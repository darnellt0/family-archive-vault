import os
import sqlite3
import io
import numpy as np
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from PIL import Image
import cv2
import insightface
from insightface.app import FaceAnalysis

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
    
    # Table for storing face detections
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drive_id TEXT,
            embedding BLOB,
            bbox TEXT,
            confidence REAL,
            cluster_id INTEGER,
            FOREIGN KEY (drive_id) REFERENCES media (drive_id)
        )
    ''')
    
    # Table for storing named clusters (people)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS clusters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            representative_face_id INTEGER
        )
    ''')
    
    conn.commit()
    conn.close()

def process_faces():
    # 1. Load InsightFace (Load-Process-Unload pattern)
    print("Loading InsightFace model...")
    app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']) # Use CPU for sandbox, user can switch to CUDA
    app.prepare(ctx_id=0, det_size=(640, 640))
    
    service = get_drive_service()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find items that haven't been processed for faces yet
    # We'll use a subquery to find drive_ids not in the faces table
    items = cursor.execute('''
        SELECT drive_id, filename FROM media 
        WHERE drive_id NOT IN (SELECT DISTINCT drive_id FROM faces)
        AND (filename LIKE '%.jpg' OR filename LIKE '%.jpeg' OR filename LIKE '%.png')
    ''').fetchall()
    
    print(f"Found {len(items)} items to process for faces.")
    
    for drive_id, filename in items:
        print(f"Processing {filename} for faces...")
        
        try:
            # Download image
            request = service.files().get_media(fileId=drive_id)
            file_stream = io.BytesIO()
            downloader = MediaIoBaseDownload(file_stream, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            
            # Convert to OpenCV format
            file_bytes = np.frombuffer(file_stream.getvalue(), np.uint8)
            img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
            
            if img is None:
                print(f"Could not decode {filename}")
                continue
                
            # Detect faces
            faces = app.get(img)
            print(f"Detected {len(faces)} faces in {filename}")
            
            for face in faces:
                # Store embedding as blob
                embedding = face.embedding.tobytes()
                bbox = json.dumps(face.bbox.tolist())
                confidence = float(face.det_score)
                
                cursor.execute('''
                    INSERT INTO faces (drive_id, embedding, bbox, confidence)
                    VALUES (?, ?, ?, ?)
                ''', (drive_id, embedding, bbox, confidence))
            
            conn.commit()
            
        except Exception as e:
            print(f"Failed to process {filename}: {e}")

    conn.close()
    print("Face processing complete. Unloading model...")
    # In Python, the model will be garbage collected when 'app' goes out of scope.
    # We can explicitly delete it to be sure.
    del app

if __name__ == "__main__":
    import json
    update_schema()
    process_faces()
