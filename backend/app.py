from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
import base64
import requests
import re
import sqlite3
import uuid
import hashlib
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
CORS(app)

# Email configuration
EMAIL_ADDRESS = "cobweb.sticky@gmail.com"
EMAIL_PASSWORD = "rrzp sbdh akhc jalf".replace(" ", "")

OCR_API_KEY = "helloworld"
OCR_API_URL = "https://api.ocr.space/parse/image"

# ============ DATABASE SETUP ============
conn = sqlite3.connect('shipments.db')
c = conn.cursor()

# Shipments table
c.execute('''
    CREATE TABLE IF NOT EXISTS shipments (
        id TEXT PRIMARY KEY,
        tracking_number TEXT,
        full_text TEXT,
        status TEXT,
        created_at TEXT,
        last_updated TEXT,
        customer_email TEXT
    )
''')

# Add customer_email column if missing
try:
    c.execute('ALTER TABLE shipments ADD COLUMN customer_email TEXT')
    print("✅ Added customer_email column")
except sqlite3.OperationalError:
    print("ℹ️ customer_email column already exists")

# Users table for login portal
c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        name TEXT,
        created_at TEXT
    )
''')

# Link shipments to users
c.execute('''
    CREATE TABLE IF NOT EXISTS user_shipments (
        user_id TEXT,
        shipment_id TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (shipment_id) REFERENCES shipments(id),
        PRIMARY KEY (user_id, shipment_id)
    )
''')

conn.commit()
conn.close()

# ============ HELPER FUNCTIONS ============
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def send_email_notification(to_email, shipment_id, status, tracking_url):
    if not to_email:
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = to_email
        msg['Subject'] = f"Shipment {shipment_id} Status Update: {status.upper()}"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2>📦 Shipment Status Update</h2>
            <p>Your shipment <strong>{shipment_id}</strong> has been updated.</p>
            <p><strong>New Status:</strong> <span style="color: #007bff;">{status.upper()}</span></p>
            <p><strong>Tracking Link:</strong> <a href="{tracking_url}">{tracking_url}</a></p>
            <hr>
            <p>Thank you for using our logistics service!</p>
        </body>
        </html>
        """
        msg.attach(MIMEText(body, 'html'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"✅ Email sent to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False

def extract_tracking_number(text):
    patterns = [
        r'\b1Z[A-Z0-9]{16}\b',
        r'\b\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b',
        r'\b[A-Z]{2}\d{9}[A-Z]{2}\b',
        r'\b\d{12,22}\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None

# ============ BASIC ROUTES ============
@app.route('/')
def home():
    return jsonify({"message": "Logistics Capture API", "status": "running"})

@app.route('/health')
def health():
    return jsonify({"status": "alive"})

# ============ OCR ROUTE ============
@app.route('/ocr', methods=['POST'])
def ocr_process():
    try:
        data = request.get_json()
        if not data or 'image' not in data:
            return jsonify({"error": "No image provided"}), 400

        customer_email = data.get('email', None)

        if ',' in data['image']:
            image_data = data['image'].split(',')[1]
        else:
            image_data = data['image']

        image_bytes = base64.b64decode(image_data)

        response = requests.post(
            OCR_API_URL,
            files={'file': ('image.jpg', image_bytes, 'image/jpeg')},
            data={'apikey': OCR_API_KEY, 'language': 'eng'}
        )

        result = response.json()

        if result.get('ParsedResults'):
            full_text = result['ParsedResults'][0]['ParsedText']
            tracking_number = extract_tracking_number(full_text)

            shipment_id = str(uuid.uuid4())[:8]
            now = datetime.now().isoformat()

            conn = sqlite3.connect('shipments.db')
            c = conn.cursor()
            c.execute('''INSERT INTO shipments 
                        (id, tracking_number, full_text, status, created_at, last_updated, customer_email) 
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                      (shipment_id, tracking_number, full_text[:1000], 'pending', now, now, customer_email))
            conn.commit()
            conn.close()

            tracking_url = f"https://logistics-capture.onrender.com/track/{shipment_id}"
            
            if customer_email:
                send_email_notification(customer_email, shipment_id, 'pending', tracking_url)

            return jsonify({
                "status": "success",
                "shipment_id": shipment_id,
                "tracking_url": tracking_url,
                "tracking_number": tracking_number,
                "full_text": full_text[:500]
            })
        else:
            return jsonify({"error": "No text found"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============ SHIPMENT ROUTES ============
@app.route('/shipments')
def list_shipments():
    conn = sqlite3.connect('shipments.db')
    c = conn.cursor()
    c.execute('SELECT id, tracking_number, status, created_at, customer_email FROM shipments ORDER BY created_at DESC')
    rows = c.fetchall()
    conn.close()
    shipments = [{"id": r[0], "tracking_number": r[1], "status": r[2], "created_at": r[3], "customer_email": r[4]} for r in rows]
    return jsonify(shipments)

@app.route('/update/<shipment_id>/<new_status>', methods=['POST'])
def update_status(shipment_id, new_status):
    try:
        conn = sqlite3.connect('shipments.db')
        c = conn.cursor()
        c.execute('SELECT customer_email FROM shipments WHERE id = ?', (shipment_id,))
        result = c.fetchone()
        customer_email = result[0] if result else None

        c.execute('UPDATE shipments SET status = ?, last_updated = ? WHERE id = ?',
                  (new_status, datetime.now().isoformat(), shipment_id))
        conn.commit()

        if c.rowcount == 0:
            conn.close()
            return jsonify({"error": "Shipment not found"}), 404

        conn.close()

        if customer_email:
            tracking_url = f"https://logistics-capture.onrender.com/track/{shipment_id}"
            send_email_notification(customer_email, shipment_id, new_status, tracking_url)

        return jsonify({"success": True, "shipment_id": shipment_id, "new_status": new_status})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/track/<shipment_id>')
def tracking_page(shipment_id):
    conn = sqlite3.connect('shipments.db')
    c = conn.cursor()
    c.execute('SELECT * FROM shipments WHERE id = ?', (shipment_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        html_string = "<h1>Shipment not found</h1><p>Invalid tracking ID</p>"
    else:
        status_color = {
            'pending': '#fff3cd',
            'in transit': '#cfe2ff',
            'delivered': '#d1e7dd'
        }.get(row[3].lower(), '#fff3cd')
        
        status_border = {
            'pending': '#ffc107',
            'in transit': '#0d6efd',
            'delivered': '#198754'
        }.get(row[3].lower(), '#ffc107')

        html_string = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Track Shipment {shipment_id}</title>
            <style>
                body {{ font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px; }}
                .status {{ padding: 20px; border-radius: 10px; margin: 20px 0; background: {status_color}; border: 1px solid {status_border}; }}
                h1 {{ color: #333; }}
                .tracking-number {{ font-size: 24px; font-weight: bold; color: #007bff; }}
            </style>
        </head>
        <body>
            <h1>📦 Shipment Tracking</h1>
            <div class="status">
                <h2>Status: {row[3].upper()}</h2>
            </div>
            <p><strong>Shipment ID:</strong> {row[0]}</p>
            <p><strong>Tracking Number:</strong> <span class="tracking-number">{row[1] if row[1] else 'Not detected'}</span></p>
            <p><strong>Created:</strong> {row[4]}</p>
            <p><strong>Last Updated:</strong> {row[5] if row[5] else row[4]}</p>
            <hr>
            <h3>Extracted Text:</h3>
            <pre style="background:#f0f0f0; padding:15px; border-radius:5px; overflow:auto;">{row[2][:500]}</pre>
            <p><a href="/shipments">← View all shipments</a></p>
            <p><a href="https://logistics-frontend-x78f.onrender.com/customer-portal.html">🔐 Customer Portal →</a></p>
        </body>
        </html>
        """

    return html_string

# ============ SCANNER DIRECT ENDPOINT ============
@app.route('/api/create-from-tracking', methods=['POST'])
def create_from_tracking():
    try:
        data = request.get_json()
        tracking_number = data.get('tracking_number')
        customer_email = data.get('email')
        
        if not tracking_number:
            return jsonify({"error": "Tracking number required"}), 400
        
        shipment_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        full_text = f"Tracking Number: {tracking_number}"
        
        conn = sqlite3.connect('shipments.db')
        c = conn.cursor()
        c.execute('''INSERT INTO shipments 
                    (id, tracking_number, full_text, status, created_at, last_updated, customer_email) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (shipment_id, tracking_number, full_text[:1000], 'pending', now, now, customer_email))
        conn.commit()
        conn.close()
        
        tracking_url = f"https://logistics-capture.onrender.com/track/{shipment_id}"
        
        if customer_email:
            send_email_notification(customer_email, shipment_id, 'pending', tracking_url)
        
        return jsonify({
            "status": "success",
            "shipment_id": shipment_id,
            "tracking_url": tracking_url,
            "tracking_number": tracking_number,
            "full_text": full_text
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============ AUTHENTICATION ROUTES ============
@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        name = data.get('name')
        
        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400
        
        user_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        hashed_pw = hash_password(password)
        
        conn = sqlite3.connect('shipments.db')
        c = conn.cursor()
        
        try:
            c.execute('INSERT INTO users (id, email, password, name, created_at) VALUES (?, ?, ?, ?, ?)',
                      (user_id, email, hashed_pw, name, now))
            conn.commit()
            return jsonify({"success": True, "user_id": user_id, "message": "Registration successful"})
        except sqlite3.IntegrityError:
            return jsonify({"error": "Email already exists"}), 400
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        
        conn = sqlite3.connect('shipments.db')
        c = conn.cursor()
        c.execute('SELECT id, password, name FROM users WHERE email = ?', (email,))
        user = c.fetchone()
        conn.close()
        
        if user and user[1] == hash_password(password):
            return jsonify({"success": True, "user_id": user[0], "name": user[2], "message": "Login successful"})
        else:
            return jsonify({"error": "Invalid email or password"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/user/shipments/<user_id>', methods=['GET'])
def get_user_shipments(user_id):
    conn = sqlite3.connect('shipments.db')
    c = conn.cursor()
    c.execute('''
        SELECT s.id, s.tracking_number, s.status, s.created_at, s.last_updated
        FROM shipments s
        JOIN user_shipments us ON s.id = us.shipment_id
        WHERE us.user_id = ?
        ORDER BY s.created_at DESC
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    
    shipments = [{"id": r[0], "tracking_number": r[1], "status": r[2], "created_at": r[3], "last_updated": r[4]} for r in rows]
    return jsonify(shipments)

@app.route('/api/link-shipment', methods=['POST'])
def link_shipment():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        shipment_id = data.get('shipment_id')
        
        conn = sqlite3.connect('shipments.db')
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO user_shipments (user_id, shipment_id) VALUES (?, ?)', (user_id, shipment_id))
        conn.commit()
        conn.close()
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
