import sqlite3
from datetime import datetime
from .config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript('''
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drive_id TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            mime_type TEXT,
            size_bytes INTEGER,
            sha256 TEXT,
            status TEXT DEFAULT 'pending',
            folder TEXT DEFAULT 'INBOX',
            uploaded_at TEXT,
            processed_at TEXT,
            approved_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            uploaded_date TEXT,
            date_taken TEXT,
            camera_make TEXT,
            camera_model TEXT,
            exposure_time TEXT,
            f_number TEXT,
            iso INTEGER,
            focal_length TEXT,
            gps_latitude REAL,
            gps_longitude REAL,
            ai_caption TEXT,
            clip_embedding BLOB,
            phash TEXT
        );

        CREATE TABLE IF NOT EXISTS metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            source TEXT DEFAULT 'exif',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(media_id, key, source)
        );

        CREATE TABLE IF NOT EXISTS assets (
            asset_id TEXT PRIMARY KEY,
            drive_file_id TEXT UNIQUE NOT NULL,
            contributor_token TEXT,
            batch_id TEXT,
            original_filename TEXT,
            mime_type TEXT,
            size_bytes INTEGER,
            status TEXT,
            sha256 TEXT,
            phash TEXT,
            exif_date TEXT,
            gps_lat REAL,
            gps_lon REAL,
            decade TEXT,
            decade_confidence REAL,
            caption TEXT,
            clip_embedding_ref TEXT,
            transcript_ref TEXT,
            duplicate_of TEXT,
            created_at TEXT,
            processed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS batches (
            batch_id TEXT PRIMARY KEY,
            contributor_token TEXT,
            created_at TEXT,
            decade TEXT,
            event TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS contributors (
            token TEXT PRIMARY KEY,
            display_name TEXT
        );

        CREATE TABLE IF NOT EXISTS faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT,
            bbox_json TEXT,
            embedding_ref TEXT,
            confidence REAL,
            cluster_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS clusters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            representative_face_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS duplicates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT,
            duplicate_of TEXT,
            method TEXT
        );

        CREATE TABLE IF NOT EXISTS review_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT,
            action TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS processing_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT,
            step TEXT,
            status TEXT,
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS ops_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        );
    ''')

    conn.commit()
    conn.close()


def set_ops_state(key: str, value: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO ops_state (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_ops_state(key: str):
    conn = get_conn()
    cur = conn.cursor()
    row = cur.execute("SELECT value FROM ops_state WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None
