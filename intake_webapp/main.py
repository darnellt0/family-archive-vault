"""Main FastAPI application for intake web app."""
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict
import aiofiles
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.config import get_settings
from shared.drive_client import DriveClient
from shared.models import UploadManifest


app = FastAPI(title="Family Archive Vault - Intake")

# CORS for mobile uploads
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# Global state
settings = get_settings()
drive_client: Optional[DriveClient] = None
upload_sessions: Dict[str, dict] = {}  # session_id -> session info


class UploadInitRequest(BaseModel):
    """Request to initialize an upload."""
    token: str
    filename: str
    file_size: int
    mime_type: str
    batch_id: Optional[str] = None


class UploadChunkRequest(BaseModel):
    """Request to upload a chunk."""
    session_id: str
    chunk_index: int
    total_chunks: int


class UploadFinishRequest(BaseModel):
    """Request to finalize upload."""
    session_id: str
    batch_id: str
    decade: Optional[int] = None
    event_name: Optional[str] = None
    notes: Optional[str] = None


class ManifestRequest(BaseModel):
    """Request to save a manifest."""
    token: str
    batch_id: str
    decade: Optional[int] = None
    event_name: Optional[str] = None
    notes: Optional[str] = None
    voice_note_file_id: Optional[str] = None
    uploaded_files: list


@app.on_event("startup")
async def startup_event():
    """Initialize Drive client on startup."""
    global drive_client
    try:
        drive_client = DriveClient(
            settings.service_account_json_path,
            settings.drive_root_folder_id
        )
        logger.info("Drive client initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Drive client: {e}")
        raise


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/u/{token}", response_class=HTMLResponse)
async def uploader_page(request: Request, token: str):
    """Uploader page for a specific contributor token."""
    contributor_folders = settings.get_contributor_tokens()

    if token not in contributor_folders:
        raise HTTPException(status_code=404, detail="Invalid token")

    return templates.TemplateResponse(
        "uploader.html",
        {
            "request": request,
            "token": token,
            "contributor_name": contributor_folders[token]
        }
    )


@app.post("/api/upload/init")
async def init_upload(req: UploadInitRequest):
    """Initialize a resumable upload session."""
    contributor_folders = settings.get_contributor_tokens()

    if req.token not in contributor_folders:
        raise HTTPException(status_code=403, detail="Invalid token")

    contributor_folder = contributor_folders[req.token]

    try:
        # Get or create the contributor folder in Drive
        folder_ids = drive_client.folder_cache
        if not folder_ids:
            # Initialize folder structure if not cached
            drive_client.setup_folder_structure(list(contributor_folders.values()))

        # Get the contributor's upload folder
        inbox_id = drive_client.get_or_create_folder("INBOX_UPLOADS")
        contributor_folder_id = drive_client.get_or_create_folder(contributor_folder, inbox_id)

        # Create upload session
        session_id = str(uuid.uuid4())
        upload_sessions[session_id] = {
            "filename": req.filename,
            "file_size": req.file_size,
            "mime_type": req.mime_type,
            "token": req.token,
            "contributor_folder_id": contributor_folder_id,
            "batch_id": req.batch_id or f"batch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
            "chunks": {},
            "created_at": datetime.utcnow()
        }

        logger.info(f"Initialized upload session {session_id} for {req.filename}")

        return {
            "session_id": session_id,
            "batch_id": upload_sessions[session_id]["batch_id"],
            "chunk_size": settings.upload_chunk_size_mb * 1024 * 1024
        }

    except Exception as e:
        logger.error(f"Error initializing upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload/chunk")
async def upload_chunk(
    session_id: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    chunk: UploadFile = File(...)
):
    """Upload a file chunk."""
    if session_id not in upload_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = upload_sessions[session_id]

    try:
        # Save chunk to temporary storage
        temp_dir = Path(settings.local_cache) / "upload_chunks" / session_id
        temp_dir.mkdir(parents=True, exist_ok=True)

        chunk_path = temp_dir / f"chunk_{chunk_index}"
        async with aiofiles.open(chunk_path, 'wb') as f:
            content = await chunk.read()
            await f.write(content)

        session["chunks"][chunk_index] = str(chunk_path)

        logger.info(f"Received chunk {chunk_index + 1}/{total_chunks} for session {session_id}")

        return {
            "status": "chunk_received",
            "chunk_index": chunk_index,
            "total_chunks": total_chunks
        }

    except Exception as e:
        logger.error(f"Error uploading chunk: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload/finish")
async def finish_upload(req: UploadFinishRequest):
    """Finalize the upload and upload to Drive."""
    if req.session_id not in upload_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = upload_sessions[req.session_id]

    try:
        # Reassemble chunks
        temp_dir = Path(settings.local_cache) / "upload_chunks" / req.session_id
        final_file = temp_dir / session["filename"]

        with open(final_file, 'wb') as outfile:
            for i in sorted(session["chunks"].keys()):
                chunk_path = session["chunks"][i]
                with open(chunk_path, 'rb') as infile:
                    outfile.write(infile.read())

        logger.info(f"Reassembled file {session['filename']}")

        # Upload to Drive
        drive_file_id = drive_client.upload_file(
            final_file,
            session["contributor_folder_id"],
            session["mime_type"]
        )

        if not drive_file_id:
            raise Exception("Failed to upload to Drive")

        # Clean up chunks
        for chunk_path in session["chunks"].values():
            Path(chunk_path).unlink(missing_ok=True)
        final_file.unlink(missing_ok=True)
        temp_dir.rmdir()

        # Remove session
        del upload_sessions[req.session_id]

        logger.info(f"Upload complete: {session['filename']} -> Drive file {drive_file_id}")

        return {
            "status": "complete",
            "drive_file_id": drive_file_id,
            "filename": session["filename"]
        }

    except Exception as e:
        logger.error(f"Error finishing upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/manifest/save")
async def save_manifest(req: ManifestRequest):
    """Save upload manifest to Drive."""
    contributor_folders = settings.get_contributor_tokens()

    if req.token not in contributor_folders:
        raise HTTPException(status_code=403, detail="Invalid token")

    try:
        # Create manifest
        manifest = UploadManifest(
            batch_id=req.batch_id,
            contributor_token=req.token,
            contributor_folder=contributor_folders[req.token],
            decade=req.decade,
            event_name=req.event_name,
            notes=req.notes,
            voice_note_file_id=req.voice_note_file_id,
            uploaded_files=req.uploaded_files,
            upload_end=datetime.utcnow(),
            total_files=len(req.uploaded_files),
            total_bytes=sum(f.get("size", 0) for f in req.uploaded_files)
        )

        # Get manifests folder
        inbox_id = drive_client.get_or_create_folder("INBOX_UPLOADS")
        manifests_folder_id = drive_client.get_or_create_folder("_MANIFESTS", inbox_id)

        # Upload manifest
        manifest_filename = f"batch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{req.token}.json"
        manifest_file_id = drive_client.upload_json(
            manifest.dict(),
            manifest_filename,
            manifests_folder_id
        )

        logger.info(f"Saved manifest {manifest_filename} to Drive")

        return {
            "status": "manifest_saved",
            "batch_id": req.batch_id,
            "manifest_file_id": manifest_file_id
        }

    except Exception as e:
        logger.error(f"Error saving manifest: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "drive_connected": drive_client is not None,
        "active_sessions": len(upload_sessions)
    }


def main():
    """Run the intake app."""
    import uvicorn
    uvicorn.run(
        app,
        host=settings.intake_host,
        port=settings.intake_port,
        log_level="info"
    )


if __name__ == "__main__":
    main()
