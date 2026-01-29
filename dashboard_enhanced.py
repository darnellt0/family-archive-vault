from flask import Flask, render_template_string, send_file, jsonify, request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import sqlite3
import io
from datetime import datetime

app = Flask(__name__)

# Google Drive setup
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = r'F:\FamilyArchive\config\service-account.json'

def get_drive_service():
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=credentials)

def get_db_connection():
    conn = sqlite3.connect(r'F:\FamilyArchive\data\archive.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def dashboard():
    conn = get_db_connection()
    
    # Get counts for dashboard
    total_items = conn.execute('SELECT COUNT(*) as count FROM media').fetchone()['count']
    pending_count = conn.execute('SELECT COUNT(*) as count FROM media WHERE status = "pending"').fetchone()['count']
    approved_count = conn.execute('SELECT COUNT(*) as count FROM media WHERE status = "approved"').fetchone()['count']
    rejected_count = conn.execute('SELECT COUNT(*) as count FROM media WHERE status = "rejected"').fetchone()['count']
    
    # Get recent items
    recent_items = conn.execute('''
        SELECT * FROM media 
        ORDER BY COALESCE(uploaded_date, uploaded_at) DESC 
        LIMIT 6
    ''').fetchall()
    
    conn.close()
    
    return render_template_string(DASHBOARD_TEMPLATE, 
                                  total_items=total_items,
                                  pending_count=pending_count,
                                  approved_count=approved_count,
                                  rejected_count=rejected_count,
                                  recent_items=recent_items)

@app.route('/pending')
def pending_review():
    conn = get_db_connection()
    items = conn.execute('''
        SELECT * FROM media 
        WHERE status = "pending" 
        ORDER BY COALESCE(uploaded_date, uploaded_at) DESC
    ''').fetchall()
    conn.close()
    
    return render_template_string(PENDING_TEMPLATE, items=items)

@app.route('/approved')
def approved():
    conn = get_db_connection()
    items = conn.execute('''
        SELECT * FROM media 
        WHERE status = "approved" 
        ORDER BY COALESCE(uploaded_date, uploaded_at) DESC
    ''').fetchall()
    conn.close()
    
    return render_template_string(APPROVED_TEMPLATE, items=items)

@app.route('/rejected')
def rejected():
    conn = get_db_connection()
    items = conn.execute('''
        SELECT * FROM media 
        WHERE status = "rejected" 
        ORDER BY COALESCE(uploaded_date, uploaded_at) DESC
    ''').fetchall()
    conn.close()
    
    return render_template_string(REJECTED_TEMPLATE, items=items)

@app.route('/thumbnail/<drive_id>')
def serve_thumbnail(drive_id):
    try:
        service = get_drive_service()
        request_obj = service.files().get_media(fileId=drive_id)
        
        file_buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(file_buffer, request_obj)
        
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        file_buffer.seek(0)
        
        file_metadata = service.files().get(fileId=drive_id, fields='mimeType').execute()
        mime_type = file_metadata.get('mimeType', 'image/jpeg')
        
        return send_file(file_buffer, mimetype=mime_type)
    except Exception as e:
        print(f"Error serving thumbnail: {e}")
        return "Error loading image", 404

@app.route('/view/<drive_id>')
def view_full_image(drive_id):
    conn = get_db_connection()
    item = conn.execute('SELECT * FROM media WHERE drive_id = ?', (drive_id,)).fetchone()
    conn.close()
    
    if not item:
        return "Item not found", 404
    
    return render_template_string(VIEW_TEMPLATE, item=item)

@app.route('/api/approve/<drive_id>', methods=['POST'])
def approve_item(drive_id):
    conn = get_db_connection()
    conn.execute('''
        UPDATE media 
        SET status = "approved", reviewed_date = ? 
        WHERE drive_id = ?
    ''', (datetime.now().isoformat(), drive_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Item approved'})

@app.route('/api/reject/<drive_id>', methods=['POST'])
def reject_item(drive_id):
    conn = get_db_connection()
    conn.execute('''
        UPDATE media 
        SET status = "rejected", reviewed_date = ? 
        WHERE drive_id = ?
    ''', (datetime.now().isoformat(), drive_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Item rejected'})

# HTML Templates
BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Family Archive Vault</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        header {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        }
        
        h1 {
            color: #ff6b6b;
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .tagline {
            color: rgba(255, 255, 255, 0.8);
            font-size: 1.1em;
        }
        
        nav {
            display: flex;
            gap: 10px;
            margin-top: 25px;
        }
        
        .nav-btn {
            background: rgba(255, 255, 255, 0.1);
            color: white;
            border: 2px solid rgba(255, 255, 255, 0.3);
            padding: 12px 24px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 500;
            transition: all 0.3s ease;
            cursor: pointer;
        }
        
        .nav-btn:hover {
            background: rgba(255, 255, 255, 0.2);
            border-color: rgba(255, 255, 255, 0.5);
            transform: translateY(-2px);
        }
        
        .nav-btn.active {
            background: #ff6b6b;
            border-color: #ff6b6b;
        }
        
        .content {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
        }
        
        .stat-card h3 {
            font-size: 2.5em;
            margin-bottom: 5px;
        }
        
        .stat-card p {
            opacity: 0.9;
            font-size: 0.95em;
        }
        
        .gallery-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        
        .media-card {
            background: white;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        
        .media-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.15);
        }
        
        .media-thumbnail {
            width: 100%;
            height: 250px;
            object-fit: cover;
            background: #f0f0f0;
        }
        
        .media-info {
            padding: 15px;
        }
        
        .filename {
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 8px;
            word-break: break-word;
        }
        
        .badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
            margin-bottom: 8px;
        }
        
        .badge-approved {
            background: #d4edda;
            color: #155724;
        }
        
        .badge-pending {
            background: #fff3cd;
            color: #856404;
        }
        
        .badge-rejected {
            background: #f8d7da;
            color: #721c24;
        }
        
        .meta-info {
            font-size: 0.9em;
            color: #6c757d;
            margin-bottom: 15px;
        }
        
        .actions {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }
        
        .btn {
            flex: 1;
            padding: 10px;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            text-decoration: none;
            text-align: center;
            display: block;
        }
        
        .btn-view {
            background: #007bff;
            color: white;
        }
        
        .btn-view:hover {
            background: #0056b3;
        }
        
        .btn-approve {
            background: #28a745;
            color: white;
        }
        
        .btn-approve:hover {
            background: #218838;
        }
        
        .btn-reject {
            background: #dc3545;
            color: white;
        }
        
        .btn-reject:hover {
            background: #c82333;
        }
        
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #6c757d;
        }
        
        .empty-state h2 {
            margin-bottom: 10px;
            color: #495057;
        }
        
        h2 {
            color: #2c3e50;
            margin-bottom: 20px;
            font-size: 1.8em;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Family Archive Vault</h1>
            <p class="tagline">Preserving memories for future generations</p>
            <nav>
                <a href="/" class="nav-btn {% if active_page == 'dashboard' %}active{% endif %}">Dashboard</a>
                <a href="/pending" class="nav-btn {% if active_page == 'pending' %}active{% endif %}">Pending Review</a>
                <a href="/approved" class="nav-btn {% if active_page == 'approved' %}active{% endif %}">Approved</a>
                <a href="/rejected" class="nav-btn {% if active_page == 'rejected' %}active{% endif %}">Rejected</a>
            </nav>
        </header>
        
        <div class="content">
            {% block content %}{% endblock %}
        </div>
    </div>
    
    <script>
        function approveItem(driveId) {
            if (!confirm('Approve this item for archiving?')) return;
            
            fetch(`/api/approve/${driveId}`, { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        location.reload();
                    }
                })
                .catch(error => console.error('Error:', error));
        }
        
        function rejectItem(driveId) {
            if (!confirm('Reject this item? It will not be archived.')) return;
            
            fetch(`/api/reject/${driveId}`, { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        location.reload();
                    }
                })
                .catch(error => console.error('Error:', error));
        }
    </script>
</body>
</html>
'''

DASHBOARD_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
{% block content %}
<h2>Dashboard Overview</h2>

<div class="stats-grid">
    <div class="stat-card" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
        <h3>{{ total_items }}</h3>
        <p>Total Items</p>
    </div>
    <div class="stat-card" style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);">
        <h3>{{ pending_count }}</h3>
        <p>Pending Review</p>
    </div>
    <div class="stat-card" style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);">
        <h3>{{ approved_count }}</h3>
        <p>Approved</p>
    </div>
    <div class="stat-card" style="background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);">
        <h3>{{ rejected_count }}</h3>
        <p>Rejected</p>
    </div>
</div>

<h2>Recent Uploads</h2>
{% if recent_items %}
<div class="gallery-grid">
    {% for item in recent_items %}
    <div class="media-card">
        <img src="/thumbnail/{{ item.drive_id }}" alt="{{ item.filename }}" class="media-thumbnail">
        <div class="media-info">
            <div class="filename">{{ item.filename }}</div>
            <span class="badge badge-{{ item.status }}">{{ item.status.upper() }}</span>
            <div class="meta-info">
                Size: {{ (item.size_bytes / 1024)|int }} KB<br>
                Uploaded: {{ (item.uploaded_date or item.uploaded_at or 'Unknown')[:10] }}
            </div>
            <div class="actions">
                <a href="/view/{{ item.drive_id }}" class="btn btn-view">View</a>
            </div>
        </div>
    </div>
    {% endfor %}
</div>
{% else %}
<div class="empty-state">
    <h2>No items yet</h2>
    <p>Upload some photos to get started!</p>
</div>
{% endif %}
{% endblock %}
''').replace('{% if active_page == \'dashboard\' %}active{% endif %}', 'active')

PENDING_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
{% block content %}
<h2>Pending Review ({{ items|length }})</h2>

{% if items %}
<div class="gallery-grid">
    {% for item in items %}
    <div class="media-card">
        <img src="/thumbnail/{{ item.drive_id }}" alt="{{ item.filename }}" class="media-thumbnail">
        <div class="media-info">
            <div class="filename">{{ item.filename }}</div>
            <span class="badge badge-pending">PENDING</span>
            <div class="meta-info">
                Size: {{ (item.size_bytes / 1024)|int }} KB<br>
                Uploaded: {{ (item.uploaded_date or item.uploaded_at or 'Unknown')[:10] }}
            </div>
            <div class="actions">
                <a href="/view/{{ item.drive_id }}" class="btn btn-view">View</a>
            </div>
            <div class="actions">
                <button onclick="approveItem('{{ item.drive_id }}')" class="btn btn-approve">✓ Approve</button>
                <button onclick="rejectItem('{{ item.drive_id }}')" class="btn btn-reject">✗ Reject</button>
            </div>
        </div>
    </div>
    {% endfor %}
</div>
{% else %}
<div class="empty-state">
    <h2>No items pending review</h2>
    <p>All caught up! Check back when new items are uploaded.</p>
</div>
{% endif %}
{% endblock %}
''').replace('{% if active_page == \'pending\' %}active{% endif %}', 'active')

APPROVED_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
{% block content %}
<h2>Approved Items ({{ items|length }})</h2>

{% if items %}
<div class="gallery-grid">
    {% for item in items %}
    <div class="media-card">
        <img src="/thumbnail/{{ item.drive_id }}" alt="{{ item.filename }}" class="media-thumbnail">
        <div class="media-info">
            <div class="filename">{{ item.filename }}</div>
            <span class="badge badge-approved">APPROVED</span>
            <div class="meta-info">
                Size: {{ (item.size_bytes / 1024)|int }} KB<br>
                Uploaded: {{ (item.uploaded_date or item.uploaded_at or 'Unknown')[:10] }}
            </div>
            <div class="actions">
                <a href="/view/{{ item.drive_id }}" class="btn btn-view">View</a>
            </div>
        </div>
    </div>
    {% endfor %}
</div>
{% else %}
<div class="empty-state">
    <h2>No approved items yet</h2>
    <p>Items you approve will appear here.</p>
</div>
{% endif %}
{% endblock %}
''').replace('{% if active_page == \'approved\' %}active{% endif %}', 'active')

REJECTED_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', '''
{% block content %}
<h2>Rejected Items ({{ items|length }})</h2>

{% if items %}
<div class="gallery-grid">
    {% for item in items %}
    <div class="media-card">
        <img src="/thumbnail/{{ item.drive_id }}" alt="{{ item.filename }}" class="media-thumbnail">
        <div class="media-info">
            <div class="filename">{{ item.filename }}</div>
            <span class="badge badge-rejected">REJECTED</span>
            <div class="meta-info">
                Size: {{ (item.size_bytes / 1024)|int }} KB<br>
                Uploaded: {{ (item.uploaded_date or item.uploaded_at or 'Unknown')[:10] }}
            </div>
            <div class="actions">
                <a href="/view/{{ item.drive_id }}" class="btn btn-view">View</a>
            </div>
        </div>
    </div>
    {% endfor %}
</div>
{% else %}
<div class="empty-state">
    <h2>No rejected items</h2>
    <p>Items you reject will appear here.</p>
</div>
{% endif %}
{% endblock %}
''').replace('{% if active_page == \'rejected\' %}active{% endif %}', 'active')

VIEW_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ item.filename }} - Family Archive Vault</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #1a1a1a;
            color: white;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        .header {
            background: rgba(0, 0, 0, 0.5);
            padding: 15px 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            backdrop-filter: blur(10px);
        }
        
        .back-btn {
            color: white;
            text-decoration: none;
            font-size: 1.2em;
            padding: 8px 16px;
            border-radius: 6px;
            background: rgba(255, 255, 255, 0.1);
            transition: all 0.3s ease;
        }
        
        .back-btn:hover {
            background: rgba(255, 255, 255, 0.2);
        }
        
        .viewer {
            flex: 1;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .image-container {
            max-width: 100%;
            max-height: 90vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        
        .full-image {
            max-width: 100%;
            max-height: 90vh;
            object-fit: contain;
            border-radius: 8px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
        }
        
        .info-panel {
            background: rgba(0, 0, 0, 0.8);
            padding: 20px 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .info-details {
            flex: 1;
        }
        
        .filename {
            font-size: 1.3em;
            font-weight: 600;
            margin-bottom: 10px;
        }
        
        .meta {
            color: rgba(255, 255, 255, 0.7);
            font-size: 0.95em;
        }
        
        .actions {
            display: flex;
            gap: 10px;
        }
        
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .btn-approve {
            background: #28a745;
            color: white;
        }
        
        .btn-approve:hover {
            background: #218838;
        }
        
        .btn-reject {
            background: #dc3545;
            color: white;
        }
        
        .btn-reject:hover {
            background: #c82333;
        }
        
        .badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
            margin-left: 10px;
        }
        
        .badge-approved {
            background: #d4edda;
            color: #155724;
        }
        
        .badge-pending {
            background: #fff3cd;
            color: #856404;
        }
        
        .badge-rejected {
            background: #f8d7da;
            color: #721c24;
        }
    </style>
</head>
<body>
    <div class="header">
        <a href="javascript:history.back()" class="back-btn">← Back</a>
        <span>Family Archive Vault</span>
    </div>
    
    <div class="viewer">
        <div class="image-container">
            <img src="/thumbnail/{{ item.drive_id }}" alt="{{ item.filename }}" class="full-image">
        </div>
    </div>
    
    <div class="info-panel">
        <div class="info-details">
            <div class="filename">
                {{ item.filename }}
                <span class="badge badge-{{ item.status }}">{{ item.status.upper() }}</span>
            </div>
            <div class="meta">
                Size: {{ (item.size_bytes / 1024)|int }} KB | 
                Uploaded: {{ (item.uploaded_date or item.uploaded_at or 'Unknown')[:10] }}
                {% if item.reviewed_date %} | Reviewed: {{ item.reviewed_date[:10] }}{% endif %}
            </div>
        </div>
        
        {% if item.status == 'pending' %}
        <div class="actions">
            <button onclick="approveItem('{{ item.drive_id }}')" class="btn btn-approve">✓ Approve</button>
            <button onclick="rejectItem('{{ item.drive_id }}')" class="btn btn-reject">✗ Reject</button>
        </div>
        {% endif %}
    </div>
    
    <script>
        function approveItem(driveId) {
            if (!confirm('Approve this item for archiving?')) return;
            
            fetch(`/api/approve/${driveId}`, { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        window.location.href = '/pending';
                    }
                })
                .catch(error => console.error('Error:', error));
        }
        
        function rejectItem(driveId) {
            if (!confirm('Reject this item? It will not be archived.')) return;
            
            fetch(`/api/reject/${driveId}`, { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        window.location.href = '/pending';
                    }
                })
                .catch(error => console.error('Error:', error));
        }
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
