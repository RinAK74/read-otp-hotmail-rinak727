from flask import Flask, request, jsonify
import requests
import re
from datetime import datetime, timezone, timedelta
from flask import render_template_string

app = Flask(__name__)

# ========= Regex tách mã OTP ========= #
OTP_REGEX = [
    r"\b(?:code|OTP|mã)[^\d]{0,10}(\d{6})\b",  # ví dụ: OTP là 123456
    r"\b(\d{6})\b"  # fallback: bất kỳ chuỗi 6 số nào
]

# ========= Lấy access_token từ refresh_token ========= #
def get_access_token(refresh_token, client_id):
    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    data = {
        'client_id': client_id,
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'scope': 'https://graph.microsoft.com/.default'
    }
    response = requests.post(token_url, data=data)
    if response.status_code == 200:
        return response.json().get("access_token")
    return None

# ========= Đọc email qua Graph API ========= #
def read_emails(access_token, max_email=10):
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://graph.microsoft.com/v1.0/me/messages?$top={max_email}&$orderby=receivedDateTime desc"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("value", [])
    return []

# ========= Tách mã OTP từ nội dung ========= #
def extract_otp(email):
    text = f"{email.get('subject', '')} {email.get('body', {}).get('content', '')}"
    for pattern in OTP_REGEX:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None

# ========= API: hỗ trợ GET & POST ========= #
@app.route("/read_mail_otp", methods=["GET", "POST"])
def read_mail_otp():
    if request.method == "POST":
        data = request.get_json()
    else:
        data = request.args

    refresh_token = data.get("refresh_token")
    client_id = data.get("client_id")
    max_email_raw = data.get("max_email")
    # Nếu không truyền thì mặc định là lấy 1 mail gần nhất
    max_email = int(max_email_raw) if max_email_raw and max_email_raw.isdigit() else 1
    keyword = data.get("keyword", "").lower()
    time_window_raw = data.get("time_window")

    # Nếu có time_window thì chuyển sang số, còn không thì None
    #time_window_minutes = int(time_window_raw) if time_window_raw else None
    
    # Nếu có time_window thì chuyển sang số, còn không thì mặc định 5 phút
    time_window_minutes = int(time_window_raw) if time_window_raw and time_window_raw.isdigit() else 5

    if not refresh_token or not client_id:
        return jsonify({"error": "Missing refresh_token or client_id"}), 400

    access_token = get_access_token(refresh_token, client_id)
    if not access_token:
        return jsonify({"error": "Failed to get access_token"}), 401

    emails = read_emails(access_token, max_email)
    now = datetime.now(timezone.utc)
    result = []

    for email in emails:
        # Lọc thời gian nếu có yêu cầu
        received_time_str = email.get("receivedDateTime")
        if received_time_str:
            received_time = datetime.fromisoformat(received_time_str.replace("Z", "+00:00"))
            if time_window_minutes is not None:
                if (now - received_time) > timedelta(minutes=time_window_minutes):
                    continue

        # Lọc từ khóa nếu có yêu cầu
        subject = email.get("subject", "").lower()
        body = email.get("body", {}).get("content", "").lower()
        if keyword and keyword not in subject and keyword not in body:
            continue

        # Trích OTP
        otp = extract_otp(email)
        if otp:
            result.append({
                "from": email.get("from", {}).get("emailAddress", {}).get("address", ""),
                "subject": email.get("subject", ""),
                "code": otp,
                "received": received_time_str
            })
            
    if not result:
        return jsonify([{"code": "0"}])

    return jsonify(result)

@app.route("/")
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Get Mail Code</title>
        <style>
            body { font-family: sans-serif; max-width: 600px; margin: 30px auto; }
            input, button { padding: 10px; width: 100%; margin: 5px 0; font-size: 16px; }
            pre { background: #f0f0f0; padding: 10px; white-space: pre-wrap; }
        </style>
    </head>
    <body>
        <h2>🔐 Lấy mã OTP từ email (Hotmail/Outlook)</h2>
        <input type="text" id="refresh_token" placeholder="Refresh Token">
        <input type="text" id="client_id" placeholder="Client ID">
        <input type="text" id="keyword" placeholder="Lọc từ khoá (ví dụ: facebook, twitter - có thể để trống)">
        <input type="number" id="time_window" placeholder="Thời gian lọc (phút, để trống mặc định là 5 phút)">
        <input type="number" id="max_email" placeholder="Số lượng mail tối đa (để trống mặc định là 1 email)">
        <button onclick="getCode()">Get Code</button>
        <pre id="output">👉 Nhập thông tin rồi nhấn nút Get Code...</pre>

        <script>
            async function getCode() {
                const token = document.getElementById("refresh_token").value;
                const clientId = document.getElementById("client_id").value;
                const keyword = document.getElementById("keyword").value;
                const timeWindow = document.getElementById("time_window").value;
                const maxEmail = document.getElementById("max_email").value;

                const params = new URLSearchParams({
                    refresh_token: token,
                    client_id: clientId,
                    keyword: keyword,
                    time_window: timeWindow,
                    max_email: maxEmail
                });

                document.getElementById("output").innerText = "⏳ Đang xử lý...";

                try {
                    const res = await fetch("/read_mail_otp?" + params.toString());
                    const data = await res.json();
                    document.getElementById("output").innerText = JSON.stringify(data, null, 2);
                } catch (err) {
                    document.getElementById("output").innerText = "❌ Lỗi: " + err;
                }
            }
        </script>
    </body>
    </html>
    """)

# ========= Chạy server ========= #
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
