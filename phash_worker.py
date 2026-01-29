import os
import sqlite3
import io
from PIL import Image
import imagehash
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- CONFIGURATION ---
DB_PATH = r'F:\FamilyArchive\data\archive.db'
SERVICE_ACCOUNT_FILE = r'F:\FamilyArchive\config\service-account.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def process_phash():
    service = get_drive_service()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find items without pHash
    items = cursor.execute('''
        SELECT drive_id, filename FROM media 
        WHERE phash IS NULL
        AND (filename LIKE '%.jpg' OR filename LIKE '%.jpeg' OR filename LIKE '%.png')
    ''').fetchall()
    
    print(f"Found {len(items)} items to process for pHash.")
    
    for drive_id, filename in items:
        print(f"Generating pHash for {filename}...")
        
        try:
            # Download image
            request = service.files().get_media(fileId=drive_id)
            file_stream = io.BytesIO()
            downloader = MediaIoBaseDownload(file_stream, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            
            # Process image
            img = Image.open(io.BytesIO(file_stream.getvalue()))
            
            # Generate pHash
            hash_val = imagehash.phash(img)
            
            # Update database
            cursor.execute("UPDATE media SET phash = ? WHERE drive_id = ?", (str(hash_val), drive_id))
            conn.commit()
            
        except Exception as e:
            print(f"Failed to process {filename}: {e}")
            # Mark as 'failed' to avoid retrying
            cursor.execute("UPDATE media SET phash = 'failed' WHERE drive_id = ?", (drive_id,))
            conn.commit()

    conn.close()
    print("pHash processing complete.")

if __name__ == "__main__":
    process_phash()
