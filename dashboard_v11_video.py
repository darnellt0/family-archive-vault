"""
Family Archive Vault v11 - Video Player Integration
Now extended with the core v8 dashboard, sharing, and duplicates routes.
"""

from datetime import datetime, timedelta
import hashlib
import io
import json
import math
import os
import secrets
import sqlite3
from pathlib import Path

from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
    session,
)

try:
    from flask_cors import CORS
except Exception:
    CORS = None
from services.api_ops import register_ops_routes

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
DB_PATH = r"F:\FamilyArchive\data\archive.db"
SERVICE_ACCOUNT_FILE = r"F:\FamilyArchive\config\service-account.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
ITEMS_PER_PAGE = 12

app = Flask(__name__, template_folder=TEMPLATE_DIR)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "family-archive-v11")


if CORS is not None:
    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": [
                    "http://localhost:5173",
                    "http://127.0.0.1:5173",
                ]
            }
        },
        supports_credentials=True,
    )


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


register_ops_routes(app, Path(DB_PATH))


def table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_table_columns(conn, table_name):
    if not table_exists(conn, table_name):
        return set()
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {r["name"] for r in rows}


def column_exists(conn, table_name, column_name):
    return column_name in get_table_columns(conn, table_name)


def ensure_uploaded_dates(conn):
    # Backfill uploaded_date so templates slicing [:10] does not crash.
    conn.execute(
        """
        UPDATE media
        SET uploaded_date = COALESCE(
            uploaded_date,
            substr(uploaded_at, 1, 10),
            substr(created_at, 1, 10)
        )
        WHERE uploaded_date IS NULL
        """
    )
    conn.commit()


def paginate_items(items, page=1):
    total_items = len(items)
    if total_items == 0:
        return {
            "items": [],
            "current_page": 1,
            "total_pages": 1,
            "total_items": 0,
            "has_prev": False,
            "has_next": False,
        }
    total_pages = math.ceil(total_items / ITEMS_PER_PAGE)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    return {
        "items": items[start_idx:end_idx],
        "current_page": page,
        "total_pages": total_pages,
        "total_items": total_items,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }


def get_gallery_items(status, search_query, sort_by):
    conn = get_db_connection()
    ensure_uploaded_dates(conn)

    query = "SELECT * FROM media WHERE status = ?"
    params = [status]

    if search_query:
        query += " AND (filename LIKE ? OR ai_caption LIKE ?)"
        like = f"%{search_query}%"
        params.extend([like, like])

    if sort_by == "oldest":
        query += " ORDER BY uploaded_date ASC"
    elif sort_by == "date_taken_newest":
        query += " ORDER BY COALESCE(date_taken, uploaded_date) DESC"
    elif sort_by == "date_taken_oldest":
        query += " ORDER BY COALESCE(date_taken, uploaded_date) ASC"
    elif sort_by == "filename_asc":
        query += " ORDER BY filename ASC"
    elif sort_by == "filename_desc":
        query += " ORDER BY filename DESC"
    else:
        query += " ORDER BY uploaded_date DESC"

    items = conn.execute(query, params).fetchall()
    conn.close()
    return items


def get_drive_service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except Exception:
        return None

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def drive_get_media_stream(drive_id):
    service = get_drive_service()
    if not service:
        return None

    try:
        from googleapiclient.http import MediaIoBaseDownload
    except Exception:
        return None

    request_obj = service.files().get_media(fileId=drive_id)
    file_stream = io.BytesIO()
    downloader = MediaIoBaseDownload(file_stream, request_obj)
    done = False
    while done is False:
        _, done = downloader.next_chunk()
    file_stream.seek(0)
    return file_stream


def ensure_share_links_schema(conn):
    if not table_exists(conn, "share_links"):
        return

    cols = get_table_columns(conn, "share_links")
    alters = []
    if "password_hash" not in cols:
        alters.append("ALTER TABLE share_links ADD COLUMN password_hash TEXT")
    if "password_salt" not in cols:
        alters.append("ALTER TABLE share_links ADD COLUMN password_salt TEXT")
    if "max_views" not in cols:
        alters.append("ALTER TABLE share_links ADD COLUMN max_views INTEGER")
    if "allow_download" not in cols:
        alters.append(
            "ALTER TABLE share_links ADD COLUMN allow_download BOOLEAN DEFAULT 0"
        )

    for stmt in alters:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass
    if alters:
        conn.commit()


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    ).hex()
    return digest, salt


def create_share_link(data):
    conn = get_db_connection()
    ensure_share_links_schema(conn)
    cols = get_table_columns(conn, "share_links")

    token = secrets.token_urlsafe(32)
    name = data.get("name") or "Unnamed Share"
    expires_days = data.get("expires_days", 30)
    created_date = datetime.now().isoformat()
    expires_date = None
    if expires_days:
        expires_date = (datetime.now() + timedelta(days=int(expires_days))).isoformat()

    password = data.get("password") or None
    allow_download = 1 if data.get("allow_download") else 0
    max_views = data.get("max_views")
    max_views = int(max_views) if max_views else None

    password_hash = None
    password_salt = None
    if password:
        password_hash, password_salt = hash_password(password)

    values = {
        "token": token,
        "name": name,
        "created_date": created_date,
        "expires_date": expires_date,
        "access_type": "view",
        "is_active": 1,
        "view_count": 0,
        "password_hash": password_hash,
        "password_salt": password_salt,
        "max_views": max_views,
        "allow_download": allow_download,
    }

    insert_cols = [c for c in values.keys() if c in cols]
    placeholders = ", ".join(["?" for _ in insert_cols])
    sql = f"INSERT INTO share_links ({', '.join(insert_cols)}) VALUES ({placeholders})"
    conn.execute(sql, [values[c] for c in insert_cols])
    conn.commit()
    conn.close()
    return token


def get_all_share_links():
    conn = get_db_connection()
    ensure_share_links_schema(conn)
    links = conn.execute(
        """
        SELECT * FROM share_links
        WHERE is_active = 1
        ORDER BY created_date DESC
        """
    ).fetchall()
    conn.close()

    result = []
    for link in links:
        d = dict(link)
        d.setdefault("allow_download", 0)
        d.setdefault("max_views", None)
        d.setdefault("password_hash", None)
        d.setdefault("password_salt", None)
        result.append(d)
    return result


def revoke_share_link(token):
    conn = get_db_connection()
    conn.execute("UPDATE share_links SET is_active = 0 WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def verify_share_link(token, password=None):
    conn = get_db_connection()
    ensure_share_links_schema(conn)

    link = conn.execute(
        "SELECT * FROM share_links WHERE token = ? AND is_active = 1", (token,)
    ).fetchone()
    if not link:
        conn.close()
        return None

    link_dict = dict(link)

    expires_date = link_dict.get("expires_date")
    if expires_date:
        try:
            if datetime.now() > datetime.fromisoformat(expires_date):
                conn.close()
                return None
        except ValueError:
            pass

    max_views = link_dict.get("max_views")
    view_count = link_dict.get("view_count") or 0
    if max_views and view_count >= max_views:
        conn.execute("UPDATE share_links SET is_active = 0 WHERE token = ?", (token,))
        conn.commit()
        conn.close()
        return None

    needs_password = bool(link_dict.get("password_hash"))
    verified_tokens = set(session.get("verified_share_tokens", []))

    if needs_password and token not in verified_tokens:
        if not password:
            conn.close()
            return {"requires_password": True, "link": link_dict}
        salt = link_dict.get("password_salt") or ""
        expected = link_dict.get("password_hash")
        actual, _ = hash_password(password, salt=salt)
        if not secrets.compare_digest(actual, expected):
            conn.close()
            return {"requires_password": True, "link": link_dict}
        verified_tokens.add(token)
        session["verified_share_tokens"] = list(verified_tokens)

    conn.execute(
        "UPDATE share_links SET view_count = COALESCE(view_count, 0) + 1 WHERE token = ?",
        (token,),
    )
    conn.commit()
    conn.close()
    link_dict["requires_password"] = False
    return link_dict


def transcript_table_exists(conn):
    return table_exists(conn, "transcripts")


def get_video_info(drive_id):
    conn = get_db_connection()
    ensure_uploaded_dates(conn)

    video = conn.execute(
        """
        SELECT drive_id, filename, status, uploaded_date, ai_caption
        FROM media
        WHERE drive_id = ? AND status = 'approved'
        """,
        (drive_id,),
    ).fetchone()
    if not video:
        conn.close()
        return None

    transcript = None
    if transcript_table_exists(conn):
        transcript_row = conn.execute(
            """
            SELECT full_text, segments_json
            FROM transcripts
            WHERE media_id = ?
            """,
            (drive_id,),
        ).fetchone()
        if transcript_row:
            try:
                transcript = {
                    "full_text": transcript_row[0],
                    "segments": json.loads(transcript_row[1]),
                }
            except json.JSONDecodeError:
                transcript = None

    conn.close()
    return {
        "drive_id": video[0],
        "filename": video[1],
        "status": video[2],
        "uploaded_date": video[3],
        "ai_caption": video[4],
        "transcript": transcript,
    }


@app.route("/")
def dashboard():
    conn = get_db_connection()
    ensure_uploaded_dates(conn)
    stats = conn.execute(
        """
        SELECT
            COUNT(*) as total,
            SUM(case when status = 'pending' then 1 else 0 end) as pending,
            SUM(case when status = 'approved' then 1 else 0 end) as approved,
            SUM(case when status = 'rejected' then 1 else 0 end) as rejected
        FROM media
        """
    ).fetchone()
    recent_items = conn.execute(
        "SELECT * FROM media ORDER BY uploaded_date DESC LIMIT 6"
    ).fetchall()
    conn.close()
    return render_template("dashboard_tailwind.html", stats=stats, recent_items=recent_items)



def _format_number(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _parse_datetime(value):
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None


def _time_ago(value):
    dt = _parse_datetime(value)
    if not dt:
        return "Unknown"

    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    delta = now - dt
    days = max(delta.days, 0)

    if days == 0:
        return "today"
    if days == 1:
        return "1 day ago"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        weeks = max(days // 7, 1)
        return "1 week ago" if weeks == 1 else f"{weeks} weeks ago"
    if days < 365:
        months = max(days // 30, 1)
        return "1 month ago" if months == 1 else f"{months} months ago"
    years = max(days // 365, 1)
    return "1 year ago" if years == 1 else f"{years} years ago"


def _seconds_to_mmss(seconds):
    try:
        total = max(int(float(seconds)), 0)
    except (TypeError, ValueError):
        total = 0
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


def _is_video(row):
    mime_type = (row["mime_type"] or "").lower() if "mime_type" in row.keys() else ""
    filename = (row["filename"] or "").lower() if "filename" in row.keys() else ""
    if mime_type.startswith("video/"):
        return True
    video_exts = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")
    return filename.endswith(video_exts)


def _video_filter_sql():
    return (
        "(mime_type LIKE 'video/%' "
        "OR lower(filename) LIKE '%.mp4' "
        "OR lower(filename) LIKE '%.mov' "
        "OR lower(filename) LIKE '%.avi' "
        "OR lower(filename) LIKE '%.mkv' "
        "OR lower(filename) LIKE '%.webm' "
        "OR lower(filename) LIKE '%.m4v')"
    )


def _get_faces_indexed(conn):
    if not table_exists(conn, "faces"):
        return 0
    row = conn.execute("SELECT COUNT(*) AS count FROM faces").fetchone()
    return row["count"] if row and "count" in row.keys() else 0


def _get_video_hours_seconds(conn):
    if not table_exists(conn, "metadata"):
        return 0.0

    duration_keys = (
        "duration_seconds",
        "video_duration_seconds",
        "duration",
        "duration_sec",
    )
    placeholders = ",".join(["?" for _ in duration_keys])
    video_filter = _video_filter_sql()

    sql = f"""
        SELECT md.value
        FROM metadata md
        JOIN media m ON m.id = md.media_id
        WHERE md.key IN ({placeholders})
          AND {video_filter}
    """

    total_seconds = 0.0
    for row in conn.execute(sql, duration_keys).fetchall():
        try:
            total_seconds += float(row["value"])
        except (TypeError, ValueError, KeyError):
            continue
    return total_seconds


def _format_hours(total_seconds):
    hours = max(total_seconds / 3600.0, 0.0)
    rounded = round(hours, 1)
    if abs(rounded - int(rounded)) < 1e-9:
        return f"{int(rounded)} hrs"
    return f"{rounded:.1f} hrs"


@app.route("/api/stats")
def api_stats_react():
    conn = get_db_connection()
    ensure_uploaded_dates(conn)

    total_files = conn.execute("SELECT COUNT(*) AS count FROM media").fetchone()["count"]
    faces_indexed = _get_faces_indexed(conn)
    video_seconds = _get_video_hours_seconds(conn)
    conn.close()

    payload = [
        {
            "label": "Total Memories",
            "value": _format_number(total_files),
            "metric": "total_files",
        },
        {
            "label": "Faces Indexed",
            "value": _format_number(faces_indexed),
            "metric": "faces_indexed",
        },
        {
            "label": "Searchable Video",
            "value": _format_hours(video_seconds),
            "metric": "video_hours",
        },
    ]
    return jsonify(payload)


@app.route("/api/recent")
def api_recent_react():
    conn = get_db_connection()
    ensure_uploaded_dates(conn)

    rows = conn.execute(
        """
        SELECT drive_id, filename, original_filename, mime_type, status,
               uploaded_date, date_taken, created_at, ai_caption
        FROM media
        ORDER BY COALESCE(uploaded_date, substr(created_at, 1, 10)) DESC
        LIMIT 10
        """
    ).fetchall()
    conn.close()

    items = []
    api_base = request.host_url.rstrip("/")
    for row in rows:
        date_source = row["uploaded_date"] or row["date_taken"] or row["created_at"]
        items.append(
            {
                "id": row["drive_id"],
                "type": "video" if _is_video(row) else "photo",
                "title": row["original_filename"] or row["filename"],
                "date": _time_ago(date_source),
                "thumbnail": f"{api_base}/thumbnail/{row['drive_id']}",
                "drive_id": row["drive_id"],
                "mime_type": row["mime_type"],
                "status": row["status"],
                "uploaded_date": (row["uploaded_date"] or "")[:10],
                "date_taken": row["date_taken"],
                "ai_caption": row["ai_caption"],
            }
        )

    return jsonify(items)


def _get_transcript_columns(conn):
    cols = get_table_columns(conn, "transcripts")
    id_col = "media_id" if "media_id" in cols else ("drive_id" if "drive_id" in cols else None)
    seg_col = "segments_json" if "segments_json" in cols else None
    text_col = "full_text" if "full_text" in cols else ("transcript" if "transcript" in cols else None)
    return id_col, seg_col, text_col


@app.route("/api/transcript/<video_id>")
def api_transcript(video_id):
    conn = get_db_connection()
    if not transcript_table_exists(conn):
        conn.close()
        return jsonify([])

    id_col, seg_col, text_col = _get_transcript_columns(conn)
    if not id_col:
        conn.close()
        return jsonify([])

    select_cols = [c for c in (seg_col, text_col) if c]
    sql = f"SELECT {', '.join(select_cols)} FROM transcripts WHERE {id_col} = ? LIMIT 1"
    row = conn.execute(sql, (video_id,)).fetchone()
    conn.close()

    if not row:
        return jsonify([])

    segments = []
    if seg_col:
        try:
            raw_segments = json.loads(row[0]) if row[0] else []
        except (json.JSONDecodeError, TypeError):
            raw_segments = []

        for seg in raw_segments:
            start = seg.get("start") or seg.get("start_time") or 0
            segments.append({"time": _seconds_to_mmss(start), "text": seg.get("text") or ""})

    if not segments and text_col:
        text_value = row[-1] if select_cols else None
        if text_value:
            segments = [{"time": "00:00", "text": str(text_value)}]

    return jsonify(segments)


def _format_expiry(expires_date):
    if not expires_date:
        return "Never", True
    dt = _parse_datetime(expires_date)
    if not dt:
        return str(expires_date)[:10], True
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    is_active = now <= dt
    return ("Expired" if not is_active else dt.date().isoformat()), is_active


@app.route("/api/shares")
def api_shares_react():
    conn = get_db_connection()
    if not table_exists(conn, "share_links"):
        conn.close()
        return jsonify([])

    ensure_share_links_schema(conn)
    rows = conn.execute(
        """
        SELECT * FROM share_links
        WHERE is_active = 1
        ORDER BY created_date DESC
        """
    ).fetchall()
    conn.close()

    shares = []
    for row in rows:
        link = dict(row)
        expires_label, not_expired = _format_expiry(link.get("expires_date"))
        view_count = int(link.get("view_count") or 0)
        max_views = link.get("max_views")
        limit = int(max_views) if max_views else 0
        within_limit = (view_count < limit) if limit else True
        active = bool(link.get("is_active", 1)) and not_expired and within_limit

        shares.append(
            {
                "id": link.get("id") or link.get("token"),
                "name": link.get("name") or "Unnamed Share",
                "views": view_count,
                "limit": limit,
                "expires": expires_label,
                "active": active,
                "token": link.get("token"),
                "created_date": link.get("created_date"),
            }
        )

    return jsonify(shares)


@app.route("/pending")
def pending_review():
    search_query = request.args.get("search", "")
    page = request.args.get("page", 1, type=int)
    sort_by = request.args.get("sort", "newest")
    search_mode = request.args.get("mode", "keyword")

    items = []
    if search_mode == "semantic" and search_query:
        try:
            from semantic_search import semantic_search
        except Exception:
            semantic_search = None
        if semantic_search:
            results = semantic_search(search_query, top_k=100)
            drive_ids = [r[0] for r in results]
            if drive_ids:
                conn = get_db_connection()
                placeholders = ",".join(["?" for _ in drive_ids])
                sql = (
                    "SELECT * FROM media WHERE status = 'pending' AND drive_id IN ("
                    + placeholders
                    + ")"
                )
                items = conn.execute(sql, drive_ids).fetchall()
                conn.close()
    if not items:
        items = get_gallery_items("pending", search_query, sort_by)

    paginated = paginate_items(items, page)
    return render_template(
        "gallery_tailwind.html",
        title="Pending Review",
        items=paginated["items"],
        status_filter="pending",
        search_query=search_query,
        sort_by=sort_by,
        pagination=paginated,
        search_mode=search_mode,
    )


@app.route("/approved")
def approved_items():
    search_query = request.args.get("search", "")
    page = request.args.get("page", 1, type=int)
    sort_by = request.args.get("sort", "newest")
    search_mode = request.args.get("mode", "keyword")

    items = []
    if search_mode == "semantic" and search_query:
        try:
            from semantic_search import semantic_search
        except Exception:
            semantic_search = None
        if semantic_search:
            results = semantic_search(search_query, top_k=100)
            drive_ids = [r[0] for r in results]
            if drive_ids:
                conn = get_db_connection()
                placeholders = ",".join(["?" for _ in drive_ids])
                sql = (
                    "SELECT * FROM media WHERE status = 'approved' AND drive_id IN ("
                    + placeholders
                    + ")"
                )
                items = conn.execute(sql, drive_ids).fetchall()
                conn.close()
    if not items:
        items = get_gallery_items("approved", search_query, sort_by)

    paginated = paginate_items(items, page)
    return render_template(
        "gallery_tailwind.html",
        title="Approved Archive",
        items=paginated["items"],
        status_filter="approved",
        search_query=search_query,
        sort_by=sort_by,
        pagination=paginated,
        search_mode=search_mode,
    )


@app.route("/duplicates")
def duplicates_view():
    try:
        from duplicate_detection import get_duplicate_groups
    except Exception:
        get_duplicate_groups = None

    duplicate_groups = []
    if get_duplicate_groups:
        try:
            duplicate_groups = get_duplicate_groups()
        except Exception:
            duplicate_groups = []
    return render_template("duplicates.html", duplicate_groups=duplicate_groups)


@app.route("/people")
def people_view():
    conn = get_db_connection()
    if not (table_exists(conn, "clusters") and table_exists(conn, "faces")):
        conn.close()
        return render_template("people.html", people=[])

    people = conn.execute(
        """
        SELECT c.id, c.name, f.drive_id as rep_drive_id, COUNT(f2.id) as face_count
        FROM clusters c
        JOIN faces f ON c.representative_face_id = f.id
        JOIN faces f2 ON c.id = f2.cluster_id
        GROUP BY c.id
        """
    ).fetchall()
    conn.close()
    return render_template("people.html", people=people)


@app.route("/person/<int:cluster_id>")
def person_gallery(cluster_id):
    page = request.args.get("page", 1, type=int)
    conn = get_db_connection()
    if not (table_exists(conn, "clusters") and table_exists(conn, "faces")):
        conn.close()
        return render_template(
            "gallery_tailwind.html",
            title="Person",
            items=[],
            status_filter="person",
            pagination=paginate_items([], page),
            search_query="",
            sort_by="newest",
        )

    person = conn.execute(
        "SELECT name FROM clusters WHERE id = ?", (cluster_id,)
    ).fetchone()
    items = conn.execute(
        """
        SELECT DISTINCT m.*
        FROM media m
        JOIN faces f ON m.drive_id = f.drive_id
        WHERE f.cluster_id = ?
        ORDER BY m.uploaded_date DESC
        """,
        (cluster_id,),
    ).fetchall()
    conn.close()
    paginated = paginate_items(items, page)
    person_name = person["name"] if person else "Unknown"
    return render_template(
        "gallery_tailwind.html",
        title=f"Photos of {person_name}",
        items=paginated["items"],
        status_filter="person",
        pagination=paginated,
        search_query="",
        sort_by="newest",
    )


@app.route("/sharing")
def sharing_view():
    return render_template("sharing_advanced.html")


@app.route("/api/create-share-link", methods=["POST"])
def api_create_share_link():
    data = request.json or {}
    try:
        token = create_share_link(data)
        return jsonify({"token": token, "url": f"/share/{token}"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/share-links")
def api_share_links():
    try:
        return jsonify(get_all_share_links())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/revoke-share-link/<token>", methods=["POST"])
def api_revoke_share_link(token):
    try:
        revoke_share_link(token)
        return jsonify({"status": "success"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/share/<token>/verify", methods=["POST"])
def share_verify(token):
    data = request.json or {}
    password = data.get("password")
    result = verify_share_link(token, password=password)
    if not result or result.get("requires_password"):
        return jsonify({"status": "denied"}), 401
    return jsonify({"status": "ok"})


@app.route("/share/<token>")
def shared_view(token):
    result = verify_share_link(token)
    if not result:
        abort(404)

    if result.get("requires_password"):
        return render_template(
            "shared_view.html",
            requires_password=True,
            token=token,
        )

    conn = get_db_connection()
    ensure_uploaded_dates(conn)
    items = conn.execute(
        "SELECT * FROM media WHERE status = 'approved' ORDER BY uploaded_date DESC"
    ).fetchall()
    conn.close()

    allow_download = bool(result.get("allow_download"))
    media = []
    for item in items:
        uploaded_date = item["uploaded_date"] or ""
        media.append(
            {
                "drive_id": item["drive_id"],
                "filename": item["filename"],
                "uploaded_date": uploaded_date[:10],
                "ai_caption": item["ai_caption"],
                "thumbnail_url": f"/thumbnail/{item['drive_id']}",
                "download_url": f"/download/{item['drive_id']}",
            }
        )

    expires_date = result.get("expires_date") or "No expiration"
    max_views = result.get("max_views")
    view_count = result.get("view_count") or 0

    return render_template(
        "shared_view.html",
        requires_password=False,
        token=token,
        share_name=result.get("name", "Shared Archive"),
        media=media,
        allow_download=allow_download,
        expires_date=expires_date,
        max_views=max_views,
        view_count=view_count,
    )


@app.route("/api/bulk_action", methods=["POST"])
def bulk_action():
    data = request.json or {}
    drive_ids = data.get("drive_ids", [])
    action = data.get("action")
    status = "approved" if action == "approve" else "rejected"
    reviewed_date = datetime.now().isoformat()

    conn = get_db_connection()
    has_reviewed_date = column_exists(conn, "media", "reviewed_date")
    if has_reviewed_date:
        conn.executemany(
            "UPDATE media SET status = ?, reviewed_date = ? WHERE drive_id = ?",
            [(status, reviewed_date, d_id) for d_id in drive_ids],
        )
    else:
        conn.executemany(
            "UPDATE media SET status = ? WHERE drive_id = ?",
            [(status, d_id) for d_id in drive_ids],
        )
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "count": len(drive_ids)})


@app.route("/thumbnail/<drive_id>")
def get_thumbnail(drive_id):
    file_stream = drive_get_media_stream(drive_id)
    if not file_stream:
        abort(404)
    return send_file(file_stream, mimetype="image/jpeg")


@app.route("/download/<drive_id>")
def download_media(drive_id):
    file_stream = drive_get_media_stream(drive_id)
    if not file_stream:
        abort(404)
    return send_file(
        file_stream,
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=f"{drive_id}.bin",
    )


@app.route("/video/<drive_id>")
def video_player(drive_id):
    video_info = get_video_info(drive_id)
    if not video_info:
        return "Video not found", 404

    video_url = f"/api/stream/{drive_id}"
    return render_template(
        "video_player.html",
        filename=video_info["filename"],
        uploaded_date=video_info["uploaded_date"],
        ai_caption=video_info["ai_caption"],
        transcript=video_info["transcript"],
        video_url=video_url,
    )


@app.route("/api/stream/<drive_id>")
def stream_video(drive_id):
    return jsonify({"error": "Video streaming not yet implemented"}), 501


@app.route("/api/search-transcripts", methods=["POST"])
def search_transcripts():
    data = request.json or {}
    query = (data.get("query") or "").lower().strip()
    if not query:
        return jsonify([])

    conn = get_db_connection()
    if not transcript_table_exists(conn):
        conn.close()
        return jsonify([])

    rows = conn.execute(
        """
        SELECT t.media_id, m.filename, t.full_text, t.segments_json
        FROM transcripts t
        JOIN media m ON t.media_id = m.drive_id
        WHERE t.full_text LIKE ? AND m.status = 'approved'
        """,
        (f"%{query}%",),
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        try:
            segments = json.loads(row[3])
        except json.JSONDecodeError:
            continue
        matching_segments = [
            seg for seg in segments if query in (seg.get("text") or "").lower()
        ]
        results.append(
            {
                "drive_id": row[0],
                "filename": row[1],
                "matching_segments": matching_segments[:3],
            }
        )
    return jsonify(results)


@app.route("/transcripts")
def transcripts_search():
    return render_template("transcript_search.html")


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
