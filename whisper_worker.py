import os
import sqlite3
import io
import torch
from faster_whisper import WhisperModel
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import tempfile

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
    
    # Table for storing video transcripts
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drive_id TEXT,
            transcript TEXT,
            segments_json TEXT,
            FOREIGN KEY (drive_id) REFERENCES media (drive_id)
        )
    ''')
    
    conn.commit()
    conn.close()

def process_transcriptions():
    # 1. Load Whisper (Load-Process-Unload pattern)
    print("Loading Whisper model (base)...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # Use 'base' model for a good balance of speed and accuracy on 4GB VRAM
    model = WhisperModel("base", device=device, compute_type="float32")
    
    service = get_drive_service()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find video items without transcripts
    items = cursor.execute('''
        SELECT drive_id, filename FROM media 
        WHERE drive_id NOT IN (SELECT drive_id FROM transcripts)
        AND (filename LIKE '%.mp4' OR filename LIKE '%.mov' OR filename LIKE '%.avi')
    ''').fetchall()
    
    print(f"Found {len(items)} videos to transcribe.")
    
    for drive_id, filename in items:
        print(f"Transcribing {filename}...")
        
        try:
            # Download video to a temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
                request = service.files().get_media(fileId=drive_id)
                downloader = MediaIoBaseDownload(tmp, request)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                tmp_path = tmp.name
            
            # Transcribe
            segments, info = model.transcribe(tmp_path, beam_size=5)
            
            full_text = ""
            segments_data = []
            for segment in segments:
                full_text += segment.text + " "
                segments_data.append({
                    'start': segment.start,
                    'end': segment.end,
                    'text': segment.text
                })
            
            # Store in database
            cursor.execute('''
                INSERT INTO transcripts (drive_id, transcript, segments_json)
                VALUES (?, ?, ?)
            ''', (drive_id, full_text.strip(), json.dumps(segments_data)))
            conn.commit()
            
            # Clean up temp file
            os.unlink(tmp_path)
            print(f"Successfully transcribed {filename}")
            
        except Exception as e:
            print(f"Failed to transcribe {filename}: {e}")

    conn.close()
    print("Transcription complete. Unloading model...")
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

if __name__ == "__main__":
    import json
    update_schema()
    process_transcriptions()
