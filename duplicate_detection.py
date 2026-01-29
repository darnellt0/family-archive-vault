import sqlite3
import imagehash
from PIL import Image
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

DB_PATH = r'F:\FamilyArchive\data\archive.db'
SERVICE_ACCOUNT_FILE = r'F:\FamilyArchive\config\service-account.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def find_duplicates(threshold=5):
    """
    Find duplicate images using pHash similarity.
    
    Args:
        threshold (int): Maximum Hamming distance to consider as duplicates (0-64). 
                        Lower = stricter matching. Default 5 means ~95% similarity.
    
    Returns:
        list: List of duplicate groups, each containing drive_ids with similar images.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all items with pHash values
    items = cursor.execute('''
        SELECT drive_id, phash FROM media 
        WHERE phash IS NOT NULL AND phash != 'failed'
    ''').fetchall()
    
    conn.close()
    
    # Build hash objects
    hash_objects = []
    for drive_id, phash_str in items:
        try:
            hash_obj = imagehash.ImageHash(imagehash.hex2np(phash_str))
            hash_objects.append((drive_id, hash_obj))
        except Exception as e:
            print(f"Error parsing hash for {drive_id}: {e}")
    
    # Find duplicates using Hamming distance
    duplicates = []
    seen = set()
    
    for i, (drive_id_1, hash_1) in enumerate(hash_objects):
        if drive_id_1 in seen:
            continue
        
        group = [drive_id_1]
        for drive_id_2, hash_2 in hash_objects[i+1:]:
            if drive_id_2 in seen:
                continue
            
            # Calculate Hamming distance
            distance = hash_1 - hash_2
            if distance <= threshold:
                group.append(drive_id_2)
                seen.add(drive_id_2)
        
        if len(group) > 1:
            duplicates.append(group)
            for drive_id in group:
                seen.add(drive_id)
    
    return duplicates

def get_duplicate_groups():
    """
    Get duplicate groups with metadata for the dashboard.
    """
    duplicate_groups = find_duplicates(threshold=5)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    result = []
    for group in duplicate_groups:
        group_data = []
        placeholders = ','.join(['?' for _ in group])
        items = cursor.execute(f"SELECT * FROM media WHERE drive_id IN ({placeholders})", group).fetchall()
        group_data = [dict(item) for item in items]
        result.append(group_data)
    
    conn.close()
    return result

if __name__ == "__main__":
    groups = get_duplicate_groups()
    print(f"Found {len(groups)} duplicate groups")
    for i, group in enumerate(groups):
        print(f"\nGroup {i+1}:")
        for item in group:
            print(f"  - {item['filename']} ({item['drive_id']})")
