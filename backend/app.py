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

# ============ DATABASE SETUP ============
conn = sqlite3.connect('shipments.db')
c = conn.cursor()

# Shipments table with all customer details
c.execute('''
    CREATE TABLE IF NOT EXISTS shipments (
        id TEXT PRIMARY KEY,
        tracking_number TEXT UNIQUE,
        tracking_code TEXT UNIQUE,
        customer_name TEXT,
        customer_email TEXT,
        customer_phone TEXT,
        pickup_address TEXT,
        delivery_address TEXT,
        warehouse TEXT,
        notes TEXT,
        status TEXT,
        created_at TEXT,
        last_updated TEXT
    )
''')

# Add missing columns if needed
columns_to_add = [
    ('tracking_number', 'TEXT'),
    ('tracking_code', 'TEXT'),
    ('customer_name', 'TEXT'),
    ('customer_email', 'TEXT'),
    ('customer_phone', 'TEXT'),
    ('pickup_address', 'TEXT'),
    ('delivery_address', 'TEXT'),
    ('warehouse', 'TEXT'),
    ('notes', 'TEXT')
]

for col_name, col_type in columns_to_add:
    try:
        c.execute(f'ALTER TABLE shipments ADD COLUMN {col_name} {col_type}')
        print(f"✅ Added {col_name} column")
    except sqlite3.OperationalError:
        pass  # Column already exists

# Users table
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
def generate_tracking_code():
    """Generate a unique tracking code like LGS-2024-001234"""
    conn = sqlite3.connect('shipments.db')
    c = conn.cursor()
    count = len(c.execute('SELECT id FROM shipments').fetchall()) + 1
    conn.close()
    year = datetime.now().year
    return f"LGS-{year}-{count:06d}"

def generate_tracking_number():
    """Generate a unique tracking number like LGS-ABC123XYZ"""
    return f"LGS-{uuid.uuid4().hex[:8].upper()}"

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def send_email_notification(to_email, shipment_data, tracking_url):
    """Send plain email notification (fast, no timeout)"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = to_email
        msg['Subject'] = f"Your Shipment {shipment_data['tracking_code']} Has Been Created"

        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; text-align: center;">
                <h1 style="color: white;">📦 Logistics Capture</h1>
            </div>
            <div style="padding: 20px;">
                <h2>Hello {shipment_data.get('customer_name', 'Customer')},</h2>
                <p>Your shipment has been successfully created!</p>
                <div style="background: #f0f0f0; padding: 15px; border-radius: 8px;">
                    <p><strong>📋 Tracking Code:</strong> {shipment_data['tracking_code']}</p>
                    <p><strong>🔢 Tracking Number:</strong> {shipment_data['tracking_number']}</p>
                    <p><strong>📍 Status:</strong> <span style="color: #ffc107;">PENDING</span></p>
                    <p><strong>🏭 Destination Warehouse:</strong> {shipment_data.get('warehouse', 'Not specified')}</p>
                </div>
                <div style="text-align: center; margin: 20px 0;">
                    <a href="{tracking_url}" style="background: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px;">🔗 Track Your Shipment</a>
                </div>
                <p><strong>📱 QR Code available on tracking page</strong> – open the link above to scan.</p>
                <hr>
                <p>Thank you for using Logistics Capture!</p>
            </div>
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

# ============ SHIPMENT CREATION ROUTE ============
@app.route('/api/create-shipment', methods=['POST'])
def create_shipment():
    try:
        data = request.get_json()
        
        # Get customer details
        customer_name = data.get('customer_name')
        customer_email = data.get('customer_email')
        customer_phone = data.get('customer_phone')
        pickup_address = data.get('pickup_address')
        delivery_address = data.get('delivery_address')
        warehouse = data.get('warehouse')
        notes = data.get('notes', '')
        
        # Validate required fields
        if not all([customer_name, customer_email, customer_phone, pickup_address, delivery_address, warehouse]):
            return jsonify({"error": "All required fields must be filled"}), 400
        
        # Generate unique identifiers
        shipment_id = str(uuid.uuid4())[:8]
        tracking_code = generate_tracking_code()
        tracking_number = generate_tracking_number()
        now = datetime.now().isoformat()
        
        # Save to database
        conn = sqlite3.connect('shipments.db')
        c = conn.cursor()
        c.execute('''INSERT INTO shipments 
                    (id, tracking_number, tracking_code, customer_name, customer_email, 
                     customer_phone, pickup_address, delivery_address, warehouse, notes, 
                     status, created_at, last_updated) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (shipment_id, tracking_number, tracking_code, customer_name, customer_email,
                   customer_phone, pickup_address, delivery_address, warehouse, notes,
                   'pending', now, now))
        conn.commit()
        conn.close()
        
        tracking_url = f"https://logistics-capture.onrender.com/track/{shipment_id}"
        
        # Send email notification
        shipment_data = {
            'tracking_code': tracking_code,
            'tracking_number': tracking_number,
            'customer_name': customer_name,
            'warehouse': warehouse
        }
        send_email_notification(customer_email, shipment_data, tracking_url)
        
        return jsonify({
            "status": "success",
            "shipment_id": shipment_id,
            "tracking_code": tracking_code,
            "tracking_number": tracking_number,
            "tracking_url": tracking_url,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "message": f"Shipment created successfully! Email sent to {customer_email}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============ UPDATE SHIPMENT STATUS ============
@app.route('/update/<shipment_id>/<new_status>', methods=['POST'])
def update_status(shipment_id, new_status):
    try:
        conn = sqlite3.connect('shipments.db')
        c = conn.cursor()
        
        # Get shipment details for email
        c.execute('SELECT customer_email, tracking_code, customer_name FROM shipments WHERE id = ?', (shipment_id,))
        result = c.fetchone()
        
        if not result:
            conn.close()
            return jsonify({"error": "Shipment not found"}), 404
        
        customer_email = result[0]
        tracking_code = result[1]
        customer_name = result[2]
        
        # Update status
        c.execute('UPDATE shipments SET status = ?, last_updated = ? WHERE id = ?',
                  (new_status, datetime.now().isoformat(), shipment_id))
        conn.commit()
        conn.close()
        
        # Send status update email
        if customer_email:
            try:
                msg = MIMEMultipart()
                msg['From'] = EMAIL_ADDRESS
                msg['To'] = customer_email
                msg['Subject'] = f"Shipment {tracking_code} Status Update: {new_status.upper()}"
                
                status_colors = {
                    'pending': '#ffc107',
                    'in transit': '#17a2b8',
                    'delivered': '#28a745'
                }
                color = status_colors.get(new_status, '#ffc107')
                
                body = f"""
                <html>
                <body style="font-family: Arial, sans-serif;">
                    <h2>📦 Shipment Status Update</h2>
                    <p>Hello {customer_name or 'Customer'},</p>
                    <p>Your shipment <strong>{tracking_code}</strong> has been updated.</p>
                    <p><strong>New Status:</strong> <span style="background: {color}; color: white; padding: 5px 10px; border-radius: 5px;">{new_status.upper()}</span></p>
                    <p><strong>Tracking Link:</strong> <a href="https://logistics-capture.onrender.com/track/{shipment_id}">Click here to track</a></p>
                    <hr>
                    <p>Thank you for using Logistics Capture!</p>
                </body>
                </html>
                """
                msg.attach(MIMEText(body, 'html'))
                
                server = smtplib.SMTP('smtp.gmail.com', 587)
                server.starttls()
                server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                server.send_message(msg)
                server.quit()
                print(f"✅ Status update email sent to {customer_email}")
            except Exception as e:
                print(f"❌ Status email error: {e}")
        
        return jsonify({"success": True, "shipment_id": shipment_id, "new_status": new_status})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============ TRACKING PAGE ============
@app.route('/track/<shipment_id>')
def tracking_page(shipment_id):
    conn = sqlite3.connect('shipments.db')
    c = conn.cursor()
    c.execute('SELECT * FROM shipments WHERE id = ?', (shipment_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return "<h1>Shipment not found</h1><p>Invalid tracking ID</p>", 404
    
    # Map columns by index
    tracking_code = row[2] if len(row) > 2 else 'N/A'
    tracking_number = row[1] if len(row) > 1 else 'N/A'
    customer_name = row[3] if len(row) > 3 else 'N/A'
    pickup_address = row[6] if len(row) > 6 else 'N/A'
    delivery_address = row[7] if len(row) > 7 else 'N/A'
    warehouse = row[8] if len(row) > 8 else 'N/A'
    status = row[11] if len(row) > 11 else 'pending'
    created_at = row[12] if len(row) > 12 else 'N/A'
    last_updated = row[13] if len(row) > 13 else created_at
    
    status_colors = {
        'pending': '#fff3cd',
        'in transit': '#cfe2ff',
        'delivered': '#d1e7dd'
    }
    status_color = status_colors.get(status, '#fff3cd')
    
    html_string = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Track Shipment {tracking_code}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; background: #f5f5f5; }}
            .card {{ background: white; border-radius: 15px; padding: 25px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            .status {{ padding: 20px; border-radius: 10px; margin: 20px 0; background: {status_color}; }}
            h1 {{ color: #333; margin-top: 0; }}
            .tracking-code {{ font-size: 28px; font-weight: bold; color: #007bff; }}
            .info-row {{ margin: 10px 0; padding: 10px; background: #f8f9fa; border-radius: 8px; }}
            .label {{ font-weight: bold; color: #555; }}
            .qr-code {{ text-align: center; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>📦 Shipment Tracking</h1>
            <div class="status">
                <h2>Status: {status.upper()}</h2>
            </div>
            
            <div class="info-row">
                <span class="label">📋 Tracking Code:</span> <span class="tracking-code">{tracking_code}</span>
            </div>
            <div class="info-row">
                <span class="label">🔢 Tracking Number:</span> {tracking_number}
            </div>
            <div class="info-row">
                <span class="label">👤 Customer:</span> {customer_name}
            </div>
            <div class="info-row">
                <span class="label">📍 Pickup Address:</span> {pickup_address}
            </div>
            <div class="info-row">
                <span class="label">🏠 Delivery Address:</span> {delivery_address}
            </div>
            <div class="info-row">
                <span class="label">🏭 Warehouse:</span> {warehouse}
            </div>
            <div class="info-row">
                <span class="label">📅 Created:</span> {created_at}
            </div>
            <div class="info-row">
                <span class="label">🕐 Last Updated:</span> {last_updated}
            </div>
            
            <div class="qr-code">
                <div id="qrcode"></div>
                <p><strong>📱 Scan this QR code to track this shipment</strong></p>
            </div>
        </div>
        
        <script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
        <script>
            new QRCode(document.getElementById("qrcode"), {{
                text: window.location.href,
                width: 150,
                height: 150
            }});
        </script>
    </body>
    </html>
    """
    return html_string

# ============ LIST ALL SHIPMENTS ============
@app.route('/shipments')
def list_shipments():
    conn = sqlite3.connect('shipments.db')
    c = conn.cursor()
    c.execute('SELECT id, tracking_code, tracking_number, customer_name, customer_email, status, created_at FROM shipments ORDER BY created_at DESC')
    rows = c.fetchall()
    conn.close()
    shipments = [{"id": r[0], "tracking_code": r[1], "tracking_number": r[2], "customer_name": r[3], "customer_email": r[4], "status": r[5], "created_at": r[6]} for r in rows]
    return jsonify(shipments)

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
        SELECT s.id, s.tracking_code, s.tracking_number, s.status, s.created_at, s.customer_name
        FROM shipments s
        JOIN user_shipments us ON s.id = us.shipment_id
        WHERE us.user_id = ?
        ORDER BY s.created_at DESC
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    
    shipments = [{"id": r[0], "tracking_code": r[1], "tracking_number": r[2], "status": r[3], "created_at": r[4], "customer_name": r[5]} for r in rows]
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

# ============ OCR ROUTE (for image upload) ============
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
            tracking_number = generate_tracking_number()
            tracking_code = generate_tracking_code()
            shipment_id = str(uuid.uuid4())[:8]
            now = datetime.now().isoformat()

            conn = sqlite3.connect('shipments.db')
            c = conn.cursor()
            c.execute('''INSERT INTO shipments 
                        (id, tracking_number, tracking_code, full_text, status, created_at, last_updated, customer_email) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                      (shipment_id, tracking_number, tracking_code, full_text[:1000], 'pending', now, now, customer_email))
            conn.commit()
            conn.close()

            tracking_url = f"https://logistics-capture.onrender.com/track/{shipment_id}"
            
            if customer_email:
                shipment_data = {'tracking_code': tracking_code, 'tracking_number': tracking_number, 'customer_name': 'Customer', 'warehouse': 'N/A'}
                send_email_notification(customer_email, shipment_data, tracking_url)

            return jsonify({
                "status": "success",
                "shipment_id": shipment_id,
                "tracking_code": tracking_code,
                "tracking_url": tracking_url,
                "tracking_number": tracking_number,
                "full_text": full_text[:500]
            })
        else:
            return jsonify({"error": "No text found"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Health check
@app.route('/health')
def health():
    return jsonify({"status": "alive"})

@app.route('/')
def home():
    return jsonify({"message": "Logistics Capture API", "status": "running"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
