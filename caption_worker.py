import os
import sqlite3
import io
import torch
from PIL import Image
from transformers import BlipProcessor, BlipForConditionalGeneration
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

def update_schema():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Add caption column if it doesn't exist
    try:
        cursor.execute("ALTER TABLE media ADD COLUMN ai_caption TEXT")
        print("Added column: ai_caption")
    except sqlite3.OperationalError:
        # Column already exists
        pass
            
    conn.commit()
    conn.close()

def process_captions():
    # 1. Load BLIP-base (Load-Process-Unload pattern)
    print("Loading BLIP-base model...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
    model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base").to(device)
    
    service = get_drive_service()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find items without AI captions
    items = cursor.execute('''
        SELECT drive_id, filename FROM media 
        WHERE ai_caption IS NULL
        AND (filename LIKE '%.jpg' OR filename LIKE '%.jpeg' OR filename LIKE '%.png')
    ''').fetchall()
    
    print(f"Found {len(items)} items to process for captions.")
    
    for drive_id, filename in items:
        print(f"Generating caption for {filename}...")
        
        try:
            # Download image
            request = service.files().get_media(fileId=drive_id)
            file_stream = io.BytesIO()
            downloader = MediaIoBaseDownload(file_stream, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            
            # Process image
            raw_image = Image.open(io.BytesIO(file_stream.getvalue())).convert('RGB')
            
            # Generate caption
            inputs = processor(raw_image, return_tensors="pt").to(device)
            out = model.generate(**inputs)
            caption = processor.decode(out[0], skip_special_tokens=True)
            
            print(f"Caption: {caption}")
            
            # Update database
            cursor.execute("UPDATE media SET ai_caption = ? WHERE drive_id = ?", (caption, drive_id))
            conn.commit()
            
        except Exception as e:
            print(f"Failed to process {filename}: {e}")
            # Mark as 'unknown' to avoid retrying failed files
            cursor.execute("UPDATE media SET ai_caption = 'unknown' WHERE drive_id = ?", (drive_id,))
            conn.commit()

    conn.close()
    print("Captioning complete. Unloading model...")
    # Explicitly clear memory
    del model
    del processor
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

if __name__ == "__main__":
    update_schema()
    process_captions()
