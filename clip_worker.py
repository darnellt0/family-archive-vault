import os
import sqlite3
import io
import torch
import numpy as np
from PIL import Image
from sentence_transformers import SentenceTransformer
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

def process_clip_embeddings():
    # 1. Load CLIP (Load-Process-Unload pattern)
    print("Loading CLIP model (clip-ViT-B-32)...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer('clip-ViT-B-32', device=device)
    
    service = get_drive_service()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find items without CLIP embeddings
    items = cursor.execute('''
        SELECT drive_id, filename FROM media 
        WHERE clip_embedding IS NULL
        AND (filename LIKE '%.jpg' OR filename LIKE '%.jpeg' OR filename LIKE '%.png')
    ''').fetchall()
    
    print(f"Found {len(items)} items to process for CLIP embeddings.")
    
    for drive_id, filename in items:
        print(f"Generating CLIP embedding for {filename}...")
        
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
            
            # Generate embedding
            embedding = model.encode(raw_image)
            
            # Store as BLOB
            embedding_blob = embedding.astype(np.float32).tobytes()
            
            # Update database
            cursor.execute("UPDATE media SET clip_embedding = ? WHERE drive_id = ?", (embedding_blob, drive_id))
            conn.commit()
            
        except Exception as e:
            print(f"Failed to process {filename}: {e}")
            # Mark as 'failed' (using a small dummy blob) to avoid retrying
            cursor.execute("UPDATE media SET clip_embedding = ? WHERE drive_id = ?", (b'failed', drive_id))
            conn.commit()

    conn.close()
    print("CLIP processing complete. Unloading model...")
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

if __name__ == "__main__":
    process_clip_embeddings()
