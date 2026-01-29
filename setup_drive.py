import sys
sys.stdout = open(r"F:\FamilyArchive\setup_output.txt", "w")

from google.oauth2 import service_account
from googleapiclient.discovery import build

SERVICE_ACCOUNT_FILE = r"F:\FamilyArchive\config\service-account.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]

credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build("drive", "v3", credentials=credentials)

# Get Family_Archive folder ID
results = service.files().list(
    q="name='Family_Archive' and mimeType='application/vnd.google-apps.folder'",
    fields="files(id, name)"
).execute()
parent_id = results["files"][0]["id"]
print(f"Family_Archive ID: {parent_id}")

# Create subfolders
subfolders = ["INBOX", "ARCHIVE", "REJECTED", "METADATA"]
folder_ids = {"Family_Archive": parent_id}

for folder_name in subfolders:
    # Check if folder already exists
    check = service.files().list(
        q=f"name='{folder_name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder'",
        fields="files(id, name)"
    ).execute()
    
    if check.get("files"):
        folder_ids[folder_name] = check["files"][0]["id"]
        print(f"  {folder_name} already exists (ID: {folder_ids[folder_name]})")
    else:
        metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id]
        }
        folder = service.files().create(body=metadata, fields="id").execute()
        folder_ids[folder_name] = folder["id"]
        print(f"  Created {folder_name} (ID: {folder_ids[folder_name]})")

# Save folder IDs to config
import json
config_path = r"F:\FamilyArchive\config\drive_folders.json"
with open(config_path, "w") as f:
    json.dump(folder_ids, f, indent=2)
print(f"\nFolder IDs saved to: {config_path}")

sys.stdout.close()
