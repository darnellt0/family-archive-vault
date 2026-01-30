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

    body = await request.body()
    print(f"[CHUNK] Uploading part {part_number}, {len(body)} bytes")

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
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


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
