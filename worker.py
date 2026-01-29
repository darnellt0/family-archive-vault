"""
Family Archive Vault - Worker Module
Phase 1: Basic upload monitoring and processing
"""

import os
import json
import sqlite3
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

# Configuration
BASE_DIR = Path(r"F:\FamilyArchive")
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

SERVICE_ACCOUNT_FILE = CONFIG_DIR / "service-account.json"
FOLDER_IDS_FILE = CONFIG_DIR / "drive_folders.json"
DATABASE_FILE = DATA_DIR / "archive.db"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "worker.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def get_drive_service():
    """Create authenticated Google Drive service."""
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_FILE),
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=credentials)


def load_folder_ids():
    """Load Drive folder IDs from config."""
    with open(FOLDER_IDS_FILE) as f:
        return json.load(f)


def init_database():
    """Initialize SQLite database with schema."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.executescript("""
        -- Core media table
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drive_id TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            mime_type TEXT,
            size_bytes INTEGER,
            sha256 TEXT,
            status TEXT DEFAULT 'pending',  -- pending, approved, rejected
            folder TEXT DEFAULT 'INBOX',    -- INBOX, ARCHIVE, REJECTED
            uploaded_at TEXT,
            processed_at TEXT,
            approved_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        
        -- EXIF and metadata
        CREATE TABLE IF NOT EXISTS metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            source TEXT DEFAULT 'exif',  -- exif, ai, manual
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (media_id) REFERENCES media(id),
            UNIQUE(media_id, key, source)
        );
        
        -- AI-generated captions
        CREATE TABLE IF NOT EXISTS captions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id INTEGER NOT NULL,
            caption TEXT,
            model TEXT,
            confidence REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (media_id) REFERENCES media(id)
        );
        
        -- Processing log
        CREATE TABLE IF NOT EXISTS process_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (media_id) REFERENCES media(id)
        );
        
        -- Create indexes
        CREATE INDEX IF NOT EXISTS idx_media_status ON media(status);
        CREATE INDEX IF NOT EXISTS idx_media_folder ON media(folder);
        CREATE INDEX IF NOT EXISTS idx_media_drive_id ON media(drive_id);
    """)
    
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DATABASE_FILE}")


def compute_sha256(file_bytes):
    """Compute SHA256 hash of file content."""
    return hashlib.sha256(file_bytes).hexdigest()


def scan_inbox(service, folder_ids):
    """Scan INBOX folder for new files."""
    inbox_id = folder_ids["INBOX"]
    
    results = service.files().list(
        q=f"'{inbox_id}' in parents and trashed=false",
        fields="files(id, name, mimeType, size, createdTime)",
        orderBy="createdTime"
    ).execute()
    
    return results.get("files", [])


def is_media_file(mime_type):
    """Check if file is a supported media type."""
    supported = [
        "image/jpeg", "image/png", "image/gif", "image/webp", "image/heic",
        "image/tiff", "image/bmp", "image/raw",
        "video/mp4", "video/quicktime", "video/x-msvideo", "video/x-matroska",
        "video/webm", "video/3gpp"
    ]
    return mime_type in supported if mime_type else False


def file_exists_in_db(drive_id):
    """Check if file already exists in database."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM media WHERE drive_id = ?", (drive_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def add_media_to_db(file_info, sha256=None):
    """Add new media file to database."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO media (drive_id, filename, original_filename, mime_type, size_bytes, sha256, uploaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        file_info["id"],
        file_info["name"],
        file_info["name"],
        file_info.get("mimeType"),
        file_info.get("size"),
        sha256,
        file_info.get("createdTime")
    ))
    
    media_id = cursor.lastrowid
    
    # Log the action
    cursor.execute("""
        INSERT INTO process_log (media_id, action, details)
        VALUES (?, 'imported', ?)
    """, (media_id, f"Imported from INBOX: {file_info['name']}"))
    
    conn.commit()
    conn.close()
    
    return media_id


def process_inbox():
    """Main function to process INBOX files."""
    logger.info("Starting INBOX scan...")
    
    service = get_drive_service()
    folder_ids = load_folder_ids()
    
    files = scan_inbox(service, folder_ids)
    logger.info(f"Found {len(files)} files in INBOX")
    
    new_count = 0
    skip_count = 0
    
    for file_info in files:
        drive_id = file_info["id"]
        filename = file_info["name"]
        mime_type = file_info.get("mimeType", "")
        
        # Skip if already in database
        if file_exists_in_db(drive_id):
            skip_count += 1
            continue
        
        # Skip non-media files
        if not is_media_file(mime_type):
            logger.warning(f"Skipping non-media file: {filename} ({mime_type})")
            continue
        
        # Add to database
        media_id = add_media_to_db(file_info)
        logger.info(f"Added: {filename} (ID: {media_id})")
        new_count += 1
    
    logger.info(f"Scan complete. New: {new_count}, Skipped: {skip_count}")
    return new_count


def get_pending_count():
    """Get count of pending media items."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM media WHERE status = 'pending'")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_stats():
    """Get archive statistics."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    stats = {}
    
    cursor.execute("SELECT COUNT(*) FROM media")
    stats["total"] = cursor.fetchone()[0]
    
    cursor.execute("SELECT status, COUNT(*) FROM media GROUP BY status")
    for row in cursor.fetchall():
        stats[row[0]] = row[1]
    
    cursor.execute("SELECT SUM(size_bytes) FROM media")
    total_bytes = cursor.fetchone()[0] or 0
    stats["total_size_mb"] = round(total_bytes / (1024 * 1024), 2)
    
    conn.close()
    return stats


if __name__ == "__main__":
    # Initialize database
    init_database()
    
    # Process inbox
    process_inbox()
    
    # Show stats
    stats = get_stats()
    print(f"\nArchive Stats: {json.dumps(stats, indent=2)}")
