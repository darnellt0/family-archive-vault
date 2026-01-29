"""Local folder polling module for syncing media from a local directory."""
import os
import shutil
import mimetypes
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from loguru import logger


# Supported media extensions
SUPPORTED_EXTENSIONS = {
    # Images
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.heic', '.heif',
    # Videos
    '.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg',
    # Audio
    '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.wma',
}


class LocalFolderPoller:
    """Monitors a local folder for new media files to import into the archive."""

    def __init__(self, sync_folder: str, cache_dir: str, processed_dir: str):
        """
        Initialize the local folder poller.

        Args:
            sync_folder: Path to the folder to monitor for new files
            cache_dir: Path to the processing cache directory
            processed_dir: Path to move processed files (or delete if configured)
        """
        self.sync_folder = Path(sync_folder)
        self.cache_dir = Path(cache_dir)
        self.processed_dir = Path(processed_dir)
        self._processed_files: set = set()

        # Ensure directories exist
        self.sync_folder.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        # Load previously processed files
        self._load_processed_manifest()

    def _load_processed_manifest(self):
        """Load the manifest of previously processed files."""
        manifest_path = self.processed_dir / ".processed_manifest"
        if manifest_path.exists():
            try:
                with open(manifest_path, 'r') as f:
                    self._processed_files = set(line.strip() for line in f if line.strip())
                logger.info(f"Loaded {len(self._processed_files)} previously processed files")
            except Exception as e:
                logger.warning(f"Could not load processed manifest: {e}")

    def _save_processed_manifest(self):
        """Save the manifest of processed files."""
        manifest_path = self.processed_dir / ".processed_manifest"
        try:
            with open(manifest_path, 'w') as f:
                for file_path in sorted(self._processed_files):
                    f.write(f"{file_path}\n")
        except Exception as e:
            logger.warning(f"Could not save processed manifest: {e}")

    def _is_supported_file(self, file_path: Path) -> bool:
        """Check if a file has a supported media extension."""
        return file_path.suffix.lower() in SUPPORTED_EXTENSIONS

    def _get_file_identifier(self, file_path: Path) -> str:
        """Generate a unique identifier for a file based on path and modification time."""
        stat = file_path.stat()
        return f"{file_path.name}|{stat.st_size}|{stat.st_mtime}"

    def _get_mime_type(self, file_path: Path) -> str:
        """Get the MIME type for a file."""
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if not mime_type:
            ext = file_path.suffix.lower()
            # Fallback mappings
            mime_map = {
                '.heic': 'image/heic',
                '.heif': 'image/heif',
                '.webp': 'image/webp',
                '.m4v': 'video/mp4',
                '.mkv': 'video/x-matroska',
            }
            mime_type = mime_map.get(ext, 'application/octet-stream')
        return mime_type

    def scan_for_new_files(self, batch_size: int = 50) -> List[Dict[str, Any]]:
        """
        Scan the sync folder for new media files.

        Args:
            batch_size: Maximum number of files to return in one batch

        Returns:
            List of file info dictionaries with path, name, size, mime_type
        """
        new_files = []

        if not self.sync_folder.exists():
            logger.warning(f"Sync folder does not exist: {self.sync_folder}")
            return new_files

        logger.info(f"Scanning local folder: {self.sync_folder}")

        # Walk through the directory recursively
        for root, dirs, files in os.walk(self.sync_folder):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for filename in files:
                # Skip hidden files
                if filename.startswith('.'):
                    continue

                file_path = Path(root) / filename

                # Check if supported
                if not self._is_supported_file(file_path):
                    continue

                # Check if already processed
                file_id = self._get_file_identifier(file_path)
                if file_id in self._processed_files:
                    continue

                # Check if file is still being written (wait for stable size)
                try:
                    size1 = file_path.stat().st_size
                    # File seems stable, add to list
                    new_files.append({
                        'path': str(file_path),
                        'name': filename,
                        'size': size1,
                        'mime_type': self._get_mime_type(file_path),
                        'file_id': file_id,
                        'relative_path': str(file_path.relative_to(self.sync_folder)),
                    })

                    if len(new_files) >= batch_size:
                        break

                except Exception as e:
                    logger.warning(f"Could not access file {file_path}: {e}")
                    continue

            if len(new_files) >= batch_size:
                break

        if new_files:
            logger.info(f"Found {len(new_files)} new files to process")
        else:
            logger.debug("No new files found")

        return new_files

    def prepare_file_for_processing(self, file_info: Dict[str, Any]) -> Optional[Path]:
        """
        Copy a file to the processing cache for safe processing.

        Args:
            file_info: File info dictionary from scan_for_new_files

        Returns:
            Path to the cached file, or None if copy failed
        """
        source_path = Path(file_info['path'])

        if not source_path.exists():
            logger.error(f"Source file no longer exists: {source_path}")
            return None

        # Create a unique processing directory for this file
        processing_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S") + "_" + file_info['name']
        processing_dir = self.cache_dir / "processing" / processing_id
        processing_dir.mkdir(parents=True, exist_ok=True)

        dest_path = processing_dir / file_info['name']

        try:
            # Copy the file to preserve the original
            shutil.copy2(source_path, dest_path)
            logger.info(f"Copied {source_path} to {dest_path}")
            return dest_path
        except Exception as e:
            logger.error(f"Failed to copy file {source_path}: {e}")
            return None

    def mark_file_processed(self, file_info: Dict[str, Any], delete_original: bool = False):
        """
        Mark a file as processed and optionally delete or move it.

        Args:
            file_info: File info dictionary from scan_for_new_files
            delete_original: If True, delete the original file; otherwise move to processed dir
        """
        source_path = Path(file_info['path'])
        file_id = file_info['file_id']

        # Add to processed set
        self._processed_files.add(file_id)
        self._save_processed_manifest()

        if not source_path.exists():
            logger.debug(f"File already moved/deleted: {source_path}")
            return

        try:
            if delete_original:
                source_path.unlink()
                logger.info(f"Deleted original file: {source_path}")
            else:
                # Move to processed directory, preserving subfolder structure
                relative_path = file_info.get('relative_path', file_info['name'])
                dest_path = self.processed_dir / relative_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)

                # Handle name conflicts
                if dest_path.exists():
                    base = dest_path.stem
                    suffix = dest_path.suffix
                    counter = 1
                    while dest_path.exists():
                        dest_path = dest_path.parent / f"{base}_{counter}{suffix}"
                        counter += 1

                shutil.move(str(source_path), str(dest_path))
                logger.info(f"Moved processed file to: {dest_path}")

        except Exception as e:
            logger.error(f"Failed to handle processed file {source_path}: {e}")

    def get_sync_status(self) -> Dict[str, Any]:
        """
        Get the current sync status.

        Returns:
            Dictionary with sync status information
        """
        pending_count = 0
        total_size = 0

        if self.sync_folder.exists():
            for root, dirs, files in os.walk(self.sync_folder):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for filename in files:
                    if filename.startswith('.'):
                        continue
                    file_path = Path(root) / filename
                    if self._is_supported_file(file_path):
                        file_id = self._get_file_identifier(file_path)
                        if file_id not in self._processed_files:
                            pending_count += 1
                            try:
                                total_size += file_path.stat().st_size
                            except:
                                pass

        return {
            'sync_folder': str(self.sync_folder),
            'pending_files': pending_count,
            'pending_size_mb': round(total_size / (1024 * 1024), 2),
            'processed_count': len(self._processed_files),
            'is_enabled': True,
        }


def create_local_file_info(file_path: Path, file_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a file info dictionary compatible with the asset processor.

    This mimics the structure returned by DriveClient.list_files() so
    the same processing pipeline can be used for both sources.

    Args:
        file_path: Path to the local file
        file_info: Additional file info from the poller

    Returns:
        Dictionary with file info compatible with process_asset
    """
    return {
        'id': f"local_{file_info['file_id'][:32]}",  # Pseudo-ID for local files
        'name': file_info['name'],
        'mimeType': file_info['mime_type'],
        'size': str(file_info['size']),
        'local_path': str(file_path),
        'source': 'local_folder',
        'original_local_path': file_info['path'],
    }
