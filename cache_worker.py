import os
import sqlite3
import requests
from PIL import Image
from io import BytesIO

# Configuration
DB_PATH = r'F:\FamilyArchive\data\archive.db'
CACHE_DIR = r'F:\FamilyArchive\static\cache\thumbnails'
THUMBNAIL_SIZE = (300, 300)

def setup_cache():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
        print(f"Created cache directory: {CACHE_DIR}")

def get_pending_media():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # We'll add a 'thumbnail_path' column if it doesn't exist
    try:
        cursor.execute("ALTER TABLE media ADD COLUMN thumbnail_path TEXT")
    except sqlite3.OperationalError:
        pass # Column already exists
        
    cursor.execute("SELECT drive_id, filename FROM media WHERE thumbnail_path IS NULL AND status = 'approved'")
    rows = cursor.fetchall()
    conn.close()
    return rows

def download_and_cache(drive_id, filename):
    """
    Simulates downloading from Drive and saving a local thumbnail.
    In a real scenario, you'd use your existing Drive service to get the content.
    """
    # This is a placeholder for the actual Drive download logic
    # For the worker, we assume the file is accessible or we fetch it
    target_path = os.path.join(CACHE_DIR, f"{drive_id}.jpg")
    
    # Mocking the download/resize process
    # In production, you would use: 
    # content = drive_service.files().get_media(fileId=drive_id).execute()
    # img = Image.open(BytesIO(content))
    # img.thumbnail(THUMBNAIL_SIZE)
    # img.save(target_path, "JPEG")
    
    return f"static/cache/thumbnails/{drive_id}.jpg"

def update_thumbnail_path(drive_id, path):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE media SET thumbnail_path = ? WHERE drive_id = ?", (path, drive_id))
    conn.commit()
    conn.close()

def run_cache_worker():
    print("Starting Thumbnail Cache Worker...")
    setup_cache()
    pending = get_pending_media()
    print(f"Found {len(pending)} items to cache.")
    
    for drive_id, filename in pending:
        try:
            print(f"Caching thumbnail for: {filename}")
            # In a real implementation, this would call the Drive API
            # For now, we're setting up the logic
            path = download_and_cache(drive_id, filename)
            update_thumbnail_path(drive_id, path)
        except Exception as e:
            print(f"Error caching {filename}: {e}")

if __name__ == "__main__":
    run_cache_worker()
