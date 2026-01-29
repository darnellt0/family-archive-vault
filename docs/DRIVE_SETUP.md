# Drive Setup

## Find DRIVE_ROOT_FOLDER_ID
1. Open Google Drive in a browser.
2. Click the `Family_Archive` folder.
3. The folder ID is the long string in the URL after `/folders/`.

## Share the Family_Archive folder with the service account
1. Open `Family_Archive` in Google Drive.
2. Click **Share**.
3. Add the service account email (found in the service account JSON, `client_email`).
4. Grant **Editor** access.

Important: service accounts cannot see your personal Drive unless the folder is explicitly shared with them.

## Bootstrap the required schema
```
set DRIVE_ROOT_FOLDER_ID=your_folder_id
python services/worker/drive_bootstrap.py
```
This will create:
- `INBOX_UPLOADS/`
- `PROCESSING/`
- `HOLDING/`
- `ARCHIVE/`
- `METADATA/`
- `ROSETTA_STONE/`
- `HELPERS/`
with all required subfolders.
