"""Main worker for processing media files."""
import os
import sys
import time
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.config import get_settings
from shared.drive_client import DriveClient
from shared.database import DatabaseManager
from shared.models import AssetSidecar, AssetType, AssetStatus, SyncSource

from worker.local_folder_poller import LocalFolderPoller, create_local_file_info

from worker.processors.metadata_extractor import MetadataExtractor
from worker.processors.media_processor import MediaProcessor
from worker.processors.face_detector import FaceDetector
from worker.processors.captioner import ImageCaptioner
from worker.processors.clip_embedder import CLIPEmbedder
from worker.processors.transcriber import AudioTranscriber


class AssetProcessor:
    """Process individual assets through the AI pipeline."""

    def __init__(self, settings, db_manager: DatabaseManager, drive_client: DriveClient):
        self.settings = settings
        self.db = db_manager
        self.drive = drive_client
        self.cache_dir = Path(settings.local_cache)

    def process_asset(self, drive_file: Dict[str, Any], contributor_token: str, batch_id: str, sync_source: SyncSource = SyncSource.DRIVE_INBOX) -> Optional[str]:
        """Process a single asset through the entire pipeline."""
        file_id = drive_file['id']
        filename = drive_file['name']
        is_local = drive_file.get('source') == 'local_folder'

        logger.info(f"Processing asset: {filename} ({file_id}) [source: {sync_source.value}]")

        try:
            # Determine asset type
            mime_type = drive_file.get('mimeType', '')
            asset_type = self._determine_asset_type(mime_type)

            if asset_type is None:
                logger.warning(f"Unsupported file type: {mime_type}")
                return None

            # Get file to cache
            if is_local:
                # For local files, the path is already prepared
                local_path = Path(drive_file['local_path'])
                if not local_path.exists():
                    raise Exception(f"Local file not found: {local_path}")
            else:
                # Download file from Drive to cache
                local_path = self.cache_dir / "processing" / file_id / filename
                if not self.drive.download_file(file_id, local_path):
                    raise Exception("Failed to download file")

            # Initialize sidecar
            sidecar = AssetSidecar(
                drive_file_id=file_id if not is_local else None,
                original_filename=filename,
                contributor_token=contributor_token,
                batch_id=batch_id,
                upload_timestamp=datetime.utcnow(),
                asset_type=asset_type,
                mime_type=mime_type,
                file_size_bytes=int(drive_file.get('size', 0)),
                drive_path=f"PROCESSING/{filename}" if not is_local else "",
                status=AssetStatus.PROCESSING,
                sync_source=sync_source,
                local_source_path=drive_file.get('original_local_path') if is_local else None
            )

            # PHASE 1: Fast metadata extraction (no GPU)
            logger.info(f"Phase 1: Extracting metadata for {filename}")
            self._extract_metadata(local_path, sidecar)

            # Create thumbnail/poster
            self._create_preview(local_path, sidecar)

            # Check for duplicates
            duplicate_of = self._check_duplicates(sidecar)
            if duplicate_of:
                sidecar.duplicate_of = duplicate_of
                sidecar.is_master = False
                sidecar.status = AssetStatus.NEEDS_REVIEW
                logger.info(f"Possible duplicate detected: {filename}")

            # PHASE 2: AI Processing (GPU - serial model loading)
            if asset_type == AssetType.IMAGE:
                self._process_image_ai(local_path, sidecar)
            elif asset_type == AssetType.VIDEO:
                self._process_video_ai(local_path, sidecar)

            # Update status
            if sidecar.status == AssetStatus.PROCESSING:
                sidecar.status = AssetStatus.NEEDS_REVIEW

            # Save sidecar
            self._save_sidecar(sidecar)

            # Update database
            self._update_database(sidecar)

            # Move in Drive based on status
            self._route_asset(sidecar)

            logger.info(f"Successfully processed {filename}")
            return sidecar.asset_id

        except Exception as e:
            logger.error(f"Error processing {filename}: {e}")
            # Log error but don't crash
            return None

    def _determine_asset_type(self, mime_type: str) -> Optional[AssetType]:
        """Determine asset type from MIME type."""
        if mime_type.startswith('image/'):
            return AssetType.IMAGE
        elif mime_type.startswith('video/'):
            return AssetType.VIDEO
        elif mime_type.startswith('audio/'):
            return AssetType.AUDIO
        return None

    def _extract_metadata(self, local_path: Path, sidecar: AssetSidecar):
        """Extract fast metadata (SHA256, EXIF, phash)."""
        # Compute hashes
        sidecar.sha256 = MetadataExtractor.compute_sha256(local_path)

        if sidecar.asset_type == AssetType.IMAGE:
            # Perceptual hash for images
            sidecar.phash = MetadataExtractor.compute_phash(local_path)

            # EXIF data
            exif = MetadataExtractor.extract_exif(local_path)
            if exif:
                sidecar.exif_data = exif
                sidecar.exif_date = exif.get('date_taken')

            # Estimate decade
            sidecar.decade = MetadataExtractor.estimate_decade(
                sidecar.exif_date,
                sidecar.original_filename
            )

        elif sidecar.asset_type == AssetType.VIDEO:
            # Video metadata
            video_meta = MetadataExtractor.extract_video_metadata(local_path)
            if video_meta:
                sidecar.video_metadata = video_meta

    def _create_preview(self, local_path: Path, sidecar: AssetSidecar):
        """Create thumbnail or video poster."""
        preview_dir = self.cache_dir / "thumbnails"
        preview_path = preview_dir / f"{sidecar.asset_id}.jpg"

        if sidecar.asset_type == AssetType.IMAGE:
            if MediaProcessor.create_thumbnail(local_path, preview_path, self.settings.thumbnail_size):
                sidecar.thumbnail_path = str(preview_path)

        elif sidecar.asset_type == AssetType.VIDEO:
            if MediaProcessor.create_video_poster(
                local_path,
                preview_path,
                self.settings.video_poster_time_seconds
            ):
                sidecar.thumbnail_path = str(preview_path)

    def _check_duplicates(self, sidecar: AssetSidecar) -> Optional[str]:
        """Check for duplicate assets."""
        # Check exact duplicates by SHA256
        session = self.db.get_session()
        try:
            from shared.database import Asset
            existing = session.query(Asset).filter_by(sha256=sidecar.sha256).first()
            if existing and existing.asset_id != sidecar.asset_id:
                return existing.asset_id

            # Check near duplicates by phash (images only)
            if sidecar.phash and sidecar.asset_type == AssetType.IMAGE:
                import imagehash
                current_hash = imagehash.hex_to_hash(sidecar.phash)

                similar_assets = session.query(Asset).filter(
                    Asset.phash.isnot(None),
                    Asset.asset_type == 'image'
                ).all()

                for asset in similar_assets:
                    if asset.phash and asset.asset_id != sidecar.asset_id:
                        other_hash = imagehash.hex_to_hash(asset.phash)
                        distance = current_hash - other_hash

                        if distance <= self.settings.phash_duplicate_threshold:
                            return asset.asset_id

        finally:
            session.close()

        return None

    def _process_image_ai(self, local_path: Path, sidecar: AssetSidecar):
        """Process image with AI models (serial loading)."""
        # Face detection
        if self.settings.enable_face_detection:
            try:
                logger.info("Loading face detection model...")
                with FaceDetector(
                    self.settings.face_detection_model,
                    self.settings.face_min_confidence,
                    self.settings.use_gpu
                ) as detector:
                    faces = detector.process(local_path)
                    sidecar.faces = faces
                logger.info("Face detection complete, model unloaded")
            except Exception as e:
                logger.error(f"Face detection failed: {e}")
                sidecar.processing_errors.append(f"Face detection: {str(e)}")

        # Image captioning
        if self.settings.enable_captions:
            try:
                logger.info("Loading caption model...")
                with ImageCaptioner(use_gpu=self.settings.use_gpu) as captioner:
                    caption = captioner.process(local_path)
                    sidecar.caption = caption
                logger.info("Captioning complete, model unloaded")
            except Exception as e:
                logger.error(f"Captioning failed: {e}")
                sidecar.processing_errors.append(f"Captioning: {str(e)}")

        # CLIP embeddings
        if self.settings.enable_clip_embeddings:
            try:
                logger.info("Loading CLIP model...")
                with CLIPEmbedder(use_gpu=self.settings.use_gpu) as embedder:
                    embedding = embedder.process(local_path)
                    if embedding:
                        embedding_id = str(uuid.uuid4())
                        sidecar.clip_embedding_id = embedding_id
                        # Store embedding in database
                        self._store_clip_embedding(sidecar.asset_id, embedding_id, embedding)
                logger.info("CLIP embedding complete, model unloaded")
            except Exception as e:
                logger.error(f"CLIP embedding failed: {e}")
                sidecar.processing_errors.append(f"CLIP: {str(e)}")

    def _process_video_ai(self, local_path: Path, sidecar: AssetSidecar):
        """Process video with AI models."""
        # Transcription (if enabled and within duration limit)
        if self.settings.enable_whisper:
            duration = sidecar.video_metadata.duration_seconds if sidecar.video_metadata else 0
            max_duration = self.settings.video_transcribe_max_minutes * 60

            if duration <= max_duration:
                try:
                    logger.info("Loading Whisper model...")
                    with AudioTranscriber(
                        self.settings.whisper_model,
                        self.settings.whisper_device,
                        self.settings.use_gpu
                    ) as transcriber:
                        # Extract audio
                        audio_path = local_path.parent / f"{local_path.stem}.mp3"
                        if transcriber.extract_audio_from_video(local_path, audio_path):
                            transcript = transcriber.process(audio_path)
                            sidecar.transcript = transcript
                            audio_path.unlink()  # Clean up
                    logger.info("Transcription complete, model unloaded")
                except Exception as e:
                    logger.error(f"Transcription failed: {e}")
                    sidecar.processing_errors.append(f"Transcription: {str(e)}")
            else:
                logger.info(f"Video duration {duration}s exceeds limit {max_duration}s, skipping transcription")

    def _store_clip_embedding(self, asset_id: str, embedding_id: str, embedding: list):
        """Store CLIP embedding in database."""
        session = self.db.get_session()
        try:
            from shared.database import ClipEmbedding
            clip_emb = ClipEmbedding(
                embedding_id=embedding_id,
                asset_id=asset_id,
                embedding=embedding
            )
            session.add(clip_emb)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Error storing CLIP embedding: {e}")
        finally:
            session.close()

    def _save_sidecar(self, sidecar: AssetSidecar):
        """Save sidecar JSON to local cache and Drive."""
        # Save locally
        local_sidecar_dir = self.cache_dir / "sidecars"
        local_sidecar_dir.mkdir(parents=True, exist_ok=True)
        local_sidecar_path = local_sidecar_dir / f"{sidecar.asset_id}.json"

        with open(local_sidecar_path, 'w') as f:
            json.dump(sidecar.dict(), f, indent=2, default=str)

        # Upload to Drive
        try:
            metadata_folder_id = self.drive.get_or_create_folder("METADATA")
            sidecars_folder_id = self.drive.get_or_create_folder("sidecars_json", metadata_folder_id)
            self.drive.upload_json(sidecar.dict(), f"{sidecar.asset_id}.json", sidecars_folder_id)
        except Exception as e:
            logger.error(f"Error uploading sidecar to Drive: {e}")

    def _update_database(self, sidecar: AssetSidecar):
        """Update database with asset information."""
        try:
            # Upsert asset
            asset_dict = sidecar.dict()
            self.db.upsert_asset(asset_dict)

            # Upsert faces
            if sidecar.faces:
                self.db.upsert_faces(sidecar.asset_id, sidecar.faces)

        except Exception as e:
            logger.error(f"Error updating database: {e}")

    def _route_asset(self, sidecar: AssetSidecar):
        """Route asset in Drive based on status."""
        # Skip Drive routing for local folder imports
        if sidecar.sync_source == SyncSource.LOCAL_FOLDER:
            logger.info(f"Skipping Drive routing for local file: {sidecar.original_filename}")
            return

        if not sidecar.drive_file_id:
            logger.warning(f"No drive_file_id for asset: {sidecar.original_filename}")
            return

        try:
            if sidecar.duplicate_of:
                # Move to Possible_Duplicates
                holding_id = self.drive.get_or_create_folder("HOLDING")
                dupes_id = self.drive.get_or_create_folder("Possible_Duplicates", holding_id)
                self.drive.move_file(sidecar.drive_file_id, dupes_id)
                sidecar.drive_path = f"HOLDING/Possible_Duplicates/{sidecar.original_filename}"

            elif sidecar.status == AssetStatus.NEEDS_REVIEW:
                # Move to Needs_Review
                holding_id = self.drive.get_or_create_folder("HOLDING")
                review_id = self.drive.get_or_create_folder("Needs_Review", holding_id)
                self.drive.move_file(sidecar.drive_file_id, review_id)
                sidecar.drive_path = f"HOLDING/Needs_Review/{sidecar.original_filename}"

        except Exception as e:
            logger.error(f"Error routing asset in Drive: {e}")


class Worker:
    """Main worker loop."""

    def __init__(self):
        self.settings = get_settings()
        self.settings.ensure_local_dirs()

        # Setup logging
        logger.remove()
        logger.add(
            sys.stderr,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> | <level>{message}</level>",
            level="INFO"
        )
        logger.add(
            Path(self.settings.local_logs) / "worker_{time}.log",
            rotation="1 day",
            retention="30 days",
            level="DEBUG"
        )

        # Initialize clients
        self.drive = DriveClient(
            self.settings.service_account_json_path,
            self.settings.drive_root_folder_id
        )
        self.db = DatabaseManager(self.settings.local_db_path)
        self.db.init_db()

        self.processor = AssetProcessor(self.settings, self.db, self.drive)

        # Initialize local folder poller if enabled
        self.local_poller = None
        if self.settings.enable_local_folder_sync and self.settings.local_sync_folder:
            self.local_poller = LocalFolderPoller(
                sync_folder=self.settings.local_sync_folder,
                cache_dir=self.settings.local_cache,
                processed_dir=os.path.join(self.settings.local_cache, "local_sync_processed")
            )
            logger.info(f"Local folder sync enabled: {self.settings.local_sync_folder}")

    def run(self):
        """Main worker loop."""
        logger.info("Worker started")

        # Initialize Drive folder structure
        contributor_folders = list(self.settings.get_contributor_tokens().values())
        self.drive.setup_folder_structure(contributor_folders)

        # Track last local sync time
        last_local_sync = 0

        while True:
            try:
                # Process local folder if enabled
                if self.local_poller:
                    current_time = time.time()
                    if current_time - last_local_sync >= self.settings.local_sync_poll_interval_seconds:
                        self._process_local_folder()
                        last_local_sync = current_time

                # Process Drive inbox
                self._process_inbox()
                time.sleep(self.settings.worker_poll_interval_seconds)
            except KeyboardInterrupt:
                logger.info("Worker stopped by user")
                break
            except Exception as e:
                logger.error(f"Worker error: {e}")
                time.sleep(60)  # Wait before retrying

    def _process_inbox(self):
        """Process files in INBOX."""
        logger.info("Checking for new files in INBOX...")

        # Get contributor folders
        contributor_tokens = self.settings.get_contributor_tokens()

        for token, folder_name in contributor_tokens.items():
            inbox_id = self.drive.get_or_create_folder("INBOX_UPLOADS")
            contributor_folder_id = self.drive.get_or_create_folder(folder_name, inbox_id)

            # List files
            files = self.drive.list_files(contributor_folder_id)

            if not files:
                continue

            logger.info(f"Found {len(files)} files in {folder_name}")

            # Process batch
            for file in files[:self.settings.worker_batch_size]:
                # Move to PROCESSING first
                processing_id = self.drive.get_or_create_folder("PROCESSING")
                self.drive.move_file(file['id'], processing_id)

                # Process asset
                batch_id = f"auto_{datetime.utcnow().strftime('%Y%m%d')}"
                self.processor.process_asset(file, token, batch_id, SyncSource.DRIVE_INBOX)

    def _process_local_folder(self):
        """Process files from the local sync folder."""
        if not self.local_poller:
            return

        logger.info("Checking for new files in local sync folder...")

        # Scan for new files
        new_files = self.local_poller.scan_for_new_files(
            batch_size=self.settings.local_sync_batch_size
        )

        if not new_files:
            return

        logger.info(f"Found {len(new_files)} new local files to process")

        # Process each file
        batch_id = f"local_{datetime.utcnow().strftime('%Y%m%d')}"
        contributor_token = self.settings.local_folder_contributor_token

        for file_info in new_files:
            try:
                # Prepare file for processing (copy to cache)
                cached_path = self.local_poller.prepare_file_for_processing(file_info)

                if not cached_path:
                    logger.error(f"Failed to prepare file: {file_info['name']}")
                    continue

                # Create file info compatible with process_asset
                process_file_info = create_local_file_info(cached_path, file_info)

                # Process the asset
                asset_id = self.processor.process_asset(
                    process_file_info,
                    contributor_token,
                    batch_id,
                    SyncSource.LOCAL_FOLDER
                )

                if asset_id:
                    # Mark as processed and optionally delete/move original
                    self.local_poller.mark_file_processed(
                        file_info,
                        delete_original=self.settings.local_sync_delete_after_import
                    )
                    logger.info(f"Successfully processed local file: {file_info['name']}")
                else:
                    logger.warning(f"Failed to process local file: {file_info['name']}")

            except Exception as e:
                logger.error(f"Error processing local file {file_info['name']}: {e}")

    def get_local_sync_status(self) -> Optional[Dict[str, Any]]:
        """Get the current local sync status."""
        if self.local_poller:
            return self.local_poller.get_sync_status()
        return None


def main():
    """Entry point for worker."""
    worker = Worker()
    worker.run()


if __name__ == "__main__":
    main()
