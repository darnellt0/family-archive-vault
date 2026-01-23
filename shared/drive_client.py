"""Google Drive client for Family Archive Vault."""
import io
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload, MediaFileUpload
from googleapiclient.errors import HttpError
from loguru import logger


class DriveClient:
    """Google Drive API client with folder management."""

    # Drive folder structure
    FOLDER_STRUCTURE = {
        "INBOX_UPLOADS": {
            "_MANIFESTS": {}
        },
        "PROCESSING": {},
        "HOLDING": {
            "Needs_Review": {},
            "Possible_Duplicates": {},
            "Low_Confidence": {}
        },
        "ARCHIVE": {
            "Originals": {},
            "Videos": {},
            "Print_Ready": {}
        },
        "METADATA": {
            "sidecars_json": {},
            "thumbnails": {},
            "video_posters": {},
            "transcripts": {}
        },
        "ROSETTA_STONE": {
            "nightly_site": {}
        }
    }

    def __init__(self, service_account_path: str, root_folder_id: str):
        """Initialize Drive client."""
        self.root_folder_id = root_folder_id
        credentials = service_account.Credentials.from_service_account_file(
            service_account_path,
            scopes=['https://www.googleapis.com/auth/drive']
        )
        self.service = build('drive', 'v3', credentials=credentials)
        self.folder_cache: Dict[str, str] = {}

    def get_service_account_email(self) -> str:
        """Get the service account email for sharing instructions."""
        about = self.service.about().get(fields="user").execute()
        return about.get('user', {}).get('emailAddress', 'unknown')

    def create_folder(self, name: str, parent_id: Optional[str] = None) -> str:
        """Create a folder and return its ID."""
        if parent_id is None:
            parent_id = self.root_folder_id

        file_metadata = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }

        try:
            folder = self.service.files().create(
                body=file_metadata,
                fields='id'
            ).execute()
            logger.info(f"Created folder: {name} (ID: {folder['id']})")
            return folder['id']
        except HttpError as e:
            logger.error(f"Error creating folder {name}: {e}")
            raise

    def find_folder(self, name: str, parent_id: Optional[str] = None) -> Optional[str]:
        """Find a folder by name within a parent."""
        if parent_id is None:
            parent_id = self.root_folder_id

        query = f"name='{name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"

        try:
            results = self.service.files().list(
                q=query,
                fields='files(id, name)',
                pageSize=1
            ).execute()
            files = results.get('files', [])
            return files[0]['id'] if files else None
        except HttpError as e:
            logger.error(f"Error finding folder {name}: {e}")
            return None

    def get_or_create_folder(self, name: str, parent_id: Optional[str] = None) -> str:
        """Get existing folder or create if it doesn't exist."""
        cache_key = f"{parent_id or self.root_folder_id}:{name}"
        if cache_key in self.folder_cache:
            return self.folder_cache[cache_key]

        folder_id = self.find_folder(name, parent_id)
        if not folder_id:
            folder_id = self.create_folder(name, parent_id)

        self.folder_cache[cache_key] = folder_id
        return folder_id

    def setup_folder_structure(self, contributor_folders: List[str]) -> Dict[str, str]:
        """Create the complete folder structure and return folder IDs."""
        folder_ids = {"root": self.root_folder_id}

        def create_structure(structure: dict, parent_id: str, path: str = ""):
            for folder_name, children in structure.items():
                current_path = f"{path}/{folder_name}" if path else folder_name
                folder_id = self.get_or_create_folder(folder_name, parent_id)
                folder_ids[current_path] = folder_id

                if isinstance(children, dict) and children:
                    create_structure(children, folder_id, current_path)

        create_structure(self.FOLDER_STRUCTURE, self.root_folder_id)

        # Create contributor folders in INBOX_UPLOADS
        inbox_id = folder_ids.get("INBOX_UPLOADS")
        if inbox_id:
            for contributor_folder in contributor_folders:
                folder_id = self.get_or_create_folder(contributor_folder, inbox_id)
                folder_ids[f"INBOX_UPLOADS/{contributor_folder}"] = folder_id

        # Create decade folders in ARCHIVE/Originals and ARCHIVE/Videos
        for decade in range(1940, 2030, 10):
            originals_id = folder_ids.get("ARCHIVE/Originals")
            if originals_id:
                decade_str = f"{decade}s"
                folder_id = self.get_or_create_folder(decade_str, originals_id)
                folder_ids[f"ARCHIVE/Originals/{decade_str}"] = folder_id

            videos_id = folder_ids.get("ARCHIVE/Videos")
            if videos_id:
                decade_str = f"{decade}s"
                folder_id = self.get_or_create_folder(decade_str, videos_id)
                folder_ids[f"ARCHIVE/Videos/{decade_str}"] = folder_id

        return folder_ids

    def list_files(self, folder_id: str, page_size: int = 100) -> List[Dict[str, Any]]:
        """List all files in a folder."""
        files = []
        page_token = None

        try:
            while True:
                query = f"'{folder_id}' in parents and trashed=false"
                results = self.service.files().list(
                    q=query,
                    fields='nextPageToken, files(id, name, mimeType, size, createdTime, modifiedTime)',
                    pageSize=page_size,
                    pageToken=page_token
                ).execute()

                files.extend(results.get('files', []))
                page_token = results.get('nextPageToken')

                if not page_token:
                    break

            return files
        except HttpError as e:
            logger.error(f"Error listing files in folder {folder_id}: {e}")
            return []

    def download_file(self, file_id: str, destination: Path) -> bool:
        """Download a file from Drive."""
        try:
            request = self.service.files().get_media(fileId=file_id)
            destination.parent.mkdir(parents=True, exist_ok=True)

            with open(destination, 'wb') as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    if status:
                        logger.debug(f"Download progress: {int(status.progress() * 100)}%")

            logger.info(f"Downloaded file {file_id} to {destination}")
            return True
        except HttpError as e:
            logger.error(f"Error downloading file {file_id}: {e}")
            return False

    def upload_file(self, file_path: Path, folder_id: str, mime_type: Optional[str] = None) -> Optional[str]:
        """Upload a file to Drive."""
        try:
            file_metadata = {
                'name': file_path.name,
                'parents': [folder_id]
            }

            media = MediaFileUpload(
                str(file_path),
                mimetype=mime_type,
                resumable=True
            )

            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()

            logger.info(f"Uploaded {file_path.name} to folder {folder_id}")
            return file['id']
        except HttpError as e:
            logger.error(f"Error uploading file {file_path}: {e}")
            return None

    def upload_json(self, data: dict, filename: str, folder_id: str) -> Optional[str]:
        """Upload JSON data to Drive."""
        try:
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }

            json_str = json.dumps(data, indent=2, default=str)
            media = MediaIoBaseUpload(
                io.BytesIO(json_str.encode('utf-8')),
                mimetype='application/json',
                resumable=True
            )

            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()

            logger.info(f"Uploaded JSON {filename} to folder {folder_id}")
            return file['id']
        except HttpError as e:
            logger.error(f"Error uploading JSON {filename}: {e}")
            return None

    def move_file(self, file_id: str, new_parent_id: str) -> bool:
        """Move a file to a different folder."""
        try:
            # Get current parents
            file = self.service.files().get(
                fileId=file_id,
                fields='parents'
            ).execute()

            previous_parents = ','.join(file.get('parents', []))

            # Move the file
            self.service.files().update(
                fileId=file_id,
                addParents=new_parent_id,
                removeParents=previous_parents,
                fields='id, parents'
            ).execute()

            logger.info(f"Moved file {file_id} to folder {new_parent_id}")
            return True
        except HttpError as e:
            logger.error(f"Error moving file {file_id}: {e}")
            return False

    def get_file_metadata(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file metadata."""
        try:
            file = self.service.files().get(
                fileId=file_id,
                fields='id, name, mimeType, size, createdTime, modifiedTime, parents'
            ).execute()
            return file
        except HttpError as e:
            logger.error(f"Error getting metadata for file {file_id}: {e}")
            return None

    def create_resumable_upload_session(self, filename: str, mime_type: str, folder_id: str) -> Dict[str, Any]:
        """Create a resumable upload session and return the session URI."""
        try:
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }

            media = MediaIoBaseUpload(
                io.BytesIO(b''),  # Empty initial upload
                mimetype=mime_type,
                resumable=True
            )

            request = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            )

            # Get the resumable URI
            response = None
            while response is None:
                status, response = request.next_chunk()

            return {
                'upload_url': request.uri,
                'file_id': response.get('id')
            }
        except HttpError as e:
            logger.error(f"Error creating resumable upload session: {e}")
            raise
