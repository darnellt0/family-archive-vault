import json
import os
import re
import secrets
import smtplib
import sqlite3
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.auth.transport.requests import AuthorizedSession
import io
import uuid

app = FastAPI()

BASE_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

TOKEN_MAP_PATH = Path(os.getenv("INTAKE_TOKEN_MAP_PATH", str(BASE_DIR / "token_map.json")))
DRIVE_ROOT_FOLDER_ID = os.getenv("DRIVE_ROOT_FOLDER_ID")
SERVICE_ACCOUNT_JSON_PATH = os.getenv("SERVICE_ACCOUNT_JSON_PATH")
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")

MAX_FILE_SIZE_BYTES = int(os.getenv("MAX_FILE_SIZE_BYTES", str(25 * 1024 * 1024 * 1024)))
MAX_FILES_PER_BATCH = int(os.getenv("MAX_FILES_PER_BATCH", "100"))
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "120"))
SESSION_STORE_PATH = Path(os.getenv("UPLOAD_SESSION_STORE", str(BASE_DIR / "upload_sessions.json")))

# Self-registration configuration
FAMILY_CODE = os.getenv("FAMILY_CODE", "")  # Required for registration
CONTRIBUTORS_DB_PATH = Path(os.getenv("CONTRIBUTORS_DB_PATH", str(BASE_DIR / "contributors.db")))
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "Family Archive <noreply@familyarchive.local>")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8080")  # For verification links

_RATE_LIMIT = {}
_SESSIONS = {}


# --- Database Setup for Self-Registration ---

def get_contributors_db():
    """Get a connection to the contributors database."""
    conn = sqlite3.connect(str(CONTRIBUTORS_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_contributors_db():
    """Initialize the contributors database schema."""
    conn = get_contributors_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS contributors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            folder_name TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            verification_token TEXT,
            verification_expiry TEXT,
            created_at TEXT,
            verified_at TEXT
        )
    ''')
    conn.commit()
    conn.close()


# Initialize DB on startup
init_contributors_db()


def get_contributor_by_token(token: str) -> Optional[Dict[str, Any]]:
    """Look up contributor by upload token - checks DB first, then JSON fallback."""
    # First check database
    conn = get_contributors_db()
    row = conn.execute(
        "SELECT * FROM contributors WHERE token = ? AND status = 'active'",
        (token,)
    ).fetchone()
    conn.close()

    if row:
        return {
            "display_name": row["display_name"],
            "folder_name": row["folder_name"],
            "email": row["email"],
        }

    # Fallback to JSON token map for backwards compatibility
    token_map = load_token_map()
    return token_map.get(token)


def get_contributor_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Look up contributor by email."""
    conn = get_contributors_db()
    row = conn.execute(
        "SELECT * FROM contributors WHERE email = ?",
        (email.lower(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_contributor(email: str, display_name: str) -> str:
    """Create a new contributor and return their upload token."""
    token = secrets.token_urlsafe(24)

    # Create a safe folder name from display name
    folder_name = re.sub(r'[^a-zA-Z0-9_]', '_', display_name) + "_UPLOADS"

    conn = get_contributors_db()
    conn.execute('''
        INSERT INTO contributors (token, email, display_name, folder_name, status, created_at, verified_at)
        VALUES (?, ?, ?, ?, 'active', ?, ?)
    ''', (token, email.lower(), display_name, folder_name,
          datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

    return token


def verify_contributor(verification_token: str) -> Optional[Dict[str, Any]]:
    """Verify a contributor's email and activate their account."""
    conn = get_contributors_db()
    row = conn.execute(
        "SELECT * FROM contributors WHERE verification_token = ? AND status = 'pending'",
        (verification_token,)
    ).fetchone()

    if not row:
        conn.close()
        return None

    # Check expiry
    expiry = datetime.fromisoformat(row["verification_expiry"])
    if datetime.utcnow() > expiry:
        conn.close()
        return None

    # Activate the account
    conn.execute('''
        UPDATE contributors
        SET status = 'active', verified_at = ?, verification_token = NULL
        WHERE id = ?
    ''', (datetime.utcnow().isoformat(), row["id"]))
    conn.commit()
    conn.close()

    return {
        "token": row["token"],
        "display_name": row["display_name"],
        "email": row["email"],
    }


def send_verification_email(email: str, display_name: str, verification_token: str) -> bool:
    """Send verification email to new contributor."""
    verification_url = f"{BASE_URL}/verify/{verification_token}"

    subject = "Verify your Family Archive account"
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #6366f1;">Welcome to Family Archive, {display_name}!</h2>
        <p>Thank you for joining our family archive. Click the button below to verify your email and start uploading memories.</p>
        <p style="text-align: center; margin: 30px 0;">
            <a href="{verification_url}"
               style="background-color: #6366f1; color: white; padding: 12px 24px;
                      text-decoration: none; border-radius: 6px; display: inline-block;">
                Verify My Email
            </a>
        </p>
        <p style="color: #666; font-size: 14px;">
            Or copy this link: <br>
            <code style="background: #f3f4f6; padding: 4px 8px;">{verification_url}</code>
        </p>
        <p style="color: #999; font-size: 12px;">This link expires in 24 hours.</p>
    </body>
    </html>
    """

    text_body = f"""
    Welcome to Family Archive, {display_name}!

    Click here to verify your email: {verification_url}

    This link expires in 24 hours.
    """

    # If SMTP not configured, just log the verification URL (dev mode)
    if not SMTP_HOST or not SMTP_USER:
        print(f"\n{'='*50}")
        print(f"VERIFICATION EMAIL (SMTP not configured)")
        print(f"To: {email}")
        print(f"Verification URL: {verification_url}")
        print(f"{'='*50}\n")
        return True

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = email

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, email, msg.as_string())

        return True
    except Exception as e:
        print(f"Failed to send verification email: {e}")
        return False


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _RATE_LIMIT.get(ip, [])
    window = [t for t in window if now - t < 60]
    if len(window) >= RATE_LIMIT_PER_MIN:
        return JSONResponse(status_code=429, content={"detail": "Too many requests"})
    window.append(now)
    _RATE_LIMIT[ip] = window
    return await call_next(request)

# Startup validation
if not DRIVE_ROOT_FOLDER_ID:
    raise RuntimeError("DRIVE_ROOT_FOLDER_ID is required")

if not SERVICE_ACCOUNT_JSON and not SERVICE_ACCOUNT_JSON_PATH:
    raise RuntimeError("SERVICE_ACCOUNT_JSON or SERVICE_ACCOUNT_JSON_PATH is required")


def load_token_map() -> Dict[str, Dict[str, str]]:
    if not TOKEN_MAP_PATH.exists():
        return {}
    return json.loads(TOKEN_MAP_PATH.read_text(encoding="utf-8"))


def get_credentials():
    if SERVICE_ACCOUNT_JSON:
        data = json.loads(SERVICE_ACCOUNT_JSON)
        return service_account.Credentials.from_service_account_info(
            data,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
    if SERVICE_ACCOUNT_JSON_PATH:
        return service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_JSON_PATH,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
    raise RuntimeError("SERVICE_ACCOUNT_JSON_PATH or SERVICE_ACCOUNT_JSON required")


def drive_service():
    return build("drive", "v3", credentials=get_credentials())


def load_sessions() -> Dict[str, dict]:
    # Resumable upload sessions are stored locally so we can recover after restarts.
    if SESSION_STORE_PATH.exists():
        try:
            return json.loads(SESSION_STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_sessions():
    # Persist the resumable session map to disk (Cloud Run ephemeral but useful for short restarts).
    SESSION_STORE_PATH.write_text(json.dumps(_SESSIONS, indent=2), encoding="utf-8")


def ensure_folder(service, parent_id: str, name: str) -> str:
    # Escape single quotes in folder name to prevent query injection
    safe_name = name.replace("'", "\\'")
    query = (
        f"name='{safe_name}' and '{parent_id}' in parents and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    result = service.files().list(q=query, fields="files(id, name)").execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]
    folder = service.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
        fields="id",
    ).execute()
    return folder["id"]


def find_folder(service, parent_id: str, name: str) -> Optional[str]:
    """Find an existing folder by name. Returns None if not found.

    Unlike ensure_folder, this does NOT create the folder if missing.
    This is important because service accounts cannot create folders
    (they have no storage quota).

    Uses supportsAllDrives/includeItemsFromAllDrives for Shared Drive support.
    """
    safe_name = name.replace("'", "\\'")
    query = (
        f"name='{safe_name}' and '{parent_id}' in parents and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    result = service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]
    return None


def ensure_schema(service):
    """Find required folders in Drive.

    IMPORTANT: Both INBOX_UPLOADS and _MANIFESTS folders must be created
    manually by a user (not service account) in the Family_Archive folder.
    The service account should have Editor access to both folders.
    Service accounts cannot create folders (no storage quota).
    """
    # Find INBOX_UPLOADS (must exist - created manually by user)
    inbox = find_folder(service, DRIVE_ROOT_FOLDER_ID, "INBOX_UPLOADS")
    if not inbox:
        raise RuntimeError(
            "INBOX_UPLOADS folder not found. Please create it manually in Google Drive "
            "and share it with the service account."
        )

    # Find _MANIFESTS folder (must exist - created manually by user)
    # Put at root level for simplicity
    manifests = find_folder(service, DRIVE_ROOT_FOLDER_ID, "_MANIFESTS")
    if not manifests:
        # If _MANIFESTS doesn't exist, we can skip manifest tracking
        # or raise an error. For now, let's use INBOX_UPLOADS as fallback
        # and prefix manifest files to distinguish them
        print("[WARNING] _MANIFESTS folder not found, using INBOX_UPLOADS for manifests")
        manifests = inbox

    return {"INBOX_UPLOADS": inbox, "MANIFESTS": manifests}


def contributor_folder_id(service, folder_name: str) -> str:
    """Get folder for contributor uploads.

    Note: We upload directly to INBOX_UPLOADS to avoid quota issues.
    Service accounts cannot create folders (no storage quota), so we
    skip creating per-contributor subfolders. Files are prefixed with
    contributor name instead.
    """
    schema = ensure_schema(service)
    # Return INBOX_UPLOADS directly - don't create subfolders
    # This avoids the "Service Accounts do not have storage quota" error
    return schema["INBOX_UPLOADS"]


def authorized_session():
    return AuthorizedSession(get_credentials())


def start_resumable_session(file_name: str, mime_type: str, parent_id: str, size_bytes: int | None) -> str:
    """Start a resumable upload session.

    Uses supportsAllDrives=True to support Shared Drives, which is required
    for service accounts (they have no storage quota in regular Drive).
    """
    session = authorized_session()
    # Add supportsAllDrives=true for Shared Drive support
    url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true"
    headers = {"X-Upload-Content-Type": mime_type}
    if size_bytes:
        headers["X-Upload-Content-Length"] = str(size_bytes)
    body = {"name": file_name, "parents": [parent_id]}
    resp = session.post(url, headers=headers, json=body)
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail=f"Failed to start session: {resp.text}")
    session_url = resp.headers.get("Location")
    if not session_url:
        raise HTTPException(status_code=500, detail="No resumable session URL returned")
    return session_url


def upload_chunk(session_url: str, chunk: bytes, content_range: str, content_type: str):
    session = authorized_session()
    headers = {
        "Content-Type": content_type,
        "Content-Range": content_range,
    }
    try:
        resp = session.put(session_url, headers=headers, data=chunk, timeout=60)
        if resp.status_code >= 400:
            print(f"[UPLOAD ERROR] Status {resp.status_code}: {resp.text[:500]}")
        return resp
    except Exception as e:
        print(f"[UPLOAD EXCEPTION] {type(e).__name__}: {str(e)}")
        raise


def query_upload_status(session_url: str, total_size: int) -> int:
    """Ask Drive how many bytes it has received for this resumable session.

    This is critical for recovery if the client offset and server offset diverge.
    """
    session = authorized_session()
    headers = {"Content-Range": f"bytes */{total_size}"}
    resp = session.put(session_url, headers=headers)
    if resp.status_code == 308:
        range_header = resp.headers.get("Range", "")
        if range_header.startswith("bytes="):
            end = int(range_header.split("-")[-1])
            return end + 1
    return 0


def update_counter(service, token: str, increment: int) -> int:
    schema = ensure_schema(service)
    counter_name = f"counter_{token}.json"

    query = (
        f"name='{counter_name}' and '{schema['MANIFESTS']}' in parents "
        "and trashed=false"
    )
    result = service.files().list(q=query, fields="files(id, name)").execute()
    files = result.get("files", [])
    current = 0
    file_id = None
    if files:
        file_id = files[0]["id"]
        content = service.files().get_media(fileId=file_id).execute()
        try:
            current = json.loads(content.decode("utf-8")).get("count", 0)
        except Exception:
            current = 0

    new_count = current + increment
    data = json.dumps({"count": new_count}).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype="application/json", resumable=False)

    if file_id:
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        service.files().create(
            body={"name": counter_name, "parents": [schema["MANIFESTS"]]},
            media_body=media,
            fields="id",
        ).execute()

    return new_count


# --- Root Redirect ---

@app.get("/")
def root_redirect():
    """Redirect root to registration page."""
    return RedirectResponse(url="/register", status_code=302)


# --- Registration Endpoints ---

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    """Display the self-registration form."""
    if not FAMILY_CODE:
        raise HTTPException(status_code=503, detail="Registration is not enabled")
    return TEMPLATES.TemplateResponse(
        "register.html",
        {"request": request},
    )


@app.post("/api/register")
async def api_register(payload: Dict[str, Any]):
    """Handle self-registration request."""
    if not FAMILY_CODE:
        raise HTTPException(status_code=503, detail="Registration is not enabled")

    email = (payload.get("email") or "").strip().lower()
    display_name = (payload.get("display_name") or "").strip()
    family_code = (payload.get("family_code") or "").strip()

    # Validate inputs
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email is required")
    if not display_name or len(display_name) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters")
    if len(display_name) > 50:
        raise HTTPException(status_code=400, detail="Name must be 50 characters or less")

    # Verify family code (timing-safe comparison to prevent brute-force attacks)
    if not secrets.compare_digest(family_code, FAMILY_CODE):
        raise HTTPException(status_code=403, detail="Invalid family code")

    # Check if email already registered
    existing = get_contributor_by_email(email)
    if existing:
        if existing["status"] == "active":
            # Return their existing upload URL
            upload_url = f"/u/{existing['token']}"
            return {
                "status": "ok",
                "message": "You're already registered!",
                "upload_url": upload_url,
                "token": existing["token"]
            }

    # Create new contributor (immediately active - no email verification)
    token = create_contributor(email, display_name)
    # Use relative URL for redirect (more reliable across deployments)
    upload_url = f"/u/{token}"

    return {
        "status": "ok",
        "message": "Registration successful! You can start uploading now.",
        "upload_url": upload_url,
        "token": token
    }


@app.get("/verify/{verification_token}", response_class=HTMLResponse)
def verify_email(request: Request, verification_token: str):
    """Handle email verification link."""
    result = verify_contributor(verification_token)

    if not result:
        return TEMPLATES.TemplateResponse(
            "verify_result.html",
            {
                "request": request,
                "success": False,
                "message": "Invalid or expired verification link.",
            },
        )

    upload_url = f"{BASE_URL}/u/{result['token']}"
    return TEMPLATES.TemplateResponse(
        "verify_result.html",
        {
            "request": request,
            "success": True,
            "display_name": result["display_name"],
            "upload_url": upload_url,
            "token": result["token"],
        },
    )


@app.get("/u/{token}", response_class=HTMLResponse)
def uploader_page(request: Request, token: str):
    info = get_contributor_by_token(token)
    if not info:
        raise HTTPException(status_code=404, detail="Invalid link")
    return TEMPLATES.TemplateResponse(
        "uploader.html",
        {"request": request, "token": token, "display_name": info["display_name"]},
    )


@app.post("/api/batch/create")
async def api_batch_create(payload: Dict[str, Any]):
    token = payload.get("token")
    info = get_contributor_by_token(token)
    if not info:
        raise HTTPException(status_code=404, detail="Invalid token")

    batch_id = f"batch_{int(time.time())}_{token}"
    return {"batch_id": batch_id, "created_at": datetime.utcnow().isoformat()}


@app.post("/api/upload/init")
async def api_upload_init(payload: Dict[str, Any]):
    token = payload.get("token")
    batch_id = payload.get("batch_id")
    filename = payload.get("filename")
    mime_type = payload.get("mime_type") or "application/octet-stream"
    size_bytes = int(payload.get("size_bytes") or 0)

    print(f"[INIT] Starting upload for {filename} ({size_bytes} bytes)")

    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    info = get_contributor_by_token(token)
    if not info:
        raise HTTPException(status_code=404, detail="Invalid token")

    print(f"[INIT] Contributor: {info['display_name']}, folder: {info['folder_name']}")

    try:
        service = drive_service()
        folder_id = contributor_folder_id(service, info["folder_name"])
        print(f"[INIT] Folder ID: {folder_id}")

        # Prefix filename with contributor name to identify who uploaded it
        # (since we're uploading to shared INBOX_UPLOADS instead of per-user folders)
        prefixed_filename = f"{info['folder_name']}_{filename}"
        session_url = start_resumable_session(prefixed_filename, mime_type, folder_id, size_bytes)
        print(f"[INIT] Session URL: {session_url[:100]}...")
    except Exception as e:
        print(f"[INIT ERROR] {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to initialize upload: {str(e)}")

    upload_id = str(uuid.uuid4())
    _SESSIONS.update(load_sessions())
    _SESSIONS[upload_id] = {
        "session_url": session_url,
        "size_bytes": size_bytes,
        "offset": 0,
        "updated_at": datetime.utcnow().isoformat(),
    }
    save_sessions()

    response = {
        "batch_id": batch_id,
        "upload_id": upload_id,
        "upload_url": session_url,
        "upload_started_at": datetime.utcnow().isoformat(),
    }
    print(f"[INIT] Returning: upload_id={upload_id}, url_present={bool(session_url)}")
    return response


@app.put("/api/upload/chunk")
async def api_upload_chunk(request: Request):
    session_url = request.headers.get("X-Upload-Session-Url")
    upload_id = request.headers.get("X-Upload-Id")
    content_range = request.headers.get("Content-Range")
    content_type = request.headers.get("Content-Type") or "application/octet-stream"

    if not session_url and upload_id:
        _SESSIONS.update(load_sessions())
        session_url = _SESSIONS.get(upload_id, {}).get("session_url")

    if not session_url or not content_range:
        raise HTTPException(status_code=400, detail="Missing upload session or range")

    try:
        range_parts = content_range.split(" ")
        byte_range, total = range_parts[1].split("/")
        start, end = byte_range.split("-")
        start = int(start)
        total = int(total)
    except Exception:
        start = 0
        total = 0

    if total:
        expected = None
        if upload_id and upload_id in _SESSIONS:
            expected = _SESSIONS[upload_id].get("offset", 0)
        if expected is not None and start != expected:
            # Query Drive for the latest offset to recover from mismatch.
            next_offset = query_upload_status(session_url, total)
            _SESSIONS[upload_id]["offset"] = next_offset
            _SESSIONS[upload_id]["updated_at"] = datetime.utcnow().isoformat()
            save_sessions()
            return JSONResponse(content={"status": "resume", "next_offset": next_offset}, status_code=308)
        if expected is None and start > 0:
            next_offset = query_upload_status(session_url, total)
            return JSONResponse(content={"status": "resume", "next_offset": next_offset}, status_code=308)

    body = await request.body()
    print(f"[CHUNK] Uploading {len(body)} bytes, range: {content_range}")

    try:
        resp = upload_chunk(session_url, body, content_range, content_type)
    except Exception as e:
        print(f"[CHUNK ERROR] Exception during upload: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    print(f"[CHUNK] Response status: {resp.status_code}")

    if resp.status_code in (200, 201):
        if upload_id and upload_id in _SESSIONS:
            _SESSIONS.pop(upload_id, None)
            save_sessions()
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    if resp.status_code == 308:
        if upload_id and upload_id in _SESSIONS:
            range_header = resp.headers.get("Range", "")
            next_offset = 0
            if range_header.startswith("bytes="):
                next_offset = int(range_header.split("-")[-1]) + 1
            _SESSIONS[upload_id]["offset"] = next_offset
            _SESSIONS[upload_id]["updated_at"] = datetime.utcnow().isoformat()
            save_sessions()
            return JSONResponse(content={"status": "resume", "next_offset": next_offset}, status_code=308)
        return JSONResponse(content={"status": "resume"}, status_code=308)

    error_detail = resp.text[:500] if resp.text else f"HTTP {resp.status_code}"
    print(f"[CHUNK ERROR] Google Drive returned {resp.status_code}: {error_detail}")
    raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/upload/complete")
async def api_upload_complete(payload: Dict[str, Any]):
    return {"status": "ok", "payload": payload}


@app.post("/api/batch/finish")
async def api_batch_finish(payload: Dict[str, Any]):
    token = payload.get("token")
    batch_id = payload.get("batch_id")
    files = payload.get("files", [])

    info = get_contributor_by_token(token)
    if not info:
        raise HTTPException(status_code=404, detail="Invalid token")

    if len(files) > MAX_FILES_PER_BATCH:
        raise HTTPException(status_code=400, detail="Too many files in batch")

    service = drive_service()
    schema = ensure_schema(service)

    manifest = {
        "batch_id": batch_id,
        "contributor_token": token,
        "contributor_display_name": info["display_name"],
        "created_at": datetime.utcnow().isoformat(),
        "decade": payload.get("decade"),
        "event": payload.get("event"),
        "notes": payload.get("notes"),
        "files": files,
        "voice_note": payload.get("voice_note"),
    }

    manifest_name = f"{batch_id}.json"
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")

    service.files().create(
        body={"name": manifest_name, "parents": [schema["MANIFESTS"]]},
        media_body=manifest_bytes,
        fields="id",
    ).execute()

    total = update_counter(service, token, len(files))

    return {
        "status": "ok",
        "message": f"Thanks! You have preserved {total} memories.",
    }
