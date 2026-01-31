import io
import logging
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from .config import (
    SERVICE_ACCOUNT_FILE,
    SERVICE_ACCOUNT_JSON,
    DRIVE_SCHEMA_CACHE,
    DRIVE_ROOT_FOLDER_ID,
    R2_BUCKET_NAME,
    R2_SYNC_POLL_INTERVAL,
    R2_SYNC_BATCH_SIZE,
    R2_SYNC_DELETE_AFTER,
    R2_SYNC_TEMP_DIR,
    R2_EXCLUDE_PREFIXES,
    CONFIG_DIR,
)
from .r2_client import get_r2_client, list_objects, download_object, delete_object
from .db import (
    get_sync_db,
    init_sync_db,
    is_object_synced,
    record_sync_start,
    record_sync_complete,
    record_sync_error,
    get_sync_stats,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]

# MIME type mapping
MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".m4v": "video/x-m4v",
}


def get_drive_service():
    """Get Google Drive API service.

    Supports two modes:
    1. SERVICE_ACCOUNT_JSON env var: JSON content (for Railway/cloud)
    2. SERVICE_ACCOUNT_JSON_PATH: Path to file (for local)
    """
    import json

    if SERVICE_ACCOUNT_JSON:
        # Load from environment variable (Railway deployment)
        try:
            info = json.loads(SERVICE_ACCOUNT_JSON)
            creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
            logger.info("Using service account from SERVICE_ACCOUNT_JSON env var")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid SERVICE_ACCOUNT_JSON: {e}")
    elif SERVICE_ACCOUNT_FILE.exists():
        # Load from file (local development)
        creds = service_account.Credentials.from_service_account_file(
            str(SERVICE_ACCOUNT_FILE), scopes=SCOPES
        )
        logger.info(f"Using service account from file: {SERVICE_ACCOUNT_FILE}")
    else:
        raise RuntimeError(
            "No service account credentials found. Set SERVICE_ACCOUNT_JSON env var "
            f"or provide file at {SERVICE_ACCOUNT_FILE}"
        )

    return build("drive", "v3", credentials=creds)


def load_drive_schema(service) -> Dict[str, str]:
    """Load Drive folder schema from cache or create it."""
    import json

    # Try loading from cache first
    if DRIVE_SCHEMA_CACHE.exists():
        try:
            data = json.loads(DRIVE_SCHEMA_CACHE.read_text(encoding="utf-8"))
            if "INBOX_UPLOADS" in data:
                logger.info("Loaded Drive schema from cache")
                return data
        except Exception:
            pass

    # Build schema if not cached (needed for Railway where no cache exists)
    if not DRIVE_ROOT_FOLDER_ID:
        raise RuntimeError("DRIVE_ROOT_FOLDER_ID not set")

    logger.info("Building Drive schema...")
    schema = {
        "ROOT": DRIVE_ROOT_FOLDER_ID,
        "INBOX_UPLOADS": ensure_folder(service, DRIVE_ROOT_FOLDER_ID, "INBOX_UPLOADS"),
    }
    schema["INBOX_MANIFESTS"] = ensure_folder(service, schema["INBOX_UPLOADS"], "_MANIFESTS")

    # Cache the schema
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        DRIVE_SCHEMA_CACHE.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        logger.info("Cached Drive schema")
    except Exception as e:
        logger.warning(f"Could not cache schema: {e}")

    return schema


def ensure_folder(service, parent_id: str, name: str) -> str:
    """Ensure a folder exists in Drive, create if not."""
    query = (
        f"name='{name}' and '{parent_id}' in parents and "
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
    logger.info(f"Created folder: {name}")
    return folder["id"]


def upload_json(service, folder_id: str, name: str, payload: dict) -> str:
    """Upload JSON data to Drive."""
    import json
    data = json.dumps(payload, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype="application/json", resumable=False)
    file = service.files().create(
        body={"name": name, "parents": [folder_id]},
        media_body=media,
        fields="id",
    ).execute()
    return file["id"]


def get_mime_type(filename: str) -> str:
    """Get MIME type from filename extension."""
    ext = Path(filename).suffix.lower()
    return MIME_TYPES.get(ext, "application/octet-stream")


class R2SyncWorker:
    """Worker that syncs files from R2 to Google Drive INBOX."""

    def __init__(self):
        self.r2_client = get_r2_client()
        self.drive_service = get_drive_service()
        self.drive_schema = load_drive_schema(self.drive_service)
        self.db_conn = get_sync_db()
        init_sync_db(self.db_conn)
        logger.info("R2 Sync Worker initialized")

    def run_once(self):
        """Single sync cycle."""
        logger.info("Starting R2 sync cycle")

        # List all R2 objects
        all_objects = list_objects(self.r2_client, R2_BUCKET_NAME)
        logger.info(f"Found {len(all_objects)} total objects in R2")

        # Filter out manifests, already synced, and excluded prefixes
        objects_to_sync = []
        for obj in all_objects:
            key = obj["key"]

            # Skip excluded prefixes
            if any(key.lower().startswith(prefix) for prefix in R2_EXCLUDE_PREFIXES):
                continue

            # Skip already synced
            if is_object_synced(self.db_conn, key):
                continue

            objects_to_sync.append(obj)

        if not objects_to_sync:
            logger.info("No new files to sync")
            return

        logger.info(f"Found {len(objects_to_sync)} files to sync")

        # Group by contributor folder
        by_contributor: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for obj in objects_to_sync[:R2_SYNC_BATCH_SIZE]:
            # Extract contributor folder: "{ContributorName}_UPLOADS/timestamp_filename"
            parts = obj["key"].split("/", 1)
            contributor_folder = parts[0] if len(parts) > 1 else "Unknown_UPLOADS"
            by_contributor[contributor_folder].append(obj)

        # Sync each contributor batch
        for contributor_folder, objects in by_contributor.items():
            self._sync_contributor_batch(contributor_folder, objects)

        # Log stats
        stats = get_sync_stats(self.db_conn)
        logger.info(f"Sync stats: {stats}")

    def _sync_contributor_batch(self, contributor_folder: str, objects: List[Dict[str, Any]]):
        """Sync a batch of files from one contributor."""
        logger.info(f"Syncing {len(objects)} files from {contributor_folder}")

        # Create or get contributor folder in Drive
        inbox_id = self.drive_schema["INBOX_UPLOADS"]
        drive_folder_id = ensure_folder(self.drive_service, inbox_id, contributor_folder)

        # Create manifest for this batch
        batch_id = f"r2sync_{int(time.time())}_{contributor_folder[:20]}"
        manifest_files = []

        for obj in objects:
            try:
                drive_file_id = self._sync_single_file(obj, drive_folder_id)
                if drive_file_id:
                    manifest_files.append({
                        "drive_file_id": drive_file_id,
                        "original_name": obj["key"].split("/")[-1],
                        "size": obj["size"],
                        "r2_key": obj["key"],
                    })
                    record_sync_complete(self.db_conn, obj["key"], drive_file_id, batch_id)

                    # Optionally delete from R2
                    if R2_SYNC_DELETE_AFTER:
                        delete_object(self.r2_client, R2_BUCKET_NAME, obj["key"])

            except Exception as e:
                logger.exception(f"Failed to sync {obj['key']}: {e}")
                record_sync_error(self.db_conn, obj["key"], str(e))

        # Upload manifest to Drive
        if manifest_files:
            manifest = {
                "batch_id": batch_id,
                "contributor_token": contributor_folder.replace("_UPLOADS", ""),
                "contributor_display_name": contributor_folder.replace("_UPLOADS", "").replace("_", " "),
                "source": "r2_sync",
                "created_at": datetime.utcnow().isoformat(),
                "files": manifest_files,
            }
            manifest_folder_id = self.drive_schema.get("INBOX_MANIFESTS")
            if not manifest_folder_id:
                manifest_folder_id = ensure_folder(self.drive_service, inbox_id, "_MANIFESTS")

            upload_json(self.drive_service, manifest_folder_id, f"{batch_id}.json", manifest)
            logger.info(f"Created manifest: {batch_id}.json with {len(manifest_files)} files")

    def _sync_single_file(self, obj: Dict[str, Any], drive_folder_id: str) -> Optional[str]:
        """Download from R2 and upload to Drive. Returns Drive file ID."""
        key = obj["key"]
        filename = key.split("/")[-1]
        size = obj["size"]

        record_sync_start(self.db_conn, key, obj["etag"], size, key.split("/")[0])

        # Download to temp location
        local_path = R2_SYNC_TEMP_DIR / filename
        download_object(self.r2_client, R2_BUCKET_NAME, key, local_path)

        try:
            mime_type = get_mime_type(filename)

            # Use resumable upload for files > 5MB
            if size > 5 * 1024 * 1024:
                drive_file_id = self._resumable_upload(local_path, drive_folder_id, filename, mime_type)
            else:
                drive_file_id = self._simple_upload(local_path, drive_folder_id, filename, mime_type)

            logger.info(f"Uploaded {filename} to Drive: {drive_file_id}")
            return drive_file_id

        finally:
            # Clean up local temp file
            if local_path.exists():
                local_path.unlink()

    def _simple_upload(self, local_path: Path, folder_id: str, filename: str, mime_type: str) -> str:
        """Simple upload for smaller files."""
        media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=False)
        file = self.drive_service.files().create(
            body={"name": filename, "parents": [folder_id]},
            media_body=media,
            fields="id"
        ).execute()
        return file["id"]

    def _resumable_upload(self, local_path: Path, folder_id: str, filename: str, mime_type: str) -> str:
        """Resumable upload for large files (videos)."""
        media = MediaFileUpload(
            str(local_path),
            mimetype=mime_type,
            resumable=True,
            chunksize=10 * 1024 * 1024  # 10MB chunks
        )
        request = self.drive_service.files().create(
            body={"name": filename, "parents": [folder_id]},
            media_body=media,
            fields="id"
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.debug(f"Upload progress for {filename}: {int(status.progress() * 100)}%")
        return response["id"]

    def run_forever(self):
        """Main loop - poll and sync continuously."""
        logger.info(f"R2 Sync Worker started. Polling every {R2_SYNC_POLL_INTERVAL} seconds")
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.exception(f"Sync cycle failed: {e}")
            time.sleep(R2_SYNC_POLL_INTERVAL)
