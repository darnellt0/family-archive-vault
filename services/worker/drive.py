import json
from pathlib import Path
from typing import Dict, List

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
import io

from .config import SERVICE_ACCOUNT_FILE, DRIVE_ROOT_FOLDER_ID, DRIVE_SCHEMA_CACHE

SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_FILE), scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def ensure_folder(service, parent_id: str, name: str) -> str:
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
    return folder["id"]


def ensure_drive_schema(service) -> Dict[str, str]:
    if not DRIVE_ROOT_FOLDER_ID:
        raise RuntimeError("DRIVE_ROOT_FOLDER_ID is not set")

    schema = {
        "ROOT": DRIVE_ROOT_FOLDER_ID,
        "INBOX_UPLOADS": ensure_folder(service, DRIVE_ROOT_FOLDER_ID, "INBOX_UPLOADS"),
        "PROCESSING": ensure_folder(service, DRIVE_ROOT_FOLDER_ID, "PROCESSING"),
        "HOLDING": ensure_folder(service, DRIVE_ROOT_FOLDER_ID, "HOLDING"),
        "ARCHIVE": ensure_folder(service, DRIVE_ROOT_FOLDER_ID, "ARCHIVE"),
        "METADATA": ensure_folder(service, DRIVE_ROOT_FOLDER_ID, "METADATA"),
        "ROSETTA_STONE": ensure_folder(service, DRIVE_ROOT_FOLDER_ID, "ROSETTA_STONE"),
        "HELPERS": ensure_folder(service, DRIVE_ROOT_FOLDER_ID, "HELPERS"),
    }

    schema.update({
        "INBOX_MANIFESTS": ensure_folder(service, schema["INBOX_UPLOADS"], "_MANIFESTS"),
        "HOLDING_NEEDS_REVIEW": ensure_folder(service, schema["HOLDING"], "Needs_Review"),
        "HOLDING_DUPLICATES": ensure_folder(service, schema["HOLDING"], "Possible_Duplicates"),
        "HOLDING_LOW_CONF": ensure_folder(service, schema["HOLDING"], "Low_Confidence"),
        "HOLDING_TRANSCRIBE_LATER": ensure_folder(service, schema["HOLDING"], "Transcribe_Later"),
        "ARCHIVE_ORIGINALS": ensure_folder(service, schema["ARCHIVE"], "Originals"),
        "ARCHIVE_VIDEOS": ensure_folder(service, schema["ARCHIVE"], "Videos"),
        "ARCHIVE_PRINT": ensure_folder(service, schema["ARCHIVE"], "Print_Ready"),
        "METADATA_SIDECARS": ensure_folder(service, schema["METADATA"], "sidecars_json"),
        "METADATA_THUMBNAILS": ensure_folder(service, schema["METADATA"], "thumbnails"),
        "METADATA_POSTERS": ensure_folder(service, schema["METADATA"], "video_posters"),
        "METADATA_TRANSCRIPTS": ensure_folder(service, schema["METADATA"], "transcripts"),
        "ROSETTA_SITE": ensure_folder(service, schema["ROSETTA_STONE"], "nightly_site"),
    })

    DRIVE_SCHEMA_CACHE.parent.mkdir(parents=True, exist_ok=True)
    DRIVE_SCHEMA_CACHE.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    return schema


def load_drive_schema(service) -> Dict[str, str]:
    if DRIVE_SCHEMA_CACHE.exists():
        try:
            data = json.loads(DRIVE_SCHEMA_CACHE.read_text(encoding="utf-8"))
            if "ROOT" in data:
                return data
        except Exception:
            pass
    return ensure_drive_schema(service)


def list_files(service, folder_id: str) -> List[dict]:
    results = service.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id, name, mimeType, size, createdTime)",
        pageSize=1000,
    ).execute()
    return results.get("files", [])


def download_file(service, file_id: str, destination: Path):
    request = service.files().get_media(fileId=file_id)
    with destination.open("wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            _, done = downloader.next_chunk()


def move_file(service, file_id: str, target_folder_id: str):
    file = service.files().get(fileId=file_id, fields="parents").execute()
    previous_parents = ",".join(file.get("parents", []))
    service.files().update(
        fileId=file_id,
        addParents=target_folder_id,
        removeParents=previous_parents,
        fields="id, parents",
    ).execute()


def upload_json(service, folder_id: str, name: str, payload: dict) -> str:
    data = json.dumps(payload, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype="application/json", resumable=False)
    file = service.files().create(
        body={"name": name, "parents": [folder_id]},
        media_body=media,
        fields="id",
    ).execute()
    return file["id"]
