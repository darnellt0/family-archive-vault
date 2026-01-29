import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from flask import jsonify

DEFAULT_DB_PATH = Path(os.getenv("FAMILY_ARCHIVE_DB", r"F:\FamilyArchive\data\archive.db"))
SCHEMA_VERSION = "6.1"
WORKER_VERSION = "6.1"


def _get_db_connection(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn, name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _ops_counts(conn):
    if not _table_exists(conn, "assets"):
        return {
            "needs_review": 0,
            "processing": 0,
            "duplicates": 0,
            "transcribe_later": 0,
        }
    rows = conn.execute(
        """
        SELECT status, COUNT(*) as count
        FROM assets
        GROUP BY status
        """
    ).fetchall()
    counts = {r["status"]: r["count"] for r in rows}
    return {
        "needs_review": counts.get("needs_review", 0),
        "processing": counts.get("processing", 0),
        "duplicates": counts.get("possible_duplicates", 0),
        "transcribe_later": counts.get("transcribe_later", 0),
    }


def _ops_state(conn, key):
    if not _table_exists(conn, "ops_state"):
        return None
    row = conn.execute("SELECT value FROM ops_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _error_count_last_24h():
    error_dir = Path(r"F:\FamilyArchive\logs\errors")
    if not error_dir.exists():
        return 0
    cutoff = datetime.now().timestamp() - 24 * 3600
    count = 0
    for file in error_dir.glob("*.log"):
        if file.stat().st_mtime >= cutoff:
            count += 1
    return count


def _git_commit():
    try:
        head = Path(".git/HEAD")
        if not head.exists():
            return "unknown"
        content = head.read_text().strip()
        if content.startswith("ref:"):
            ref_path = Path(".git") / content.split(" ", 1)[1]
            return ref_path.read_text().strip() if ref_path.exists() else "unknown"
        return content
    except Exception:
        return "unknown"


def register_ops_routes(app, db_path: Path = DEFAULT_DB_PATH):
    if "api_health" not in app.view_functions:
        @app.route("/api/health")
        def api_health():
            return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})

    if "api_ops_stats" not in app.view_functions:
        @app.route("/api/ops/stats")
        def api_ops_stats():
            conn = _get_db_connection(db_path)
            counts = _ops_counts(conn)
            stats = {
                "backlog": counts,
                "last_worker_run": _ops_state(conn, "last_worker_run"),
                "last_rosetta_build": _ops_state(conn, "last_rosetta_build"),
                "errors_last_24h": _error_count_last_24h(),
            }
            conn.close()

            try:
                total, used, free = shutil.disk_usage(str(db_path.parent))
                stats["disk_free_gb"] = round(free / (1024 ** 3), 2)
                stats["disk_total_gb"] = round(total / (1024 ** 3), 2)
                stats["disk_warning"] = stats["disk_free_gb"] < 30
            except Exception:
                stats["disk_free_gb"] = None
                stats["disk_total_gb"] = None
                stats["disk_warning"] = None
            return jsonify(stats)

    if "api_version" not in app.view_functions:
        @app.route("/api/version")
        def api_version():
            return jsonify({
                "git_commit": _git_commit(),
                "build_time": os.getenv("BUILD_TIME", datetime.utcnow().isoformat()),
                "schema_version": SCHEMA_VERSION,
                "worker_version": WORKER_VERSION,
            })
