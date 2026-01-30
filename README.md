# Family Archive Vault

A complete, local-AI powered family photo and video preservation system with Google Drive storage, automated metadata extraction, face detection, and offline static site generation.

## Overview

**Primary Goal:** Create a central family archive where relatives can upload photos/videos to Google Drive, with local-only AI processing on your Windows 11 PC. Originals remain immutable. All metadata is stored in sidecar JSON files and a SQLite database. A curator dashboard enables approval and face identification. A nightly static "Rosetta Stone" site ensures your family memories are browsable forever, even offline.

## Key Features

- ✅ **Immutable Originals**: Never modifies original media files
- ✅ **Local-Only AI**: No cloud AI APIs (OpenAI, Google Vision, AWS)
- ✅ **Resumable Uploads**: Mobile-friendly chunked upload with interruption recovery
- ✅ **Face Detection & Clustering**: InsightFace for local face recognition
- ✅ **Image Captioning**: Moondream2 for AI-generated descriptions
- ✅ **Semantic Search**: CLIP embeddings for visual search
- ✅ **Audio Transcription**: Whisper for video and voice note transcription
- ✅ **Duplicate Detection**: SHA256 + perceptual hash matching
- ✅ **Curator Dashboard**: Streamlit interface for review and curation
- ✅ **Rosetta Stone**: Static HTML site for offline browsing
- ✅ **Bus Factor Protection**: Everything recoverable from Drive + sidecars

## System Architecture

```
┌─────────────────┐
│  Family Members │  (Mobile/Web Upload)
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────┐
│  INTAKE WEB APP (FastAPI + Docker)              │
│  - Chunked/resumable uploads                    │
│  - Token-based contributor access               │
│  - Manifest generation                          │
└────────┬────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────┐
│  GOOGLE DRIVE (Cloud Storage)                   │
│  - INBOX_UPLOADS/                               │
│  - PROCESSING/                                  │
│  - HOLDING/ (Review, Duplicates)                │
│  - ARCHIVE/ (Originals, Videos)                 │
│  - METADATA/ (Sidecars, Thumbnails)             │
│  - ROSETTA_STONE/ (Static Site)                 │
└────────┬────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────┐
│  LOCAL WORKER (Windows 11 PC)                   │
│  F:\FamilyArchive\                              │
│                                                 │
│  Serial AI Processing (4GB VRAM):               │
│  1. Metadata extraction (SHA256, EXIF, phash)   │
│  2. Face detection (InsightFace)                │
│  3. Image captioning (Moondream2)               │
│  4. CLIP embeddings (semantic search)           │
│  5. Whisper transcription (videos <8min)        │
│                                                 │
│  Output: Sidecar JSON + SQLite DB               │
└────────┬────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────┐
│  CURATOR DASHBOARD (Streamlit)                  │
│  - Review queue                                 │
│  - Duplicate resolution                         │
│  - Face cluster naming                          │
│  - Approval & archiving                         │
└─────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────┐
│  ROSETTA STONE GENERATOR (Nightly)              │
│  - Static HTML site                             │
│  - Decade/People/Event indexes                  │
│  - "Who Is This?" page                          │
│  - Offline browsable                            │
└─────────────────────────────────────────────────┘
```

## Hardware Requirements

**Target System: Windows 11 PC**
- CPU: AMD Ryzen 7 3700X (or equivalent)
- RAM: 64GB (32GB minimum)
- GPU: NVIDIA GTX 1650 SUPER (4GB VRAM) - VRAM managed aggressively
- Storage: F:\FamilyArchive\ (recommend 500GB+ for cache)

**Alternative:** Can run on CPU-only (slower, set `USE_GPU=false`)

## Quick Start

### 1. Prerequisites

- Python 3.10+
- Google Cloud Service Account with Drive API enabled
- Google Drive folder shared with service account
- (Optional) Docker for intake web app deployment

### 2. Installation

```bash
# Clone or download the repository
cd family-archive-vault

# Create virtual environment (Windows)
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings
notepad .env
```

**Required settings:**
- `DRIVE_ROOT_FOLDER_ID`: Your Google Drive folder ID
- `SERVICE_ACCOUNT_JSON_PATH`: Path to service account key
- `LOCAL_ROOT`: F:\FamilyArchive (or your local path)
- `INTAKE_SECRET_KEY`: Random secret for web app
- `TOKEN_*`: Contributor tokens (e.g., TOKEN_aunt1=Aunt_1_UPLOADS)

### 4. Google Drive Setup

**Important:** Service accounts don't see your personal Drive by default!

1. Create a folder in your Google Drive called "Family_Archive"
2. Get the folder ID from the URL: `https://drive.google.com/drive/folders/FOLDER_ID_HERE`
3. Right-click the folder → Share → Add the service account email (found in your JSON key)
4. Give "Editor" permissions

**Or use a Shared Drive** (recommended for team use)

### 5. Bootstrap

```bash
# Initialize the system
python -m scripts.bootstrap

# This will:
# - Verify configuration
# - Create local directories
# - Initialize database
# - Setup Drive folder structure
# - Generate QR codes for upload links
```

### 6. Run Components

**Option A: Local Development**

```bash
# Terminal 1: Start intake web app
python -m intake_webapp.main

# Terminal 2: Start worker
python -m worker.main

# Terminal 3: Start curator dashboard
streamlit run curator/main.py

# On-demand: Generate Rosetta Stone site
python -m rosetta.main
```

**Option B: Docker (Intake only)**

```bash
# Build and run intake web app
docker-compose up -d

# Worker and dashboard must run locally for GPU access
python -m worker.main
streamlit run curator/main.py
```

## Usage Workflow

### For Family Members (Uploaders)

1. Receive personalized upload link or QR code
2. Visit link on mobile or desktop
3. Select photos/videos (supports bulk upload)
4. Optionally add context (decade, event name, notes)
5. Optionally record voice note about the memories
6. Upload! (Resumable if interrupted)

### For Curator (You)

1. **Review Queue**: Worker processes uploads and moves to review
   - View thumbnails, AI captions, detected faces
   - Add/correct decade, event names, tags
   - Approve → moves to ARCHIVE
   - Or mark as low quality / skip

2. **Duplicates**: Resolve possible duplicates
   - Side-by-side comparison
   - Confirm duplicate or mark as unique

3. **People Clusters**: Name face clusters
   - View unnamed face clusters
   - Assign names to recurring faces
   - Merge clusters if needed

4. **Search**: Find assets by text, caption, or transcript

### Nightly Site Generation

```bash
# Run manually or schedule with Windows Task Scheduler
python -m rosetta.main
```

Generates static HTML site that:
- Browses by decade, people, events
- Shows "Who Is This?" for unidentified faces
- Includes README with recovery instructions
- Uploads to Drive at ROSETTA_STONE/nightly_site/

## Directory Structure

```
F:\FamilyArchive\              # Local working directory
├── cache\                     # Temporary processing files
│   ├── thumbnails\            # Generated thumbnails
│   ├── video_posters\         # Video poster frames
│   ├── sidecars\              # Local mirror of sidecars
│   ├── processing\            # Downloaded files during processing
│   └── rosetta_site\          # Generated static site
├── db\
│   └── archive.db             # SQLite database
├── logs\                      # Application logs
└── qr_codes\                  # Generated QR codes for upload links
```

## Google Drive Structure

```
Family_Archive/                # Root folder (share with service account!)
├── INBOX_UPLOADS/
│   ├── _MANIFESTS/            # Upload batch manifests
│   ├── Aunt_1_UPLOADS/        # Contributor folders
│   ├── Aunt_2_UPLOADS/
│   └── ...
├── PROCESSING/                # Files being processed by worker
├── HOLDING/
│   ├── Needs_Review/          # Awaiting curator approval
│   ├── Possible_Duplicates/   # Detected duplicates
│   └── Low_Confidence/        # Low quality / flagged
├── ARCHIVE/
│   ├── Originals/
│   │   ├── 1940s/
│   │   ├── 1950s/
│   │   └── ...
│   ├── Videos/
│   │   ├── 1940s/
│   │   └── ...
│   └── Print_Ready/           # High-quality print candidates
├── METADATA/
│   ├── sidecars_json/         # Sidecar JSON for each asset
│   ├── thumbnails/            # Thumbnail images
│   ├── video_posters/         # Video poster frames
│   └── transcripts/           # Video transcripts
└── ROSETTA_STONE/
    └── nightly_site/          # Static HTML site
```

## Sidecar JSON Format

Each asset has a sidecar JSON file with complete metadata:

```json
{
  "asset_id": "uuid-here",
  "sha256": "hash",
  "phash": "perceptual-hash",
  "drive_file_id": "drive-id",
  "original_filename": "IMG_1234.jpg",
  "contributor_token": "aunt1",
  "batch_id": "batch_20250115_...",
  "asset_type": "image",
  "mime_type": "image/jpeg",
  "file_size_bytes": 2048576,
  "exif_data": {...},
  "exif_date": "2024-12-25T10:30:00",
  "decade": 2020,
  "faces": [
    {
      "box": {"x": 100, "y": 200, "width": 150, "height": 150, "confidence": 0.99},
      "embedding": [0.1, 0.2, ...],
      "cluster_id": 5,
      "person_name": "Grandma Jane"
    }
  ],
  "caption": "AI-generated image description",
  "clip_embedding_id": "uuid",
  "transcript": "Video audio transcript",
  "duplicate_of": null,
  "status": "archived",
  "event_name": "Christmas 2024",
  "tags": ["family", "holiday"],
  "notes": "Taken at Aunt Mary's house",
  "drive_path": "ARCHIVE/Originals/2020s/IMG_1234.jpg"
}
```

## Advanced Configuration

### Face Clustering

```bash
# Run face clustering after processing batches
python -m scripts.cluster_faces
```

Uses HDBSCAN to group similar faces. Run periodically as more faces are detected.

### GPU Memory Management

The worker loads AI models **serially** to manage 4GB VRAM:

1. Load InsightFace → process faces → unload
2. Load Moondream2 → generate captions → unload
3. Load CLIP → generate embeddings → unload
4. Load Whisper → transcribe audio → unload

Each model is unloaded before the next loads, with explicit `torch.cuda.empty_cache()`.

### Whisper Transcription Limits

Videos longer than `VIDEO_TRANSCRIBE_MAX_MINUTES` (default: 8) are skipped to avoid excessive processing time. Adjust in `.env`:

```bash
VIDEO_TRANSCRIBE_MAX_MINUTES=15  # Process videos up to 15 minutes
```

### Duplicate Detection

- **Exact duplicates**: Matched by SHA256
- **Near duplicates**: Matched by perceptual hash (phash) distance
- Threshold: `PHASH_DUPLICATE_THRESHOLD=5` (lower = stricter)

## Troubleshooting

### "Cannot access Drive folder"
- Ensure folder is shared with service account email
- Check folder ID is correct in `.env`
- Service account needs "Editor" permissions

### "Out of VRAM" errors
- Reduce `THUMBNAIL_SIZE` and `WORKER_BATCH_SIZE`
- Set `USE_GPU=false` to use CPU instead
- Ensure models are unloading between steps

### "Model not found"
- Models download automatically on first run
- Ensure internet connection for initial download
- Check `~/.cache/huggingface/` and `~/.insightface/`

### Upload fails on mobile
- Uploads are chunked and resumable
- Check network stability
- Increase `UPLOAD_CHUNK_SIZE_MB` for better networks
- Decrease for unstable connections

## Security & Privacy

- **No cloud AI**: All processing happens locally
- **Token-based access**: Upload links use secret tokens
- **No authentication**: Simple token-based "secret link" system
- **Rate limiting**: Configurable upload rate limits
- **No public listing**: Tokens not discoverable

**For production:** Consider adding authentication, HTTPS, and firewall rules.

## Maintenance

### Backups

**Critical data:**
1. Google Drive folder (originals + metadata)
2. SQLite database: `F:\FamilyArchive\db\archive.db`
3. `.env` configuration

**Recovery:** System can be fully rebuilt from Drive sidecars if needed.

### Monitoring

- Check logs: `F:\FamilyArchive\logs\`
- Worker logs each asset processing step
- Intake logs uploads and errors

### Database Maintenance

```bash
# Backup database
cp F:\FamilyArchive\db\archive.db F:\FamilyArchive\db\archive_backup_$(date +%Y%m%d).db

# Vacuum database (compact)
sqlite3 F:\FamilyArchive\db\archive.db "VACUUM;"
```

## Extending the System

### Adding Contributors

1. Add token to `.env`:
   ```bash
   TOKEN_newperson=NewPerson_UPLOADS
   ```

2. Re-run bootstrap to create folder:
   ```bash
   python -m scripts.bootstrap
   ```

3. Share new QR code/link

### Custom AI Models

Edit `worker/processors/*.py` to swap models:
- Face detection: Any ONNX model compatible with InsightFace
- Captioning: Any vision-language model from HuggingFace
- Embeddings: Any CLIP or similar model
- Transcription: Other Whisper sizes (tiny, small, base, medium, large)

### Webhooks / Notifications

Add to `worker/main.py` to notify on events:
- New uploads
- Processing complete
- Duplicates found
- Errors

## License

This project is provided as-is for personal family use. Modify as needed.

## Support

For issues or questions, review logs and check configuration first. System is designed to be self-contained and maintainable.

---

**Built with:** FastAPI, Streamlit, InsightFace, Moondream2, CLIP, Whisper, SQLAlchemy, Google Drive API

**Designed for:** Long-term family memory preservation with "bus factor" resilience.
