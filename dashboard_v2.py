import os
import sqlite3
import json
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_file
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

app = Flask(__name__)

# --- CONFIGURATION ---
# In a real deployment, these should be in a .env file
DB_PATH = r'F:\FamilyArchive\data\archive.db'
SERVICE_ACCOUNT_FILE = r'F:\FamilyArchive\config\service-account.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

# --- GOOGLE DRIVE SETUP ---
def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# --- DATABASE HELPERS ---
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- ROUTES ---

@app.route('/')
def dashboard():
    conn = get_db_connection()
    stats = conn.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(case when status = 'pending' then 1 else 0 end) as pending,
            SUM(case when status = 'approved' then 1 else 0 end) as approved,
            SUM(case when status = 'rejected' then 1 else 0 end) as rejected
        FROM media
    ''').fetchone()
    
    recent_items = conn.execute('SELECT * FROM media ORDER BY uploaded_date DESC LIMIT 6').fetchall()
    conn.close()
    return render_template('dashboard.html', stats=stats, recent_items=recent_items)

@app.route('/pending')
def pending_review():
    search_query = request.args.get('search', '')
    conn = get_db_connection()
    if search_query:
        items = conn.execute("SELECT * FROM media WHERE status = 'pending' AND filename LIKE ? ORDER BY uploaded_date DESC", (f'%{search_query}%',)).fetchall()
    else:
        items = conn.execute("SELECT * FROM media WHERE status = 'pending' ORDER BY uploaded_date DESC").fetchall()
    conn.close()
    return render_template('gallery.html', title="Pending Review", items=items, status_filter="pending", search_query=search_query)

@app.route('/approved')
def approved_items():
    search_query = request.args.get('search', '')
    conn = get_db_connection()
    if search_query:
        items = conn.execute("SELECT * FROM media WHERE status = 'approved' AND filename LIKE ? ORDER BY uploaded_date DESC", (f'%{search_query}%',)).fetchall()
    else:
        items = conn.execute("SELECT * FROM media WHERE status = 'approved' ORDER BY uploaded_date DESC").fetchall()
    conn.close()
    return render_template('gallery.html', title="Approved Archive", items=items, status_filter="approved", search_query=search_query)

@app.route('/rejected')
def rejected_items():
    search_query = request.args.get('search', '')
    conn = get_db_connection()
    if search_query:
        items = conn.execute("SELECT * FROM media WHERE status = 'rejected' AND filename LIKE ? ORDER BY uploaded_date DESC", (f'%{search_query}%',)).fetchall()
    else:
        items = conn.execute("SELECT * FROM media WHERE status = 'rejected' ORDER BY uploaded_date DESC").fetchall()
    conn.close()
    return render_template('gallery.html', title="Rejected Items", items=items, status_filter="rejected", search_query=search_query)

# --- API ENDPOINTS ---

@app.route('/api/approve/<drive_id>', methods=['POST'])
def approve_item(drive_id):
    conn = get_db_connection()
    conn.execute("UPDATE media SET status = 'approved', reviewed_date = ? WHERE drive_id = ?", (datetime.now().isoformat(), drive_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/reject/<drive_id>', methods=['POST'])
def reject_item(drive_id):
    conn = get_db_connection()
    conn.execute("UPDATE media SET status = 'rejected', reviewed_date = ? WHERE drive_id = ?", (datetime.now().isoformat(), drive_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/bulk_action', methods=['POST'])
def bulk_action():
    data = request.json
    drive_ids = data.get('drive_ids', [])
    action = data.get('action') # 'approve' or 'reject'
    
    if not drive_ids or action not in ['approve', 'reject']:
        return jsonify({"status": "error", "message": "Invalid request"}), 400
    
    status = 'approved' if action == 'approve' else 'rejected'
    reviewed_date = datetime.now().isoformat()
    
    conn = get_db_connection()
    conn.executemany("UPDATE media SET status = ?, reviewed_date = ? WHERE drive_id = ?", 
                     [(status, reviewed_date, d_id) for d_id in drive_ids])
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "count": len(drive_ids)})

@app.route('/thumbnail/<drive_id>')
def get_thumbnail(drive_id):
    service = get_drive_service()
    request = service.files().get_media(fileId=drive_id)
    file_stream = io.BytesIO()
    downloader = MediaIoBaseDownload(file_stream, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    
    file_stream.seek(0)
    return send_file(file_stream, mimetype='image/jpeg')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
