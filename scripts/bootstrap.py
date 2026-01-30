"""Bootstrap script to initialize the Family Archive Vault system."""
import sys
import os
from pathlib import Path
import qrcode
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.config import get_settings
from shared.drive_client import DriveClient
from shared.database import DatabaseManager


def print_banner():
    """Print welcome banner."""
    banner = """
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║           FAMILY ARCHIVE VAULT - BOOTSTRAP                ║
║                                                           ║
║  Initializing your family's photo preservation system    ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
"""
    print(banner)


def verify_environment():
    """Verify required environment variables."""
    logger.info("Verifying environment configuration...")

    try:
        settings = get_settings()

        # Check critical settings
        if not settings.drive_root_folder_id:
            raise ValueError("DRIVE_ROOT_FOLDER_ID not set")

        if not settings.service_account_json_path:
            raise ValueError("SERVICE_ACCOUNT_JSON_PATH not set")

        if not Path(settings.service_account_json_path).exists():
            raise FileNotFoundError(f"Service account JSON not found: {settings.service_account_json_path}")

        logger.info("✓ Environment configuration valid")
        return settings

    except Exception as e:
        logger.error(f"✗ Environment verification failed: {e}")
        logger.info("\nPlease ensure you have:")
        logger.info("1. Created a .env file from .env.example")
        logger.info("2. Set DRIVE_ROOT_FOLDER_ID to your Drive folder ID")
        logger.info("3. Set SERVICE_ACCOUNT_JSON_PATH to your service account key file")
        logger.info("4. Configured contributor tokens (TOKEN_* variables)")
        sys.exit(1)


def initialize_local_dirs(settings):
    """Create local directory structure."""
    logger.info("Creating local directory structure...")

    try:
        settings.ensure_local_dirs()

        dirs = [
            settings.local_root,
            settings.local_cache,
            os.path.dirname(settings.local_db_path),
            settings.local_logs,
            os.path.join(settings.local_cache, "thumbnails"),
            os.path.join(settings.local_cache, "video_posters"),
            os.path.join(settings.local_cache, "sidecars"),
            os.path.join(settings.local_cache, "processing"),
            os.path.join(settings.local_cache, "upload_chunks"),
            os.path.join(settings.local_cache, "rosetta_site"),
        ]

        for dir_path in dirs:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
            logger.info(f"  ✓ {dir_path}")

        logger.info("✓ Local directories created")

    except Exception as e:
        logger.error(f"✗ Failed to create local directories: {e}")
        sys.exit(1)


def initialize_database(settings):
    """Initialize SQLite database."""
    logger.info("Initializing database...")

    try:
        db = DatabaseManager(settings.local_db_path)
        db.init_db()
        logger.info(f"✓ Database initialized at {settings.local_db_path}")
        return db

    except Exception as e:
        logger.error(f"✗ Failed to initialize database: {e}")
        sys.exit(1)


def connect_to_drive(settings):
    """Connect to Google Drive and verify access."""
    logger.info("Connecting to Google Drive...")

    try:
        drive_client = DriveClient(
            settings.service_account_json_path,
            settings.drive_root_folder_id
        )

        # Get service account email
        sa_email = drive_client.get_service_account_email()
        logger.info(f"✓ Connected as: {sa_email}")

        # Test root folder access
        try:
            metadata = drive_client.service.files().get(
                fileId=settings.drive_root_folder_id,
                fields='id, name, capabilities'
            ).execute()
            logger.info(f"✓ Root folder accessible: {metadata['name']}")
        except Exception as e:
            logger.error(f"✗ Cannot access root folder: {e}")
            logger.info("\n⚠️  IMPORTANT: Share your Drive folder with the service account!")
            logger.info(f"   Share the folder with: {sa_email}")
            logger.info(f"   Give 'Editor' permissions")
            sys.exit(1)

        return drive_client

    except Exception as e:
        logger.error(f"✗ Failed to connect to Drive: {e}")
        sys.exit(1)


def setup_drive_folders(drive_client, settings):
    """Create Drive folder structure."""
    logger.info("Setting up Drive folder structure...")

    try:
        contributor_folders = list(settings.get_contributor_tokens().values())
        folder_ids = drive_client.setup_folder_structure(contributor_folders)

        logger.info(f"✓ Created {len(folder_ids)} folders in Drive")
        logger.info("\nFolder structure:")
        for path in sorted(folder_ids.keys()):
            if not path.startswith("ARCHIVE/"):  # Only show top-level structure
                logger.info(f"  {path}")

        return folder_ids

    except Exception as e:
        logger.error(f"✗ Failed to setup Drive folders: {e}")
        sys.exit(1)


def generate_upload_links(settings, base_url: str = "http://localhost:8000"):
    """Generate upload links and QR codes for contributors."""
    logger.info("\n" + "="*60)
    logger.info("CONTRIBUTOR UPLOAD LINKS")
    logger.info("="*60)

    contributor_tokens = settings.get_contributor_tokens()

    if not contributor_tokens:
        logger.warning("⚠️  No contributor tokens configured!")
        logger.info("Add TOKEN_* variables to your .env file")
        return

    qr_dir = Path(settings.local_root) / "qr_codes"
    qr_dir.mkdir(exist_ok=True)

    for token, folder_name in contributor_tokens.items():
        upload_url = f"{base_url}/u/{token}"

        logger.info(f"\n{folder_name}:")
        logger.info(f"  URL: {upload_url}")
        logger.info(f"  Token: {token}")

        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(upload_url)
        qr.make(fit=True)

        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_path = qr_dir / f"upload_qr_{token}.png"
        qr_img.save(qr_path)

        logger.info(f"  QR Code: {qr_path}")

    logger.info("\n" + "="*60)
    logger.info("📱 Send these links to family members for easy uploading!")
    logger.info("="*60)


def print_next_steps(settings):
    """Print next steps for the user."""
    logger.info("\n" + "="*60)
    logger.info("🎉 BOOTSTRAP COMPLETE!")
    logger.info("="*60)

    logger.info("\nNext Steps:")
    logger.info("\n1. START THE INTAKE WEB APP:")
    logger.info("   python -m intake_webapp.main")
    logger.info("   or")
    logger.info("   uvicorn intake_webapp.main:app --host 0.0.0.0 --port 8000")

    logger.info("\n2. START THE WORKER (in another terminal):")
    logger.info("   python -m worker.main")

    logger.info("\n3. OPEN THE CURATOR DASHBOARD (in another terminal):")
    logger.info("   streamlit run curator/main.py")

    logger.info("\n4. GENERATE ROSETTA STONE SITE (nightly or on-demand):")
    logger.info("   python -m rosetta.main")

    logger.info("\n5. SHARE UPLOAD LINKS:")
    logger.info(f"   QR codes saved to: {settings.local_root}/qr_codes/")

    logger.info("\n" + "="*60)


def main():
    """Main bootstrap process."""
    print_banner()

    # Step 1: Verify environment
    settings = verify_environment()

    # Step 2: Create local directories
    initialize_local_dirs(settings)

    # Step 3: Initialize database
    initialize_database(settings)

    # Step 4: Connect to Drive
    drive_client = connect_to_drive(settings)

    # Step 5: Setup Drive folders
    setup_drive_folders(drive_client, settings)

    # Step 6: Generate upload links
    generate_upload_links(settings)

    # Step 7: Print next steps
    print_next_steps(settings)


if __name__ == "__main__":
    main()
