"""Configuration management for Family Archive Vault."""
import os
from pathlib import Path
from typing import Dict, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='allow'
    )

    # Google Drive
    drive_root_folder_id: str
    # Path to service account JSON file (optional if SERVICE_ACCOUNT_JSON env var is set)
    service_account_json_path: Optional[str] = None

    # Local Storage
    local_root: str = Field(default="F:\\FamilyArchive")
    local_cache: Optional[str] = None
    local_db_path: Optional[str] = None
    local_logs: Optional[str] = None

    # Intake Web App
    intake_host: str = "0.0.0.0"
    intake_port: int = 8000
    intake_secret_key: str
    upload_max_size_mb: int = 5000
    upload_chunk_size_mb: int = 10
    rate_limit_per_hour: int = 100

    # Worker
    worker_poll_interval_seconds: int = 300
    worker_batch_size: int = 10
    use_gpu: bool = True
    gpu_device_id: int = 0

    # AI Feature Flags
    enable_face_detection: bool = True
    enable_captions: bool = True
    enable_clip_embeddings: bool = True
    enable_whisper: bool = True

    # Whisper
    video_transcribe_max_minutes: int = 8
    whisper_model: str = "base"
    whisper_device: str = "cuda"

    # Face Detection
    face_detection_model: str = "buffalo_l"
    face_min_confidence: float = 0.6
    face_cluster_min_samples: int = 3

    # Image Processing
    phash_duplicate_threshold: int = 5
    thumbnail_size: int = 800
    video_poster_time_seconds: int = 1

    # Rosetta Stone
    rosetta_generation_time: str = "03:00"
    rosetta_timezone: str = "America/New_York"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Auto-populate derived paths if not set
        if not self.local_cache:
            self.local_cache = os.path.join(self.local_root, "cache")
        if not self.local_db_path:
            self.local_db_path = os.path.join(self.local_root, "db", "archive.db")
        if not self.local_logs:
            self.local_logs = os.path.join(self.local_root, "logs")

    def get_contributor_tokens(self) -> Dict[str, str]:
        """Extract contributor token mappings from environment."""
        tokens = {}
        for key, value in os.environ.items():
            if key.startswith("TOKEN_"):
                token_name = key[6:]  # Remove "TOKEN_" prefix
                tokens[token_name] = value
        return tokens

    def get_local_path(self, *parts: str) -> Path:
        """Get a local path relative to LOCAL_ROOT."""
        return Path(self.local_root) / Path(*parts)

    def ensure_local_dirs(self):
        """Create necessary local directories."""
        dirs = [
            self.local_cache,
            os.path.dirname(self.local_db_path),
            self.local_logs,
            os.path.join(self.local_cache, "thumbnails"),
            os.path.join(self.local_cache, "video_posters"),
            os.path.join(self.local_cache, "sidecars"),
        ]
        for dir_path in dirs:
            Path(dir_path).mkdir(parents=True, exist_ok=True)


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
