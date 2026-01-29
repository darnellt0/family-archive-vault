import json
import os
from pathlib import Path

BASE_DIR = Path(os.getenv("FAMILY_ARCHIVE_ROOT", r"F:\\FamilyArchive"))
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"
LOGS_DIR = BASE_DIR / "logs"
METADATA_DIR = BASE_DIR / "METADATA"
SIDECARE_DIR = METADATA_DIR / "sidecars_json"
THUMBNAIL_DIR = METADATA_DIR / "thumbnails"
VIDEO_POSTERS_DIR = METADATA_DIR / "video_posters"
TRANSCRIPTS_DIR = METADATA_DIR / "transcripts"

DB_PATH = Path(os.getenv("FAMILY_ARCHIVE_DB", str(DATA_DIR / "archive.db")))
SERVICE_ACCOUNT_FILE = Path(os.getenv("SERVICE_ACCOUNT_JSON_PATH", str(CONFIG_DIR / "service-account.json")))
DRIVE_ROOT_FOLDER_ID = os.getenv("DRIVE_ROOT_FOLDER_ID")

DRIVE_SCHEMA_CACHE = CONFIG_DIR / "drive_schema.json"

MAX_VIDEO_TRANSCRIBE_MINUTES = int(os.getenv("VIDEO_TRANSCRIBE_MAX_MINUTES", "8"))
PHASH_DUPLICATE_THRESHOLD = int(os.getenv("PHASH_DUPLICATE_THRESHOLD", "6"))
MIN_FREE_DISK_GB = int(os.getenv("MIN_FREE_DISK_GB", "30"))
MAX_BACKLOG_ITEMS = int(os.getenv("MAX_BACKLOG_ITEMS", "5000"))

for path in [DATA_DIR, CACHE_DIR, LOGS_DIR, METADATA_DIR, SIDECARE_DIR, THUMBNAIL_DIR, VIDEO_POSTERS_DIR, TRANSCRIPTS_DIR]:
    path.mkdir(parents=True, exist_ok=True)
