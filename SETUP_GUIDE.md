# Setup Guide - Family Archive Vault

Complete step-by-step setup instructions for Windows 11.

## Prerequisites Checklist

- [ ] Windows 11 PC
- [ ] Python 3.10 or newer
- [ ] Google account
- [ ] 500GB+ free storage on F:\ drive (or adjust LOCAL_ROOT)
- [ ] NVIDIA GPU with CUDA support (optional, for faster processing)

## Part 1: Google Cloud Setup

### 1.1 Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a project" → "New Project"
3. Name it "FamilyArchive" → Create
4. Wait for project creation

### 1.2 Enable Google Drive API

1. In your project, go to "APIs & Services" → "Library"
2. Search for "Google Drive API"
3. Click on it → Enable
4. Wait for API to enable

### 1.3 Create Service Account

1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "Service Account"
3. Name: "family-archive-vault"
4. Description: "Service account for Family Archive Vault"
5. Click "Create and Continue"
6. Skip role assignment (click "Continue")
7. Click "Done"

### 1.4 Download Service Account Key

1. Click on the service account you just created
2. Go to "Keys" tab
3. Click "Add Key" → "Create new key"
4. Choose "JSON" → Create
5. Save the downloaded JSON file to a safe location
   - Example: `C:\Users\YourName\Documents\family-archive-sa-key.json`
6. **Keep this file secure!** It's like a password.

### 1.5 Create Google Drive Folder

1. Go to [Google Drive](https://drive.google.com)
2. Create a new folder named "Family_Archive"
3. Open the folder
4. Look at the URL: `https://drive.google.com/drive/folders/XXXXXXXXXX`
5. Copy the `XXXXXXXXXX` part - this is your folder ID

### 1.6 Share Folder with Service Account

**CRITICAL STEP!**

1. Right-click your "Family_Archive" folder
2. Click "Share"
3. In your service account JSON file, find the email address:
   ```json
   {
     "client_email": "family-archive-vault@project-id.iam.gserviceaccount.com"
   }
   ```
4. Copy that email address
5. Paste it into the "Add people and groups" field in Drive
6. Change permission to "Editor"
7. Click "Send" (you might get a warning that it's external - that's OK)

## Part 2: Python Environment Setup

### 2.1 Install Python

1. Download Python 3.10+ from [python.org](https://www.python.org/downloads/)
2. **Important:** Check "Add Python to PATH" during installation
3. Verify installation:
   ```cmd
   python --version
   ```

### 2.2 Install Git (Optional)

If you want to clone from a repository:

1. Download from [git-scm.com](https://git-scm.com/)
2. Install with default options

### 2.3 Download Family Archive Vault

Option A: Clone from git:
```cmd
git clone [repository-url]
cd family-archive-vault
```

Option B: Download and extract ZIP

### 2.4 Create Virtual Environment

```cmd
cd family-archive-vault
python -m venv .venv
```

### 2.5 Activate Virtual Environment

```cmd
.venv\Scripts\activate
```

You should see `(.venv)` in your command prompt.

### 2.6 Install Dependencies

```cmd
pip install --upgrade pip
pip install -r requirements.txt
```

This will take 10-15 minutes as it downloads all AI models and dependencies.

**If you have GPU and want to use it:**
```cmd
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
pip install onnxruntime-gpu
```

**If CPU only:**
```cmd
pip install torch torchvision
pip install onnxruntime
```

## Part 3: Configuration

### 3.1 Create Environment File

```cmd
copy .env.example .env
notepad .env
```

### 3.2 Edit Configuration

Update these required values in `.env`:

```bash
# Google Drive Configuration
DRIVE_ROOT_FOLDER_ID=YOUR_FOLDER_ID_FROM_STEP_1.5
SERVICE_ACCOUNT_JSON_PATH=C:\Users\YourName\Documents\family-archive-sa-key.json

# Local Storage
LOCAL_ROOT=F:\FamilyArchive

# Intake Web App
INTAKE_SECRET_KEY=CHANGE_THIS_TO_RANDOM_STRING

# Contributor Tokens - Create one for each family member
TOKEN_mom=Mom_UPLOADS
TOKEN_dad=Dad_UPLOADS
TOKEN_aunt1=Aunt_Mary_UPLOADS
TOKEN_aunt2=Aunt_Susan_UPLOADS
TOKEN_cousin1=Cousin_John_UPLOADS
```

**Generate random secret key:**
```python
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3.3 Create Local Directory

```cmd
mkdir F:\FamilyArchive
```

Or adjust `LOCAL_ROOT` in `.env` to another location.

## Part 4: Bootstrap System

### 4.1 Run Bootstrap Script

```cmd
python -m scripts.bootstrap
```

This will:
- Verify your configuration
- Create local directories
- Initialize database
- Create folder structure in Google Drive
- Generate QR codes for upload links

**Expected output:**
```
╔═══════════════════════════════════════════════════════════╗
║           FAMILY ARCHIVE VAULT - BOOTSTRAP                ║
╚═══════════════════════════════════════════════════════════╝

✓ Environment configuration valid
✓ Local directories created
✓ Database initialized at F:\FamilyArchive\db\archive.db
✓ Connected as: family-archive-vault@project-id.iam.gserviceaccount.com
✓ Root folder accessible: Family_Archive
✓ Created 42 folders in Drive

CONTRIBUTOR UPLOAD LINKS
═══════════════════════════════════════════════════════════

Mom:
  URL: http://localhost:8000/u/mom
  Token: mom
  QR Code: F:\FamilyArchive\qr_codes\upload_qr_mom.png
...
```

### 4.2 Check Google Drive

Open your "Family_Archive" folder in Drive. You should see:
- INBOX_UPLOADS/
- PROCESSING/
- HOLDING/
- ARCHIVE/
- METADATA/
- ROSETTA_STONE/

## Part 5: Start Services

### 5.1 Terminal 1 - Intake Web App

```cmd
cd family-archive-vault
.venv\Scripts\activate
python -m intake_webapp.main
```

**Expected output:**
```
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Test it:** Open browser to `http://localhost:8000`

### 5.2 Terminal 2 - Worker

Open a **NEW** command prompt:

```cmd
cd family-archive-vault
.venv\Scripts\activate
python -m worker.main
```

**Expected output:**
```
2025-01-23 10:30:00 | INFO | Worker started
2025-01-23 10:30:00 | INFO | Checking for new files in INBOX...
```

### 5.3 Terminal 3 - Curator Dashboard

Open a **NEW** command prompt:

```cmd
cd family-archive-vault
.venv\Scripts\activate
streamlit run curator/main.py
```

**Expected output:**
```
  You can now view your Streamlit app in your browser.
  Local URL: http://localhost:8501
```

**Open it:** Browser to `http://localhost:8501`

## Part 6: Test Upload

### 6.1 Get Upload Link

From bootstrap output, use one of the upload URLs:
```
http://localhost:8000/u/mom
```

### 6.2 Upload Test Photos

1. Open the URL in browser (mobile or desktop)
2. Click or tap to select photos
3. Optionally fill in decade/event
4. Click upload
5. Wait for completion

### 6.3 Monitor Processing

**In Worker terminal**, you should see:
```
2025-01-23 10:35:00 | INFO | Found 3 files in Mom_UPLOADS
2025-01-23 10:35:05 | INFO | Processing asset: IMG_1234.jpg
2025-01-23 10:35:10 | INFO | Phase 1: Extracting metadata
2025-01-23 10:35:15 | INFO | Loading face detection model...
2025-01-23 10:35:20 | INFO | Detected 2 faces
...
```

### 6.4 Review in Dashboard

1. Go to curator dashboard: `http://localhost:8501`
2. Click "Review Queue" in sidebar
3. You should see your uploaded photos
4. Review and approve them

## Part 7: Share Upload Links

### 7.1 Print QR Codes

QR codes are saved to: `F:\FamilyArchive\qr_codes\`

Print them or share via email/text.

### 7.2 For Remote Access

**Option A: Cloud Deployment**

Deploy intake app to Heroku, DigitalOcean, Railway, etc.

```cmd
docker-compose up -d
```

Update upload URLs with your public domain.

**Option B: Port Forwarding**

Forward port 8000 on your router to your PC (not recommended without HTTPS).

**Option C: Tunneling (Development)**

Use ngrok, Cloudflare Tunnel, or similar:

```cmd
ngrok http 8000
```

Update upload URLs with the temporary ngrok URL.

## Part 8: Schedule Rosetta Stone Generation

### 8.1 Create Batch File

Create `F:\FamilyArchive\run_rosetta.bat`:

```batch
@echo off
cd /d C:\path\to\family-archive-vault
call .venv\Scripts\activate
python -m rosetta.main
```

### 8.2 Schedule with Task Scheduler

1. Open Task Scheduler
2. Create Basic Task
3. Name: "Family Archive Rosetta"
4. Trigger: Daily at 3:00 AM
5. Action: Start a program
6. Program: `F:\FamilyArchive\run_rosetta.bat`
7. Finish

## Troubleshooting

### "Cannot access Drive folder"

**Check:**
1. Is folder shared with service account email?
2. Does service account have "Editor" permissions?
3. Is folder ID correct in `.env`?

**Fix:**
```cmd
python -c "from shared.drive_client import DriveClient; from shared.config import get_settings; s = get_settings(); d = DriveClient(s.service_account_json_path, s.drive_root_folder_id); print(d.get_service_account_email())"
```

Copy the email and reshare your Drive folder with it.

### "Module not found" errors

**Ensure virtual environment is activated:**
```cmd
.venv\Scripts\activate
```

**Reinstall dependencies:**
```cmd
pip install -r requirements.txt
```

### Worker not finding files

**Check:**
1. Did files upload successfully?
2. Check Drive folder in browser
3. Check worker logs: `F:\FamilyArchive\logs\`

### Out of memory errors

**Reduce batch size in `.env`:**
```bash
WORKER_BATCH_SIZE=5
THUMBNAIL_SIZE=600
```

**Or disable GPU:**
```bash
USE_GPU=false
```

### Upload fails on mobile

**Increase chunk size for better networks:**
```bash
UPLOAD_CHUNK_SIZE_MB=20
```

**Or decrease for unstable connections:**
```bash
UPLOAD_CHUNK_SIZE_MB=5
```

## Next Steps

1. Upload family photos!
2. Review and approve in dashboard
3. Name face clusters for automatic identification
4. Generate Rosetta Stone site
5. Share site with family

## Maintenance Tips

- Check logs weekly: `F:\FamilyArchive\logs\`
- Backup database monthly: `F:\FamilyArchive\db\archive.db`
- Run face clustering after uploading batches: `python -m scripts.cluster_faces`
- Generate Rosetta Stone after major updates: `python -m rosetta.main`

---

**Congratulations!** Your Family Archive Vault is ready. 🎉
