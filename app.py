# app.py - 线下编写，线上部署
import os
import uuid
import qrcode
import smtplib
import sqlite3
from datetime import datetime
from io import BytesIO
from flask import Flask, render_template_string, request, jsonify
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage

EMAIL_FROM = os.environ.get("EMAIL_FROM", "touweihuimishuchu@cimc-raffles.com")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:5000")

SMTP_SERVER = "smtp.exmail.qq.com"
SMTP_PORT = 587

app = Flask(__name__)
DB_PATH = "/tmp/vote.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS meetings (id INTEGER PRIMARY KEY, title TEXT, content TEXT, start_time TEXT, end_time TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS committee_members (id INTEGER PRIMARY KEY, name TEXT, email TEXT, meeting_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS vote_tokens (id INTEGER PRIMARY KEY, token TEXT UNIQUE, member_id INTEGER, used INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS votes (id INTEGER PRIMARY KEY, member_id INTEGER, meeting_id INTEGER, decision TEXT, comment TEXT, voted_at TEXT)''')
    conn.commit()
    conn.close()

def generate_qr_code(url):
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill='black', back_color='white')

def send_email_with_qr(to_email, qr_img, title):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_FROM
    msg['To'] = to_email
    msg['Subject'] = f"【投审会表决通知】{title}"
    body = f"<div style='font-family:Arial'><h2>请微信扫码完成表决</h2><div style='text-align:center; margin:20px'><img src='cid:qr' width='180'></div></div>"
    msg.attach(MIMEText(body, 'html'))
    buf = BytesIO()
    qr_img.save(buf, format='PNG')
    buf.seek(0)
    img = MIMEImage(buf.read())
    img.add_header('Content-ID', '<qr>')
    msg.attach(img)
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"邮件发送失败: {e}")
        return False

SECRETARY_HTML = '''
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>投审会秘书</title>
<style>body{font-family:Arial;padding:20px}input,textarea{width:100%;padding:8px;margin:5px 0}button{padding:10px 20px;background:#1E88E5;color:white;border:none}</style>
</head>
<body>
<h2>创建投审会表决</h2>
<form method="post">
  标题: <input name="title" required><br>
  内容: <textarea name="content" rows="4"></textarea><br>
  开始: <input type="datetime-local" name="start" required><br>
  结束: <input type="datetime-local" name="end" required><br>
  姓名（每行一个）:<br><textarea name="names" rows="5"></textarea><br>
  邮箱（每行一个）:<br><textarea name="emails" rows="5"></textarea><br>
  <button type="submit">发送通知邮件</button>
</form>
</body></html>
'''

VOTE_HTML = '''
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>委员表决</title>
<style>body{font-family:Arial;padding:20px}label{display:block;margin:10px 0}button{padding:12px 24px;background:#4CAF50;color:white;border:none}</style>
</head>
<body>
<h2>表决事项</h2>
<div style="background:#f0f8ff;padding:15px;margin:15px 0;">{{ content }}</div>
<form id="f">
  <input type="hidden" name="token" value="{{ token }}">
  <label><input type="radio" name="decision" value="同意" required> 同意</label>
  <label><input type="radio" name="decision" value="不同意"> 不同意</label>
  <label><input type="radio" name="decision" value="补充资料后再议"> 补充资料后再议</label>
  <textarea name="comment" placeholder="意见（可选）" style="width:100%;height:80px;margin:10px 0"></textarea>
  <button type="submit">提交表决</button>
</form>
<script>
document.getElementById('f').onsubmit=e=>{e.preventDefault();fetch('/submit',{method:'POST',body:new FormData(f)}).then(r=>r.json()).then(d=>{if(d.status=='success')alert('✅ 提交成功！');else alert('❌ '+d.error)})};
</script>
</body></html>
'''

@app.route('/')
def index():
    return '<a href="/secretary">👉 进入秘书后台</a>'

@app.route('/secretary', methods=['GET', 'POST'])
def secretary():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        start = datetime.fromisoformat(request.form['start'])
        end = datetime.fromisoformat(request.form['end'])
        names = [n.strip() for n in request.form['names'].split('\n') if n.strip()]
        emails = [e.strip() for e in request.form['emails'].split('\n') if e.strip()]
        if len(names) != len(emails): return "姓名和邮箱数量不一致！", 400
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('INSERT INTO meetings (title,content,start_time,end_time) VALUES (?,?,?,?)',
                  (title, content, start.isoformat(), end.isoformat()))
        mid = c.lastrowid
        mids = []
        for name, email in zip(names, emails):
            c.execute('INSERT INTO committee_members (name,email,meeting_id) VALUES (?,?,?)',
                      (name, email, mid))
            mids.append(c.lastrowid)
        conn.commit()
        conn.close()
        
        for i, email in enumerate(emails):
            token = str(uuid.uuid4())
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('INSERT INTO vote_tokens (token,member_id) VALUES (?,?)', (token, mids[i]))
            conn.commit()
            conn.close()
            url = f"{BASE_URL}/vote?token={token}"
            qr = generate_qr_code(url)
            send_email_with_qr(email, qr, title)
        return "✅ 会议创建成功！通知已发送。"
    return SECRETARY_HTML

@app.route('/vote')
def vote_page():
    token = request.args.get('token')
    if not token: return "无效链接", 400
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT m.content FROM vote_tokens vt JOIN committee_members cm ON vt.member_id=cm.id JOIN meetings m ON cm.meeting_id=m.id WHERE vt.token=? AND vt.used=0', (token,))
    r = c.fetchone()
    conn.close()
    if not r: return "链接无效或已使用", 400
    return render_template_string(VOTE_HTML, content=r[0], token=token)

@app.route('/submit', methods=['POST'])
def submit():
    token = request.form.get('token')
    decision = request.form.get('decision')
    if not token or not decision: return jsonify({"error": "参数缺失"}), 400
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT member_id, meeting_id FROM vote_tokens vt JOIN committee_members cm ON vt.member_id=cm.id WHERE vt.token=? AND vt.used=0', (token,))
    r = c.fetchone()
    if not r:
        conn.close()
        return jsonify({"error": "无效链接"}), 400
    mid, meetid = r
    c.execute('UPDATE vote_tokens SET used=1 WHERE token=?', (token,))
    c.execute('INSERT INTO votes (member_id,meeting_id,decision,comment,voted_at) VALUES (?,?,?,?,?)',
              (mid, meetid, decision, request.form.get('comment',''), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

if __name__ == '__main__':
    init_db()
    app.run(debug=False)