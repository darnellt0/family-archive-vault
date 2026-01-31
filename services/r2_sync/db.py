import sqlite3
from datetime import datetime
from typing import Optional

from .config import R2_SYNC_DB_PATH


def get_sync_db():
    """Get a connection to the sync tracking database."""
    conn = sqlite3.connect(str(R2_SYNC_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_sync_db(conn):
    """Initialize the R2 sync tracking database."""
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS r2_sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_key TEXT UNIQUE NOT NULL,
            object_etag TEXT,
            size_bytes INTEGER,
            contributor_folder TEXT,
            drive_file_id TEXT,
            manifest_id TEXT,
            status TEXT DEFAULT 'pending',
            synced_at TEXT,
            error_message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_r2_sync_status ON r2_sync_log(status);
        CREATE INDEX IF NOT EXISTS idx_r2_sync_key ON r2_sync_log(object_key);
    ''')
    conn.commit()


def is_object_synced(conn, object_key: str) -> bool:
    """Check if an object has already been synced successfully."""
    row = conn.execute(
        "SELECT 1 FROM r2_sync_log WHERE object_key = ? AND status = 'synced'",
        (object_key,)
    ).fetchone()
    return row is not None


def record_sync_start(conn, object_key: str, etag: str, size: int, folder: str):
    """Record that we're starting to sync an object."""
    conn.execute('''
        INSERT OR REPLACE INTO r2_sync_log
        (object_key, object_etag, size_bytes, contributor_folder, status, created_at)
        VALUES (?, ?, ?, ?, 'syncing', ?)
    ''', (object_key, etag, size, folder, datetime.utcnow().isoformat()))
    conn.commit()


def record_sync_complete(conn, object_key: str, drive_file_id: str, manifest_id: str):
    """Record successful sync completion."""
    conn.execute('''
        UPDATE r2_sync_log
        SET drive_file_id = ?, manifest_id = ?, status = 'synced', synced_at = ?
        WHERE object_key = ?
    ''', (drive_file_id, manifest_id, datetime.utcnow().isoformat(), object_key))
    conn.commit()


def record_sync_error(conn, object_key: str, error: str):
    """Record sync failure."""
    conn.execute('''
        UPDATE r2_sync_log SET status = 'error', error_message = ? WHERE object_key = ?
    ''', (error, object_key))
    conn.commit()


def get_failed_syncs(conn, limit: int = 10):
    """Get objects that failed to sync for retry."""
    return conn.execute(
        "SELECT * FROM r2_sync_log WHERE status = 'error' ORDER BY created_at LIMIT ?",
        (limit,)
    ).fetchall()


def get_sync_stats(conn) -> dict:
    """Get sync statistics."""
    row = conn.execute('''
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'synced' THEN 1 ELSE 0 END) as synced,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
            SUM(CASE WHEN status = 'syncing' THEN 1 ELSE 0 END) as in_progress
        FROM r2_sync_log
    ''').fetchone()
    return dict(row) if row else {"total": 0, "synced": 0, "errors": 0, "in_progress": 0}
