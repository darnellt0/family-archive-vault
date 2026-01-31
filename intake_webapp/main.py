import json
import os
import re
import secrets
import smtplib
import sqlite3
import time
import hashlib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import boto3
from botocore.config import Config
import uuid

app = FastAPI()

BASE_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Cloudflare R2 Configuration
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "family-archive-uploads")

MAX_FILE_SIZE_BYTES = int(os.getenv("MAX_FILE_SIZE_BYTES", str(25 * 1024 * 1024 * 1024)))
MAX_FILES_PER_BATCH = int(os.getenv("MAX_FILES_PER_BATCH", "100"))
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "120"))

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
_UPLOAD_SESSIONS = {}  # Track multipart uploads
_URL_CACHE = {}  # Cache presigned URLs to avoid rate limiting
_URL_CACHE_TTL = 3000  # Cache URLs for 50 minutes (they expire in 60)


# --- R2 Client Setup ---

def get_r2_client():
    """Get a boto3 S3 client configured for Cloudflare R2."""
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"}
        ),
    )


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
    # Track upload counts locally
    conn.execute('''
        CREATE TABLE IF NOT EXISTS upload_counts (
            token TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()


# Initialize DB on startup
init_contributors_db()


def get_contributor_by_token(token: str) -> Optional[Dict[str, Any]]:
    """Look up contributor by upload token."""
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
    return None


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


def update_upload_count(token: str, increment: int) -> int:
    """Update and return the upload count for a contributor."""
    conn = get_contributors_db()

    # Get current count
    row = conn.execute("SELECT count FROM upload_counts WHERE token = ?", (token,)).fetchone()
    current = row["count"] if row else 0
    new_count = current + increment

    # Upsert the count
    conn.execute('''
        INSERT INTO upload_counts (token, count) VALUES (?, ?)
        ON CONFLICT(token) DO UPDATE SET count = ?
    ''', (token, new_count, new_count))
    conn.commit()
    conn.close()

    return new_count


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
if not R2_ACCOUNT_ID or not R2_ACCESS_KEY_ID or not R2_SECRET_ACCESS_KEY:
    print("[WARNING] R2 credentials not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY")


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

    batch_id = f"batch_{int(time.time())}_{token[:8]}"
    return {"batch_id": batch_id, "created_at": datetime.utcnow().isoformat()}


@app.post("/api/upload/init")
async def api_upload_init(payload: Dict[str, Any]):
    """Initialize an upload - returns a presigned URL for direct upload to R2."""
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
        s3 = get_r2_client()

        # Create object key with contributor prefix and timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
        object_key = f"{info['folder_name']}/{timestamp}_{safe_filename}"

        print(f"[INIT] Object key: {object_key}")

        # For files larger than 5MB, use multipart upload
        if size_bytes > 5 * 1024 * 1024:
            # Start multipart upload
            response = s3.create_multipart_upload(
                Bucket=R2_BUCKET_NAME,
                Key=object_key,
                ContentType=mime_type,
            )
            upload_id = response["UploadId"]

            # Store session info
            session_id = str(uuid.uuid4())
            _UPLOAD_SESSIONS[session_id] = {
                "upload_id": upload_id,
                "object_key": object_key,
                "size_bytes": size_bytes,
                "parts": [],
                "created_at": datetime.utcnow().isoformat(),
            }

            print(f"[INIT] Multipart upload started: {upload_id}")

            return {
                "batch_id": batch_id,
                "upload_id": session_id,
                "upload_type": "multipart",
                "object_key": object_key,
                "upload_started_at": datetime.utcnow().isoformat(),
            }
        else:
            # For smaller files, use server-side upload to avoid CORS issues
            session_id = str(uuid.uuid4())
            _UPLOAD_SESSIONS[session_id] = {
                "object_key": object_key,
                "mime_type": mime_type,
                "size_bytes": size_bytes,
                "created_at": datetime.utcnow().isoformat(),
            }

            print(f"[INIT] Small file upload session created: {session_id}")

            return {
                "batch_id": batch_id,
                "upload_id": session_id,
                "upload_type": "simple",
                "object_key": object_key,
                "upload_started_at": datetime.utcnow().isoformat(),
            }

    except Exception as e:
        print(f"[INIT ERROR] {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to initialize upload: {str(e)}")


@app.post("/api/upload/get-part-url")
async def api_get_part_url(payload: Dict[str, Any]):
    """Get a presigned URL for uploading a part of a multipart upload."""
    session_id = payload.get("upload_id")
    part_number = int(payload.get("part_number", 1))

    if session_id not in _UPLOAD_SESSIONS:
        raise HTTPException(status_code=404, detail="Upload session not found")

    session = _UPLOAD_SESSIONS[session_id]

    try:
        s3 = get_r2_client()

        presigned_url = s3.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": R2_BUCKET_NAME,
                "Key": session["object_key"],
                "UploadId": session["upload_id"],
                "PartNumber": part_number,
            },
            ExpiresIn=3600,
        )

        return {
            "upload_url": presigned_url,
            "part_number": part_number,
        }

    except Exception as e:
        print(f"[PART URL ERROR] {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get part URL: {str(e)}")


@app.post("/api/upload/complete-part")
async def api_complete_part(payload: Dict[str, Any]):
    """Record a completed part of a multipart upload."""
    session_id = payload.get("upload_id")
    part_number = int(payload.get("part_number", 1))
    etag = payload.get("etag")

    if session_id not in _UPLOAD_SESSIONS:
        raise HTTPException(status_code=404, detail="Upload session not found")

    session = _UPLOAD_SESSIONS[session_id]
    session["parts"].append({
        "PartNumber": part_number,
        "ETag": etag,
    })

    return {"status": "ok", "parts_uploaded": len(session["parts"])}


@app.post("/api/upload/complete-multipart")
async def api_complete_multipart(payload: Dict[str, Any]):
    """Complete a multipart upload."""
    session_id = payload.get("upload_id")

    if session_id not in _UPLOAD_SESSIONS:
        raise HTTPException(status_code=404, detail="Upload session not found")

    session = _UPLOAD_SESSIONS[session_id]

    try:
        s3 = get_r2_client()

        # Sort parts by part number
        parts = sorted(session["parts"], key=lambda p: p["PartNumber"])

        response = s3.complete_multipart_upload(
            Bucket=R2_BUCKET_NAME,
            Key=session["object_key"],
            UploadId=session["upload_id"],
            MultipartUpload={"Parts": parts},
        )

        # Clean up session
        del _UPLOAD_SESSIONS[session_id]

        print(f"[COMPLETE] Multipart upload completed: {session['object_key']}")

        return {
            "status": "ok",
            "object_key": session["object_key"],
            "location": response.get("Location", ""),
        }

    except Exception as e:
        print(f"[COMPLETE ERROR] {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to complete upload: {str(e)}")


@app.post("/api/upload/simple")
async def api_upload_simple(request: Request):
    """Handle simple file upload (small files) - proxy to R2."""
    session_id = request.headers.get("X-Upload-Id")
    content_type = request.headers.get("Content-Type") or "application/octet-stream"

    if not session_id or session_id not in _UPLOAD_SESSIONS:
        raise HTTPException(status_code=400, detail="Invalid or missing upload session")

    session = _UPLOAD_SESSIONS[session_id]
    body = await request.body()

    print(f"[SIMPLE] Uploading {len(body)} bytes to {session['object_key']}")

    try:
        s3 = get_r2_client()

        s3.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=session["object_key"],
            Body=body,
            ContentType=session.get("mime_type", content_type),
        )

        # Clean up session
        del _UPLOAD_SESSIONS[session_id]

        print(f"[SIMPLE] Upload complete: {session['object_key']}")

        return JSONResponse(content={
            "status": "complete",
            "object_key": session["object_key"],
        }, status_code=200)

    except Exception as e:
        print(f"[SIMPLE ERROR] {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.put("/api/upload/chunk")
async def api_upload_chunk(request: Request):
    """Handle chunk upload - proxy to R2 for multipart uploads."""
    session_id = request.headers.get("X-Upload-Id")
    content_range = request.headers.get("Content-Range")
    content_type = request.headers.get("Content-Type") or "application/octet-stream"

    if not session_id or session_id not in _UPLOAD_SESSIONS:
        raise HTTPException(status_code=400, detail="Invalid or missing upload session")

    session = _UPLOAD_SESSIONS[session_id]

    # Parse content range to determine part number
    # Format: bytes start-end/total
    try:
        range_parts = content_range.split(" ")[1].split("/")
        byte_range = range_parts[0]
        total = int(range_parts[1])
        start, end = map(int, byte_range.split("-"))

        # Calculate part number (5MB chunks)
        chunk_size = 5 * 1024 * 1024
        part_number = (start // chunk_size) + 1
    except Exception:
        part_number = len(session["parts"]) + 1

    try:
        body = await request.body()
    except Exception as e:
        print(f"[CHUNK ERROR] Failed to read request body: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to read chunk data: {str(e)}")

    print(f"[CHUNK] Uploading part {part_number}, {len(body)} bytes for {session['object_key']}")

    try:
        s3 = get_r2_client()

        response = s3.upload_part(
            Bucket=R2_BUCKET_NAME,
            Key=session["object_key"],
            UploadId=session["upload_id"],
            PartNumber=part_number,
            Body=body,
        )

        etag = response["ETag"]
        session["parts"].append({
            "PartNumber": part_number,
            "ETag": etag,
        })

        print(f"[CHUNK] Part {part_number} uploaded, ETag: {etag}")

        # Check if this is the last chunk
        if content_range:
            try:
                _, total_str = content_range.split("/")
                total = int(total_str)
                _, end_str = content_range.split(" ")[1].split("/")[0].split("-")
                end = int(end_str)

                if end + 1 >= total:
                    # This is the last chunk, complete the multipart upload
                    parts = sorted(session["parts"], key=lambda p: p["PartNumber"])

                    complete_response = s3.complete_multipart_upload(
                        Bucket=R2_BUCKET_NAME,
                        Key=session["object_key"],
                        UploadId=session["upload_id"],
                        MultipartUpload={"Parts": parts},
                    )

                    del _UPLOAD_SESSIONS[session_id]

                    print(f"[COMPLETE] Upload finished: {session['object_key']}")

                    return JSONResponse(content={
                        "status": "complete",
                        "object_key": session["object_key"],
                    }, status_code=200)
            except Exception as e:
                print(f"[CHUNK] Error checking completion: {e}")

        return JSONResponse(content={"status": "ok", "part_number": part_number}, status_code=200)

    except Exception as e:
        print(f"[CHUNK ERROR] {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chunk upload failed: {str(e)}")


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

    # Save manifest to R2
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

    try:
        s3 = get_r2_client()
        manifest_key = f"_manifests/{batch_id}.json"
        s3.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=manifest_key,
            Body=json.dumps(manifest, indent=2),
            ContentType="application/json",
        )
        print(f"[MANIFEST] Saved: {manifest_key}")
    except Exception as e:
        print(f"[MANIFEST ERROR] {type(e).__name__}: {str(e)}")
        # Don't fail the batch if manifest save fails

    total = update_upload_count(token, len(files))

    return {
        "status": "ok",
        "message": f"Thanks! You have preserved {total} memories.",
    }


# --- Dashboard Endpoints ---

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")  # Set this in Railway


def verify_dashboard_access(request: Request) -> bool:
    """Check if user has dashboard access via cookie."""
    if not DASHBOARD_PASSWORD:
        return True  # No password set, allow access
    auth_cookie = request.cookies.get("dashboard_auth")
    expected = hashlib.sha256(DASHBOARD_PASSWORD.encode()).hexdigest()[:32]
    return auth_cookie == expected


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    """Dashboard main page - shows all uploads from R2."""
    if not verify_dashboard_access(request):
        return RedirectResponse(url="/dashboard/login", status_code=302)
    return TEMPLATES.TemplateResponse("dashboard.html", {"request": request})


@app.get("/dashboard/login", response_class=HTMLResponse)
def dashboard_login_page(request: Request):
    """Dashboard login page."""
    if not DASHBOARD_PASSWORD:
        return RedirectResponse(url="/dashboard", status_code=302)
    return TEMPLATES.TemplateResponse("dashboard_login.html", {"request": request})


@app.post("/dashboard/login")
async def dashboard_login(request: Request):
    """Handle dashboard login."""
    form = await request.form()
    password = form.get("password", "")

    if password == DASHBOARD_PASSWORD:
        response = RedirectResponse(url="/dashboard", status_code=302)
        auth_hash = hashlib.sha256(DASHBOARD_PASSWORD.encode()).hexdigest()[:32]
        response.set_cookie("dashboard_auth", auth_hash, max_age=86400 * 7)  # 7 days
        return response

    return TEMPLATES.TemplateResponse(
        "dashboard_login.html",
        {"request": request, "error": "Invalid password"}
    )


@app.get("/api/dashboard/files")
async def api_dashboard_files(request: Request):
    """Get all files from R2 for the dashboard."""
    if not verify_dashboard_access(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        s3 = get_r2_client()

        # List all objects in the bucket
        paginator = s3.get_paginator('list_objects_v2')

        files = []
        contributors = set()

        for page in paginator.paginate(Bucket=R2_BUCKET_NAME):
            for obj in page.get('Contents', []):
                key = obj['Key']

                # Skip manifests folder
                if key.startswith('_manifests/'):
                    continue

                # Parse contributor folder from key
                parts = key.split('/')
                contributor = parts[0] if len(parts) > 1 else 'unknown'
                contributors.add(contributor)

                files.append({
                    "key": key,
                    "contributor": contributor,
                    "filename": parts[-1] if parts else key,
                    "size": obj['Size'],
                    "last_modified": obj['LastModified'].isoformat(),
                })

        # Sort by most recent
        files.sort(key=lambda x: x['last_modified'], reverse=True)

        return {
            "files": files,
            "total_files": len(files),
            "contributors": sorted(list(contributors)),
        }

    except Exception as e:
        print(f"[DASHBOARD ERROR] {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/manifests")
async def api_dashboard_manifests(request: Request):
    """Get all batch manifests from R2."""
    if not verify_dashboard_access(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        s3 = get_r2_client()

        # List manifests
        response = s3.list_objects_v2(
            Bucket=R2_BUCKET_NAME,
            Prefix='_manifests/'
        )

        manifests = []
        for obj in response.get('Contents', []):
            key = obj['Key']
            if not key.endswith('.json'):
                continue

            # Get manifest content
            manifest_obj = s3.get_object(Bucket=R2_BUCKET_NAME, Key=key)
            manifest_data = json.loads(manifest_obj['Body'].read().decode('utf-8'))
            manifest_data['_key'] = key
            manifests.append(manifest_data)

        # Sort by created_at descending
        manifests.sort(key=lambda x: x.get('created_at', ''), reverse=True)

        return {"manifests": manifests, "total": len(manifests)}

    except Exception as e:
        print(f"[MANIFESTS ERROR] {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/thumbnail/{file_key:path}")
async def api_dashboard_thumbnail(request: Request, file_key: str):
    """Generate a presigned URL for a file thumbnail."""
    if not verify_dashboard_access(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        s3 = get_r2_client()

        # Generate presigned URL valid for 1 hour
        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': R2_BUCKET_NAME, 'Key': file_key},
            ExpiresIn=3600,
        )

        return {"url": url}

    except Exception as e:
        print(f"[THUMBNAIL ERROR] {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/stats")
async def api_dashboard_stats(request: Request):
    """Get dashboard statistics."""
    if not verify_dashboard_access(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        s3 = get_r2_client()

        # Count files and total size
        paginator = s3.get_paginator('list_objects_v2')

        total_files = 0
        total_size = 0
        contributors = set()

        for page in paginator.paginate(Bucket=R2_BUCKET_NAME):
            for obj in page.get('Contents', []):
                key = obj['Key']
                if key.startswith('_manifests/'):
                    continue
                total_files += 1
                total_size += obj['Size']
                parts = key.split('/')
                if len(parts) > 1:
                    contributors.add(parts[0])

        # Count manifests
        manifest_resp = s3.list_objects_v2(Bucket=R2_BUCKET_NAME, Prefix='_manifests/')
        total_batches = len([o for o in manifest_resp.get('Contents', []) if o['Key'].endswith('.json')])

        return {
            "total_files": total_files,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "total_batches": total_batches,
            "total_contributors": len(contributors),
        }

    except Exception as e:
        print(f"[STATS ERROR] {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Family Gallery Endpoints ---

def verify_gallery_access(request: Request) -> bool:
    """Check if user has gallery access via cookie (using family code)."""
    if not FAMILY_CODE:
        return True  # No family code set, allow access
    auth_cookie = request.cookies.get("gallery_auth")
    expected = hashlib.sha256(FAMILY_CODE.encode()).hexdigest()[:32]
    return auth_cookie == expected


@app.get("/gallery", response_class=HTMLResponse)
def gallery_page(request: Request):
    """Family photo gallery - beautiful viewing experience."""
    if not verify_gallery_access(request):
        return RedirectResponse(url="/gallery/login", status_code=302)
    return TEMPLATES.TemplateResponse("gallery.html", {"request": request})


@app.get("/gallery/login", response_class=HTMLResponse)
def gallery_login_page(request: Request):
    """Gallery login page."""
    if not FAMILY_CODE:
        return RedirectResponse(url="/gallery", status_code=302)
    return TEMPLATES.TemplateResponse("gallery_login.html", {"request": request})


@app.post("/gallery/login")
async def gallery_login(request: Request):
    """Handle gallery login with family code."""
    form = await request.form()
    code = form.get("family_code", "")

    if secrets.compare_digest(code, FAMILY_CODE):
        response = RedirectResponse(url="/gallery", status_code=302)
        auth_hash = hashlib.sha256(FAMILY_CODE.encode()).hexdigest()[:32]
        response.set_cookie("gallery_auth", auth_hash, max_age=86400 * 30)  # 30 days
        return response

    return TEMPLATES.TemplateResponse(
        "gallery_login.html",
        {"request": request, "error": "Invalid family code"}
    )


@app.get("/api/gallery/photos")
async def api_gallery_photos(request: Request):
    """Get all photos for the gallery, organized by batch/event."""
    if not verify_gallery_access(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        s3 = get_r2_client()

        # Get all manifests to understand the batches
        manifest_resp = s3.list_objects_v2(Bucket=R2_BUCKET_NAME, Prefix='_manifests/')

        batches = []
        all_files_in_batches = set()

        for obj in manifest_resp.get('Contents', []):
            key = obj['Key']
            if not key.endswith('.json'):
                continue

            manifest_obj = s3.get_object(Bucket=R2_BUCKET_NAME, Key=key)
            manifest = json.loads(manifest_obj['Body'].read().decode('utf-8'))

            # Get files for this batch
            batch_files = []
            for f in manifest.get('files', []):
                object_key = f.get('object_key', '')
                if object_key:
                    all_files_in_batches.add(object_key)
                    batch_files.append({
                        "key": object_key,
                        "name": f.get('original_name', ''),
                        "size": f.get('size', 0),
                    })

            batches.append({
                "id": manifest.get('batch_id', ''),
                "contributor": manifest.get('contributor_display_name', 'Unknown'),
                "date": manifest.get('created_at', ''),
                "decade": manifest.get('decade', ''),
                "notes": manifest.get('notes', ''),
                "event": manifest.get('event', ''),
                "files": batch_files,
                "file_count": len(batch_files),
            })

        # Sort batches by date (newest first)
        batches.sort(key=lambda x: x['date'], reverse=True)

        # Also get any files not in manifests (orphaned files)
        paginator = s3.get_paginator('list_objects_v2')
        orphaned = []

        for page in paginator.paginate(Bucket=R2_BUCKET_NAME):
            for obj in page.get('Contents', []):
                key = obj['Key']
                if key.startswith('_manifests/'):
                    continue
                if key not in all_files_in_batches:
                    parts = key.split('/')
                    orphaned.append({
                        "key": key,
                        "name": parts[-1] if parts else key,
                        "size": obj['Size'],
                        "contributor": parts[0].replace('_UPLOADS', '') if len(parts) > 1 else 'Unknown',
                    })

        return {
            "batches": batches,
            "orphaned_files": orphaned,
            "total_batches": len(batches),
        }

    except Exception as e:
        print(f"[GALLERY ERROR] {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gallery/image/{file_key:path}")
async def api_gallery_image(request: Request, file_key: str):
    """Generate a presigned URL for viewing an image in the gallery."""
    if not verify_gallery_access(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        # Check cache first to avoid R2 rate limiting
        cache_key = f"url:{file_key}"
        now = time.time()

        if cache_key in _URL_CACHE:
            cached_url, cached_time = _URL_CACHE[cache_key]
            if now - cached_time < _URL_CACHE_TTL:
                return {"url": cached_url}

        s3 = get_r2_client()

        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': R2_BUCKET_NAME, 'Key': file_key},
            ExpiresIn=3600,
        )

        # Cache the URL
        _URL_CACHE[cache_key] = (url, now)

        # Clean old cache entries periodically (every 100 requests)
        if len(_URL_CACHE) > 500:
            cutoff = now - _URL_CACHE_TTL
            keys_to_delete = [k for k, (_, t) in _URL_CACHE.items() if t < cutoff]
            for k in keys_to_delete:
                del _URL_CACHE[k]

        return {"url": url}

    except Exception as e:
        print(f"[GALLERY IMAGE ERROR] {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
