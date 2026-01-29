"""
Family Archive Vault - Connection Test
Verifies that the service account can access the Family_Archive folder in Google Drive.
"""

from google.oauth2 import service_account
from googleapiclient.discovery import build
import json
import os

# Configuration
SERVICE_ACCOUNT_FILE = r"F:\FamilyArchive\config\service-account.json"
SCOPES = ['https://www.googleapis.com/auth/drive']

def test_connection():
    print("=" * 50)
    print("Family Archive Vault - Connection Test")
    print("=" * 50)
    
    # Check if service account file exists
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"ERROR: Service account file not found at {SERVICE_ACCOUNT_FILE}")
        return False
    
    print(f"[OK] Service account file found")
    
    # Load credentials
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        print(f"[OK] Credentials loaded successfully")
        print(f"    Service Account: {credentials.service_account_email}")
    except Exception as e:
        print(f"ERROR: Failed to load credentials: {e}")
        return False
    
    # Build Drive service
    try:
        service = build('drive', 'v3', credentials=credentials)
        print(f"[OK] Google Drive API service created")
    except Exception as e:
        print(f"ERROR: Failed to create Drive service: {e}")
        return False
    
    # Search for Family_Archive folder
    try:
        results = service.files().list(
            q="name='Family_Archive' and mimeType='application/vnd.google-apps.folder'",
            spaces='drive',
            fields='files(id, name, owners)'
        ).execute()
        
        folders = results.get('files', [])
        
        if not folders:
            print("WARNING: Family_Archive folder not found.")
            print("         Make sure the folder is shared with the service account.")
            return False
        
        folder = folders[0]
        print(f"[OK] Family_Archive folder found!")
        print(f"    Folder ID: {folder['id']}")
        
        # Save folder ID for later use
        config_path = r"F:\FamilyArchive\config\drive_config.json"
        with open(config_path, 'w') as f:
            json.dump({
                'family_archive_folder_id': folder['id'],
                'service_account_email': credentials.service_account_email
            }, f, indent=2)
        print(f"[OK] Configuration saved to {config_path}")
        
    except Exception as e:
        print(f"ERROR: Failed to search for folder: {e}")
        return False
    
    # Test creating a subfolder (will be used for INBOX, ARCHIVE, etc.)
    try:
        # Check if INBOX subfolder exists
        results = service.files().list(
            q=f"name='INBOX' and '{folder['id']}' in parents and mimeType='application/vnd.google-apps.folder'",
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        
        subfolders = results.get('files', [])
        
        if not subfolders:
            # Create INBOX folder
            file_metadata = {
                'name': 'INBOX',
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [folder['id']]
            }
            inbox = service.files().create(body=file_metadata, fields='id').execute()
            print(f"[OK] Created INBOX subfolder (ID: {inbox['id']})")
        else:
            print(f"[OK] INBOX subfolder already exists (ID: {subfolders[0]['id']})")
            
    except Exception as e:
        print(f"ERROR: Failed to create/check INBOX folder: {e}")
        return False
    
    print("\n" + "=" * 50)
    print("CONNECTION TEST PASSED!")
    print("=" * 50)
    return True

if __name__ == "__main__":
    test_connection()
