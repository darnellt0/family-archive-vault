import os
import sqlite3
import json
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_file, abort
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import math
from semantic_search import semantic_search
from duplicate_detection import get_duplicate_groups
from sharing import generate_share_link, verify_share_link, get_all_share_links, revoke_share_link

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
DB_PATH = r'F:\FamilyArchive\data\archive.db'
SERVICE_ACCOUNT_FILE = r'F:\FamilyArchive\config\service-account.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
ITEMS_PER_PAGE = 12

app = Flask(__name__, template_folder=TEMPLATE_DIR)

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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
    return render_template('dashboard_tailwind.html', stats=stats, recent_items=recent_items)

@app.route('/people')
def people_view():
    conn = get_db_connection()
    people = conn.execute('''
        SELECT c.id, c.name, f.drive_id as rep_drive_id, COUNT(f2.id) as face_count
        FROM clusters c
        JOIN faces f ON c.representative_face_id = f.id
        JOIN faces f2 ON c.id = f2.cluster_id
        GROUP BY c.id
    ''').fetchall()
    conn.close()
    return render_template('people.html', people=people)

@app.route('/person/<int:cluster_id>')
def person_gallery(cluster_id):
    page = request.args.get('page', 1, type=int)
    conn = get_db_connection()
    person = conn.execute("SELECT name FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    items = conn.execute('''
        SELECT DISTINCT m.* 
        FROM media m
        JOIN faces f ON m.drive_id = f.drive_id
        WHERE f.cluster_id = ?
        ORDER BY m.uploaded_date DESC
    ''', (cluster_id,)).fetchall()
    conn.close()
    paginated = paginate_items(items, page)
    return render_template('gallery_tailwind.html', title=f"Photos of {person['name']}", items=paginated['items'], status_filter="person", pagination=paginated, search_query="", sort_by="newest")

@app.route('/pending')
def pending_review():
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'newest')
    search_mode = request.args.get('mode', 'keyword')
    
    if search_mode == 'semantic' and search_query:
        results = semantic_search(search_query, top_k=100)
        drive_ids = [r[0] for r in results]
        conn = get_db_connection()
        placeholders = ','.join(['?' for _ in drive_ids])
        items = conn.execute(f"SELECT * FROM media WHERE status = 'pending' AND drive_id IN ({placeholders})", drive_ids).fetchall()
        conn.close()
    else:
        items = get_gallery_items('pending', search_query, sort_by)
    
    paginated = paginate_items(items, page)
    return render_template('gallery_tailwind.html', title="Pending Review", items=paginated['items'], status_filter="pending", search_query=search_query, sort_by=sort_by, pagination=paginated, search_mode=search_mode)

@app.route('/approved')
def approved_items():
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    sort_by = request.args.get('sort', 'newest')
    search_mode = request.args.get('mode', 'keyword')
    
    if search_mode == 'semantic' and search_query:
        results = semantic_search(search_query, top_k=100)
        drive_ids = [r[0] for r in results]
        conn = get_db_connection()
        placeholders = ','.join(['?' for _ in drive_ids])
        items = conn.execute(f"SELECT * FROM media WHERE status = 'approved' AND drive_id IN ({placeholders})", drive_ids).fetchall()
        conn.close()
    else:
        items = get_gallery_items('approved', search_query, sort_by)
    
    paginated = paginate_items(items, page)
    return render_template('gallery_tailwind.html', title="Approved Archive", items=paginated['items'], status_filter="approved", search_query=search_query, sort_by=sort_by, pagination=paginated, search_mode=search_mode)

@app.route('/duplicates')
def duplicates_view():
    duplicate_groups = get_duplicate_groups()
    return render_template('duplicates.html', duplicate_groups=duplicate_groups)

@app.route('/sharing')
def sharing_view():
    share_links = get_all_share_links()
    return render_template('sharing.html', share_links=share_links)

@app.route('/api/create_share', methods=['POST'])
def create_share():
    data = request.json
    name = data.get('name', 'Unnamed Share')
    expires_days = data.get('expires_days', 30)
    
    token = generate_share_link(name, expires_days)
    return jsonify({"token": token, "url": f"/share/{token}"})

@app.route('/api/revoke_share/<token>', methods=['POST'])
def revoke_share(token):
    revoke_share_link(token)
    return jsonify({"status": "success"})

@app.route('/share/<token>')
def shared_view(token):
    link = verify_share_link(token)
    if not link:
        abort(404)
    
    conn = get_db_connection()
    items = conn.execute('SELECT * FROM media WHERE status = "approved" ORDER BY uploaded_date DESC').fetchall()
    conn.close()
    
    paginated = paginate_items(items, 1)
    return render_template('gallery_tailwind.html', title=f"Shared: {link['name']}", items=paginated['items'], pagination=paginated, search_query="", sort_by="newest", is_shared=True)

def get_gallery_items(status, search_query, sort_by):
    conn = get_db_connection()
    query = f"SELECT * FROM media WHERE status = ?"
    params = [status]
    if search_query:
        query += " AND (filename LIKE ? OR ai_caption LIKE ?)"
        params.extend([f'%{search_query}%', f'%{search_query}%'])
    
    if sort_by == 'oldest': query += " ORDER BY uploaded_date ASC"
    elif sort_by == 'date_taken_newest': query += " ORDER BY COALESCE(date_taken, uploaded_date) DESC"
    elif sort_by == 'date_taken_oldest': query += " ORDER BY COALESCE(date_taken, uploaded_date) ASC"
    elif sort_by == 'filename_asc': query += " ORDER BY filename ASC"
    elif sort_by == 'filename_desc': query += " ORDER BY filename DESC"
    else: query += " ORDER BY uploaded_date DESC"
    
    items = conn.execute(query, params).fetchall()
    conn.close()
    return items

@app.route('/api/bulk_action', methods=['POST'])
def bulk_action():
    data = request.json
    drive_ids = data.get('drive_ids', [])
    action = data.get('action')
    status = 'approved' if action == 'approve' else 'rejected'
    reviewed_date = datetime.now().isoformat()
    conn = get_db_connection()
    conn.executemany("UPDATE media SET status = ?, reviewed_date = ? WHERE drive_id = ?", [(status, reviewed_date, d_id) for d_id in drive_ids])
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "count": len(drive_ids)})

@app.route('/thumbnail/<drive_id>')
def get_thumbnail(drive_id):
    service = get_drive_service()
    request_obj = service.files().get_media(fileId=drive_id)
    file_stream = io.BytesIO()
    downloader = MediaIoBaseDownload(file_stream, request_obj)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    file_stream.seek(0)
    return send_file(file_stream, mimetype='image/jpeg')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
