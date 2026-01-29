from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import json

SERVICE_ACCOUNT_FILE = r'F:\FamilyArchive\config\service-account.json'
SCOPES = ['https://www.googleapis.com/auth/drive']

with open(r'F:\FamilyArchive\config\drive_folders.json') as f:
    folders = json.load(f)

INBOX_ID = folders['INBOX']
TEST_IMAGE = r'C:\Users\darne\Pictures\Saved Pictures\IMG_3588.jpg'

print('Authenticating...')
credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('drive', 'v3', credentials=credentials)

print(f'Uploading {TEST_IMAGE} to INBOX...')
file_metadata = {
    'name': 'test_family_photo.jpg',
    'parents': [INBOX_ID]
}
media = MediaFileUpload(TEST_IMAGE, mimetype='image/jpeg')
file = service.files().create(body=file_metadata, media_body=media, fields='id, name').execute()
print(f'SUCCESS! Uploaded: {file["name"]} (ID: {file["id"]})')
