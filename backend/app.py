from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
import base64
import requests
import re
import sqlite3
import uuid
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
import os

app = Flask(__name__)
CORS(app)

# Gmail credentials (replace with your actual email)
GMAIL_EMAIL = "cobweb.sticky@gmail.com"  # <-- CHANGE THIS
GMAIL_APP_PASSWORD = "jgjw xljy kxrk gxyd".replace(" ", "")  # Your app password

OCR_API_KEY = "helloworld"
OCR_API_URL = "https://api.ocr.space/parse/image"

# Create database
conn = sqlite3.connect('shipments.db')
c = conn.cursor()
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
conn.commit()
conn.close()

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

def send_email_notification(to_email, shipment_id, new_status, tracking_url):
    """Send email using Gmail SMTP"""
    try:
        subject = f"📦 Shipment {shipment_id} Status Update"
        body = f"""
Hello,

Your shipment {shipment_id} status has been updated to: {new_status.upper()}

Track your shipment here: {tracking_url}

Thank you for using Logistics Tracking System.
"""
        
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = GMAIL_EMAIL
        msg['To'] = to_email
        
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        
        print(f"✅ Email sent to {to_email}")
        return True
        
    except Exception as e:
        print(f"❌ Email failed: {e}")
        return False

@app.route('/')
def home():
    return jsonify({"message": "Logistics Capture API", "status": "running"})

@app.route('/health')
def health():
    return jsonify({"status": "alive"})

@app.route('/ocr', methods=['POST'])
def ocr_process():
    try:
        data = request.get_json()
        if not data or 'image' not in data:
            return jsonify({"error": "No image provided"}), 400
        
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
            
            # Get customer email from request
            customer_email = request.args.get('email')
            
            conn = sqlite3.connect('shipments.db')
            c = conn.cursor()
            c.execute('INSERT INTO shipments (id, tracking_number, full_text, status, created_at, last_updated, customer_email) VALUES (?, ?, ?, ?, ?, ?, ?)',
                      (shipment_id, tracking_number, full_text[:1000], 'pending', now, now, customer_email))
            conn.commit()
            conn.close()
            
            return jsonify({
                "status": "success",
                "shipment_id": shipment_id,
                "tracking_url": f"https://logistics-capture.onrender.com/track/{shipment_id}",
                "tracking_number": tracking_number,
                "full_text": full_text[:500]
            })
        else:
            return jsonify({"error": "No text found"}), 400
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        c.execute('UPDATE shipments SET status = ?, last_updated = ? WHERE id = ?', 
                  (new_status, datetime.now().isoformat(), shipment_id))
        conn.commit()
        
        if c.rowcount == 0:
            conn.close()
            return jsonify({"error": "Shipment not found"}), 404
        
        # Get customer email
        c.execute('SELECT customer_email FROM shipments WHERE id = ?', (shipment_id,))
        row = c.fetchone()
        customer_email = row[0] if row else None
        conn.close()
        
        # Send email notification if email exists
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
        
        html_string = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Track Shipment {shipment_id}</title>
            <style>
                body {{ font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px; }}
                .status {{ padding: 20px; border-radius: 10px; margin: 20px 0; background: {status_color}; }}
                h1 {{ color: #333; }}
            </style>
        </head>
        <body>
            <h1>📦 Shipment Tracking</h1>
            <div class="status">
                <h2>Status: {row[3].upper()}</h2>
            </div>
            <p><strong>Shipment ID:</strong> {row[0]}</p>
            <p><strong>Tracking Number:</strong> {row[1] if row[1] else 'Not detected'}</p>
            <p><strong>Created:</strong> {row[4]}</p>
            <p><strong>Last Updated:</strong> {row[5] if row[5] else row[4]}</p>
            <hr>
            <h3>Extracted Text:</h3>
            <pre style="background:#f0f0f0; padding:15px;">{row[2][:500]}</pre>
        </body>
        </html>
        """
    
    return html_string

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
