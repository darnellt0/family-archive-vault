#!/usr/bin/env python3
"""
R2 to Google Drive Sync Worker

Syncs photos and videos from Cloudflare R2 (uploaded via memorial site)
to Google Drive INBOX_UPLOADS for processing by the main worker.

Usage:
    python -m services.r2_sync           # Run continuously
    python -m services.r2_sync --once    # Run once and exit
"""
import argparse
import logging
import sys

from .sync_worker import R2SyncWorker
from .db import get_sync_db, get_sync_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="R2 to Google Drive Sync Worker")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--stats", action="store_true", help="Show sync statistics and exit")
    args = parser.parse_args()

    if args.stats:
        conn = get_sync_db()
        stats = get_sync_stats(conn)
        print(f"Sync Statistics:")
        print(f"  Total tracked: {stats['total']}")
        print(f"  Synced:        {stats['synced']}")
        print(f"  Errors:        {stats['errors']}")
        print(f"  In progress:   {stats['in_progress']}")
        return

    try:
        worker = R2SyncWorker()

        if args.once:
            logger.info("Running single sync cycle")
            worker.run_once()
        else:
            worker.run_forever()

    except KeyboardInterrupt:
        logger.info("Shutting down...")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
