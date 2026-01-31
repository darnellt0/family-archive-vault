import os
from pathlib import Path

# Base paths (reuse from worker config)
BASE_DIR = Path(os.getenv("FAMILY_ARCHIVE_ROOT", r"F:\FamilyArchive"))
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"

# R2 Configuration
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "family-archive-uploads")

# Google Drive Configuration
# Supports two modes:
# 1. SERVICE_ACCOUNT_JSON_PATH: Path to service account JSON file (local)
# 2. SERVICE_ACCOUNT_JSON: JSON content as string (Railway/cloud deployments)
SERVICE_ACCOUNT_FILE = Path(os.getenv("SERVICE_ACCOUNT_JSON_PATH", str(CONFIG_DIR / "service-account.json")))
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON", "")  # JSON content for cloud deploy
DRIVE_ROOT_FOLDER_ID = os.getenv("DRIVE_ROOT_FOLDER_ID")
DRIVE_SCHEMA_CACHE = CONFIG_DIR / "drive_schema.json"

# Sync Configuration
R2_SYNC_POLL_INTERVAL = int(os.getenv("R2_SYNC_POLL_INTERVAL", "300"))  # 5 minutes
R2_SYNC_BATCH_SIZE = int(os.getenv("R2_SYNC_BATCH_SIZE", "20"))
R2_SYNC_DELETE_AFTER = os.getenv("R2_SYNC_DELETE_AFTER", "true").lower() == "true"
R2_SYNC_DB_PATH = Path(os.getenv("R2_SYNC_DB_PATH", str(DATA_DIR / "r2_sync.db")))

# Prefixes to exclude from sync (manifests, etc.)
R2_EXCLUDE_PREFIXES = ["_manifests/", "_synced/"]

# Temp directory for downloads
R2_SYNC_TEMP_DIR = CACHE_DIR / "r2_sync"

# Ensure directories exist
for path in [DATA_DIR, CACHE_DIR, R2_SYNC_TEMP_DIR]:
    path.mkdir(parents=True, exist_ok=True)
