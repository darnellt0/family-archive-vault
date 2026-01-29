import sqlite3
import os
import json
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime

# --- Configuration ---
# Ensure these match your actual folder names
DB_NAME = "archive.db"
MEDIA_FOLDER = "media" 
THUMBNAIL_FOLDER = "thumbnails" # Or "cache" if you named it that

app = Flask(__name__)
# Enable CORS so the React app (port 5173) can talk to this Flask app (port 5000)
CORS(app) 

def get_db_connection():
    if not os.path.exists(DB_NAME):
        print(f"WARNING: {DB_NAME} not found. Ensure you are running this script from the project root.")
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# --- API Routes ---

@app.route('/api/stats')
def api_stats():
    """Returns system statistics for the React Dashboard."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Total Memories
    try:
        cursor.execute("SELECT COUNT(*) FROM media_files")
        total_files = cursor.fetchone()[0]
    except:
        total_files = 0
    
    # 2. Faces Indexed
    try:
        cursor.execute("SELECT COUNT(*) FROM faces")
        total_faces = cursor.fetchone()[0]
    except sqlite3.OperationalError:
        total_faces = 0 
        
    # 3. Searchable Video Hours
    try:
        cursor.execute("SELECT SUM(duration) FROM media_files WHERE file_type = 'video'")
        result = cursor.fetchone()[0]
        total_seconds = result if result else 0
        video_hours = f"{int(total_seconds / 3600)} hrs"
    except:
        video_hours = "0 hrs"

    conn.close()
    
    return jsonify([
        {'label': 'Total Memories', 'value': f"{total_files:,}", 'icon': 'Database', 'color': 'text-blue-400'},
        {'label': 'Faces Indexed', 'value': str(total_faces), 'icon': 'Users', 'color': 'text-purple-400'},
        {'label': 'Searchable Video', 'value': video_hours, 'icon': 'FileVideo', 'color': 'text-emerald-400'},
        {'label': 'System Status', 'value': 'Online', 'icon': 'Activity', 'color': 'text-green-400'},
    ])

@app.route('/api/recent')
def api_recent():
    """Returns the most recent media files."""
    conn = get_db_connection()
    try:
        # Fetch top 12 recent files
        files = conn.execute("SELECT * FROM media_files ORDER BY upload_date DESC LIMIT 12").fetchall()
    except:
        files = []
    conn.close()
    
    recent_items = []
    for f in files:
        # Determine type based on extension
        filename = f['filename']
        is_video = filename.lower().endswith(('.mp4', '.mov', '.avi', '.mkv'))
        item_type = 'video' if is_video else 'photo'
        
        # Use existing thumbnail logic
        recent_items.append({
            'id': f['id'],
            'type': item_type,
            'title': filename,
            'date': f['upload_date'][:10] if f['upload_date'] else 'Unknown',
            'thumbnail': f"http://localhost:5000/thumbnails/{filename}.jpg" 
        })
        
    return jsonify(recent_items)

@app.route('/api/transcript/<int:video_id>')
def api_transcript(video_id):
    """Returns transcript segments for the video player."""
    conn = get_db_connection()
    # Adjust 'transcript_path' column name if yours is different (e.g. 'whisper_json')
    try:
        video = conn.execute("SELECT filename, transcript_path FROM media_files WHERE id = ?", (video_id,)).fetchone()
    except:
        video = None
    conn.close()
    
    if not video or not video['transcript_path'] or not os.path.exists(video['transcript_path']):
        return jsonify([]) 

    try:
        with open(video['transcript_path'], 'r') as f:
            data = json.load(f)
            segments = []
            for seg in data.get('segments', []):
                start = seg['start']
                m, s = divmod(start, 60)
                time_str = f"{int(m):02}:{int(s):02}"
                segments.append({'time': time_str, 'text': seg['text']})
            return jsonify(segments)
    except Exception as e:
        print(f"Error reading transcript: {e}")
        return jsonify([{'time': '00:00', 'text': 'Error loading transcript.'}])

@app.route('/api/shares')
def api_shares():
    """Returns active shared links."""
    conn = get_db_connection()
    try:
        shares = conn.execute("SELECT * FROM shared_links ORDER BY created_at DESC").fetchall()
    except:
        shares = []
    conn.close()
    
    share_list = []
    for s in shares:
        share_list.append({
            'id': s['id'],
            'name': s.get('title', 'Untitled Share'),
            'views': s.get('view_count', 0),
            'limit': s.get('max_views', '∞'),
            'expires': s.get('expires_at', 'Never'),
            'active': True 
        })
    return jsonify(share_list)

# --- Asset Routes ---

@app.route('/thumbnails/<filename>')
def serve_thumbnail(filename):
    # Tries to find the thumbnail, serves a placeholder if missing
    if os.path.exists(os.path.join(THUMBNAIL_FOLDER, filename)):
        return send_from_directory(THUMBNAIL_FOLDER, filename)
    return "Thumbnail not found", 404

@app.route('/media/<filename>')
def serve_media(filename):
    return send_from_directory(MEDIA_FOLDER, filename)

@app.route('/')
def home():
    return "Family Archive Backend v12 is Running! Open <a href='http://localhost:5173'>http://localhost:5173</a> to view your Vault."

if __name__ == '__main__':
    print("Starting Family Archive Backend on Port 5000...")
    app.run(debug=True, port=5000)