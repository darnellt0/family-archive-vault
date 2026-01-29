import os
import sqlite3
import json
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_file
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import math

app = Flask(__name__)

# --- CONFIGURATION ---
DB_PATH = r'F:\FamilyArchive\data\archive.db'
SERVICE_ACCOUNT_FILE = r'F:\FamilyArchive\config\service-account.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
ITEMS_PER_PAGE = 12

# --- GOOGLE DRIVE SETUP ---
def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# --- DATABASE HELPERS ---
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- PAGINATION HELPER ---
def paginate_items(items, page=1):
    total_items = len(items)
    if total_items == 0:
        return {'items': [], 'current_page': 1, 'total_pages': 1, 'total_items': 0, 'has_prev': False, 'has_next': False}
    
    total_pages = math.ceil(total_items / ITEMS_PER_PAGE)
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    
    return {
        'items': items[start_idx:end_idx],
        'current_page': page,
        'total_pages': total_pages,
        'total_items': total_items,
        'has_prev': page > 1,
        'has_next': page < total_pages
    }

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

def get_gallery_items(status, search_query, sort_by):
    conn = get_db_connection()
    
    # Base query
    query = f"SELECT * FROM media WHERE status = ?"
    params = [status]
    
    # Search
    if search_query:
        query += " AND filename LIKE ?"
        params.append(f'%{search_query}%')
    
    # Sorting
    if sort_by == 'oldest':
        query += " ORDER BY uploaded_date ASC"
    elif sort_by == 'date_taken_newest':
        query += " ORDER BY COALESCE(date_taken, uploaded_date) DESC"
    elif sort_by == 'date_taken_oldest':
        query += " ORDER BY COALESCE(date_taken, uploaded_date) ASC"
    elif sort_by == 'filename_asc':
        query += " ORDER BY filename ASC"
    elif sort_by == 'filename_desc':
        query += " ORDER BY filename DESC"
    else:  # newest (default)
        query += " ORDER BY uploaded_date DESC"
    
    items = conn.execute(query, params).fetchall()
    conn.close()
    return items

@app.route('/pending')
def pending_review():
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'newest')
    
    items = get_gallery_items('pending', search_query, sort_by)
    paginated = paginate_items(items, page)
    
    return render_template('gallery.html', 
                         title="Pending Review", 
                         items=paginated['items'], 
                         status_filter="pending", 
                         search_query=search_query,
                         sort_by=sort_by,
                         pagination=paginated)

@app.route('/approved')
def approved_items():
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'newest')
    
    items = get_gallery_items('approved', search_query, sort_by)
    paginated = paginate_items(items, page)
    
    return render_template('gallery.html', 
                         title="Approved Archive", 
                         items=paginated['items'], 
                         status_filter="approved", 
                         search_query=search_query,
                         sort_by=sort_by,
                         pagination=paginated)

@app.route('/rejected')
def rejected_items():
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'newest')
    
    items = get_gallery_items('rejected', search_query, sort_by)
    paginated = paginate_items(items, page)
    
    return render_template('gallery.html', 
                         title="Rejected Items", 
                         items=paginated['items'], 
                         status_filter="rejected", 
                         search_query=search_query,
                         sort_by=sort_by,
                         pagination=paginated)

# --- API ENDPOINTS ---

@app.route('/api/approve/<drive_id>', methods=['POST'])
def approve_item(drive_id):
    try:
        conn = get_db_connection()
        conn.execute("UPDATE media SET status = 'approved', reviewed_date = ? WHERE drive_id = ?", 
                    (datetime.now().isoformat(), drive_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Item approved"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/reject/<drive_id>', methods=['POST'])
def reject_item(drive_id):
    try:
        conn = get_db_connection()
        conn.execute("UPDATE media SET status = 'rejected', reviewed_date = ? WHERE drive_id = ?", 
                    (datetime.now().isoformat(), drive_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Item rejected"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/bulk_action', methods=['POST'])
def bulk_action():
    try:
        data = request.json
        drive_ids = data.get('drive_ids', [])
        action = data.get('action')
        
        if not drive_ids or action not in ['approve', 'reject']:
            return jsonify({"status": "error", "message": "Invalid request"}), 400
        
        status = 'approved' if action == 'approve' else 'rejected'
        reviewed_date = datetime.now().isoformat()
        
        conn = get_db_connection()
        conn.executemany("UPDATE media SET status = ?, reviewed_date = ? WHERE drive_id = ?", 
                         [(status, reviewed_date, d_id) for d_id in drive_ids])
        conn.commit()
        conn.close()
        
        return jsonify({"status": "success", "message": f"{len(drive_ids)} items {action}ed", "count": len(drive_ids)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/thumbnail/<drive_id>')
def get_thumbnail(drive_id):
    try:
        service = get_drive_service()
        request_obj = service.files().get_media(fileId=drive_id)
        file_stream = io.BytesIO()
        downloader = MediaIoBaseDownload(file_stream, request_obj)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        file_stream.seek(0)
        return send_file(file_stream, mimetype='image/jpeg')
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
