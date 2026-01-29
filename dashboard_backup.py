"""
Family Archive Vault - Dashboard
Phase 1: Basic web interface for reviewing media
"""

from flask import Flask, render_template_string, jsonify, request, redirect, url_for
import sqlite3
import json
from pathlib import Path
from datetime import datetime

app = Flask(__name__)

# Configuration
BASE_DIR = Path(r"F:\FamilyArchive")
DATABASE_FILE = BASE_DIR / "data" / "archive.db"
FOLDER_IDS_FILE = BASE_DIR / "config" / "drive_folders.json"

# Load folder IDs
with open(FOLDER_IDS_FILE) as f:
    FOLDER_IDS = json.load(f)

def get_db():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# HTML Templates
LAYOUT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Family Archive Vault</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e; color: #eee; line-height: 1.6;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { 
            background: linear-gradient(135deg, #16213e 0%, #0f3460 100%);
            padding: 20px; margin-bottom: 20px; border-radius: 10px;
        }
        header h1 { color: #e94560; font-size: 1.8em; }
        header p { color: #94a3b8; font-size: 0.9em; }
        nav { margin-top: 15px; }
        nav a { 
            color: #94a3b8; text-decoration: none; margin-right: 20px;
            padding: 8px 16px; border-radius: 5px; transition: all 0.3s;
        }
        nav a:hover, nav a.active { background: #e94560; color: white; }
        .stats-grid { 
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px; margin-bottom: 30px;
        }
        .stat-card {
            background: #16213e; padding: 20px; border-radius: 10px;
            border-left: 4px solid #e94560;
        }
        .stat-card h3 { color: #94a3b8; font-size: 0.85em; text-transform: uppercase; }
        .stat-card .value { font-size: 2em; color: #e94560; font-weight: bold; }
        .media-grid {
            display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 20px;
        }
        .media-card {
            background: #16213e; border-radius: 10px; overflow: hidden;
            transition: transform 0.3s;
        }
        .media-card:hover { transform: translateY(-5px); }
        .media-card .preview {
            height: 180px; background: #0f3460; display: flex;
            align-items: center; justify-content: center; color: #94a3b8;
        }
        .media-card .preview img { max-width: 100%; max-height: 100%; object-fit: cover; }
        .media-card .info { padding: 15px; }
        .media-card .filename { 
            font-weight: bold; white-space: nowrap; overflow: hidden;
            text-overflow: ellipsis; margin-bottom: 8px;
        }
        .media-card .meta { color: #94a3b8; font-size: 0.85em; }
        .media-card .actions { 
            display: flex; gap: 10px; margin-top: 12px; padding-top: 12px;
            border-top: 1px solid #0f3460;
        }
        .btn {
            padding: 8px 16px; border: none; border-radius: 5px;
            cursor: pointer; font-size: 0.9em; transition: all 0.3s;
        }
        .btn-approve { background: #10b981; color: white; }
        .btn-reject { background: #ef4444; color: white; }
        .btn-view { background: #3b82f6; color: white; }
        .btn:hover { opacity: 0.8; }
        .status-badge {
            display: inline-block; padding: 3px 8px; border-radius: 4px;
            font-size: 0.75em; text-transform: uppercase;
        }
        .status-pending { background: #f59e0b; color: #1a1a2e; }
        .status-approved { background: #10b981; color: white; }
        .status-rejected { background: #ef4444; color: white; }
        .empty-state {
            text-align: center; padding: 60px 20px; color: #94a3b8;
        }
        .empty-state h2 { margin-bottom: 10px; }
        .refresh-btn {
            background: #e94560; color: white; padding: 12px 24px;
            border: none; border-radius: 5px; cursor: pointer;
            font-size: 1em; margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Family Archive Vault</h1>
            <p>Preserving memories for future generations</p>
            <nav>
                <a href="/" class="{{ 'active' if page == 'dashboard' else '' }}">Dashboard</a>
                <a href="/pending" class="{{ 'active' if page == 'pending' else '' }}">Pending Review</a>
                <a href="/approved" class="{{ 'active' if page == 'approved' else '' }}">Approved</a>
                <a href="/rejected" class="{{ 'active' if page == 'rejected' else '' }}">Rejected</a>
            </nav>
        </header>
        {{ content | safe }}
    </div>
</body>
</html>
"""

DASHBOARD_CONTENT = """
<div class="stats-grid">
    <div class="stat-card">
        <h3>Total Items</h3>
        <div class="value">{{ stats.total }}</div>
    </div>
    <div class="stat-card">
        <h3>Pending Review</h3>
        <div class="value">{{ stats.pending or 0 }}</div>
    </div>
    <div class="stat-card">
        <h3>Approved</h3>
        <div class="value">{{ stats.approved or 0 }}</div>
    </div>
    <div class="stat-card">
        <h3>Total Size</h3>
        <div class="value">{{ stats.total_size_mb }} MB</div>
    </div>
</div>

<h2 style="margin-bottom: 20px;">Quick Actions</h2>
<form action="/scan" method="post" style="display: inline;">
    <button type="submit" class="refresh-btn">Scan INBOX for New Files</button>
</form>
<a href="https://drive.google.com/drive/folders/{{ inbox_id }}" target="_blank" 
   style="margin-left: 15px; color: #3b82f6;">Open INBOX in Drive &rarr;</a>
"""

MEDIA_LIST_CONTENT = """
<h2 style="margin-bottom: 20px;">{{ title }} ({{ items|length }})</h2>
{% if items %}
<div class="media-grid">
    {% for item in items %}
    <div class="media-card">
        <div class="preview">
            {% if item.mime_type and item.mime_type.startswith('image/') %}
            <span>Image: {{ item.filename[:20] }}...</span>
            {% elif item.mime_type and item.mime_type.startswith('video/') %}
            <span>Video: {{ item.filename[:20] }}...</span>
            {% else %}
            <span>{{ item.mime_type or 'Unknown' }}</span>
            {% endif %}
        </div>
        <div class="info">
            <div class="filename" title="{{ item.filename }}">{{ item.filename }}</div>
            <div class="meta">
                <span class="status-badge status-{{ item.status }}">{{ item.status }}</span><br>
                Size: {{ (item.size_bytes or 0) // 1024 }} KB<br>
                Uploaded: {{ item.uploaded_at[:10] if item.uploaded_at else 'Unknown' }}
            </div>
            <div class="actions">
                <a href="https://drive.google.com/file/d/{{ item.drive_id }}/view" target="_blank" class="btn btn-view">View</a>
                {% if item.status == 'pending' %}
                <form action="/approve/{{ item.id }}" method="post" style="display:inline;">
                    <button type="submit" class="btn btn-approve">Approve</button>
                </form>
                <form action="/reject/{{ item.id }}" method="post" style="display:inline;">
                    <button type="submit" class="btn btn-reject">Reject</button>
                </form>
                {% endif %}
            </div>
        </div>
    </div>
    {% endfor %}
</div>
{% else %}
<div class="empty-state">
    <h2>No items found</h2>
    <p>{% if status == 'pending' %}Upload files to the INBOX folder to get started.{% endif %}</p>
</div>
{% endif %}
"""

@app.route("/")
def dashboard():
    conn = get_db()
    cursor = conn.cursor()
    
    stats = {"total": 0, "total_size_mb": 0.0}
    cursor.execute("SELECT COUNT(*) FROM media")
    stats["total"] = cursor.fetchone()[0]
    
    cursor.execute("SELECT status, COUNT(*) FROM media GROUP BY status")
    for row in cursor.fetchall():
        stats[row[0]] = row[1]
    
    cursor.execute("SELECT SUM(size_bytes) FROM media")
    total_bytes = cursor.fetchone()[0] or 0
    stats["total_size_mb"] = round(total_bytes / (1024 * 1024), 2)
    
    conn.close()
    
    content = render_template_string(DASHBOARD_CONTENT, stats=stats, inbox_id=FOLDER_IDS["INBOX"])
    return render_template_string(LAYOUT, content=content, page="dashboard")


@app.route("/pending")
def pending():
    return media_list("pending", "Pending Review")

@app.route("/approved")
def approved():
    return media_list("approved", "Approved Items")

@app.route("/rejected")
def rejected():
    return media_list("rejected", "Rejected Items")

def media_list(status, title):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM media WHERE status = ? ORDER BY created_at DESC", (status,))
    items = cursor.fetchall()
    conn.close()
    
    content = render_template_string(MEDIA_LIST_CONTENT, items=items, title=title, status=status)
    return render_template_string(LAYOUT, content=content, page=status)


@app.route("/scan", methods=["POST"])
def scan():
    # Run the worker
    import subprocess
    subprocess.run([r"C:\Python313\python.exe", str(BASE_DIR / "worker.py")], capture_output=True)
    return redirect(url_for("dashboard"))


@app.route("/approve/<int:media_id>", methods=["POST"])
def approve(media_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE media SET status = 'approved', approved_at = ? WHERE id = ?", 
                   (datetime.now().isoformat(), media_id))
    cursor.execute("INSERT INTO process_log (media_id, action, details) VALUES (?, 'approved', 'Approved by user')",
                   (media_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("pending"))


@app.route("/reject/<int:media_id>", methods=["POST"])
def reject(media_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE media SET status = 'rejected' WHERE id = ?", (media_id,))
    cursor.execute("INSERT INTO process_log (media_id, action, details) VALUES (?, 'rejected', 'Rejected by user')",
                   (media_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("pending"))


@app.route("/api/stats")
def api_stats():
    conn = get_db()
    cursor = conn.cursor()
    
    stats = {}
    cursor.execute("SELECT status, COUNT(*) FROM media GROUP BY status")
    for row in cursor.fetchall():
        stats[row[0]] = row[1]
    
    conn.close()
    return jsonify(stats)


if __name__ == "__main__":
    print("Starting Family Archive Dashboard at http://localhost:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)
