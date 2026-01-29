import os
import sqlite3
import io
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from PIL import Image
from PIL.ExifTags import TAGS

# --- CONFIGURATION ---
DB_PATH = r'F:\FamilyArchive\data\archive.db'
SERVICE_ACCOUNT_FILE = r'F:\FamilyArchive\config\service-account.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def update_schema():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Add EXIF columns if they don't exist
    columns = [
        ('date_taken', 'TEXT'),
        ('camera_make', 'TEXT'),
        ('camera_model', 'TEXT'),
        ('exposure_time', 'TEXT'),
        ('f_number', 'TEXT'),
        ('iso', 'INTEGER'),
        ('focal_length', 'TEXT'),
        ('gps_latitude', 'REAL'),
        ('gps_longitude', 'REAL')
    ]
    
    for col_name, col_type in columns:
        try:
            cursor.execute(f"ALTER TABLE media ADD COLUMN {col_name} {col_type}")
            print(f"Added column: {col_name}")
        except sqlite3.OperationalError:
            # Column already exists
            pass
            
    conn.commit()
    conn.close()

def get_exif_data(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        exif = img._getexif()
        if not exif:
            return {}
        
        data = {}
        for tag, value in exif.items():
            decoded = TAGS.get(tag, tag)
            data[decoded] = value
        return data
    except Exception as e:
        print(f"Error extracting EXIF: {e}")
        return {}

def format_date(date_str):
    if not date_str:
        return None
    try:
        # EXIF dates are usually 'YYYY:MM:DD HH:MM:SS'
        dt = datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
        return dt.isoformat()
    except:
        return None

def process_pending_exif():
    service = get_drive_service()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find items without date_taken (our marker for unprocessed EXIF)
    items = cursor.execute("SELECT drive_id, filename FROM media WHERE date_taken IS NULL").fetchall()
    
    print(f"Found {len(items)} items to process for EXIF data.")
    
    for drive_id, filename in items:
        print(f"Processing {filename}...")
        
        try:
            # Download small chunk for EXIF (usually at the start of the file)
            # For simplicity, we download the whole file here, but in production, 
            # a range request for the first 128KB is often enough for EXIF.
            request = service.files().get_media(fileId=drive_id)
            file_stream = io.BytesIO()
            downloader = MediaIoBaseDownload(file_stream, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            
            exif = get_exif_data(file_stream.getvalue())
            
            # Extract specific fields
            date_taken = format_date(exif.get('DateTimeOriginal') or exif.get('DateTime'))
            make = exif.get('Make')
            model = exif.get('Model')
            
            # Update database
            cursor.execute('''
                UPDATE media SET 
                    date_taken = ?, 
                    camera_make = ?, 
                    camera_model = ?
                WHERE drive_id = ?
            ''', (date_taken or 'unknown', make, model, drive_id))
            conn.commit()
            
        except Exception as e:
            print(f"Failed to process {filename}: {e}")
            # Mark as 'unknown' so we don't keep retrying failed files
            cursor.execute("UPDATE media SET date_taken = 'unknown' WHERE drive_id = ?", (drive_id,))
            conn.commit()

    conn.close()
    print("EXIF processing complete.")

if __name__ == "__main__":
    update_schema()
    process_pending_exif()
