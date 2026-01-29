import sqlite3
import shutil
import os
from datetime import datetime

# --- CONFIGURATION ---
DB_PATH = r'F:\FamilyArchive\data\archive.db'
BACKUP_DIR = r'F:\FamilyArchive\backups'

def backup_database():
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        print(f"Created backup directory: {BACKUP_DIR}")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"archive_backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    try:
        # Use shutil for a simple file copy backup
        shutil.copy2(DB_PATH, backup_path)
        print(f"Successfully backed up database to: {backup_path}")
        
        # Optional: Keep only the last 7 backups
        backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith('archive_backup_')])
        if len(backups) > 7:
            for old_backup in backups[:-7]:
                os.remove(os.path.join(BACKUP_DIR, old_backup))
                print(f"Removed old backup: {old_backup}")
                
    except Exception as e:
        print(f"Error during backup: {e}")

if __name__ == "__main__":
    backup_database()
