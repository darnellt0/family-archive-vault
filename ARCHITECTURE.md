# Architecture Documentation

## System Overview

Family Archive Vault is a distributed system with four main components that work together to preserve, process, and present family media.

## Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTAKE WEB APP                            │
│                        (FastAPI)                                 │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │   Upload     │  │   Chunking   │  │   Manifest   │         │
│  │   Handler    │  │   Manager    │  │   Generator  │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│         │                  │                  │                  │
│         └──────────────────┴──────────────────┘                 │
│                          │                                       │
│                          ▼                                       │
│                  Google Drive API                                │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      GOOGLE DRIVE                                │
│                   (Cloud Storage Layer)                          │
│                                                                  │
│  Folder Structure:                                               │
│  • INBOX_UPLOADS/     → New files from users                    │
│  • PROCESSING/        → Files being processed                   │
│  • HOLDING/           → Awaiting curation                       │
│  • ARCHIVE/           → Final approved storage                  │
│  • METADATA/          → Sidecars, thumbnails, etc.              │
│  • ROSETTA_STONE/     → Static site copies                      │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      LOCAL WORKER                                │
│                   (AI Processing Pipeline)                       │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Drive Poller & Downloader                    │  │
│  └───────────────────────┬──────────────────────────────────┘  │
│                          ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         Phase 1: Fast Metadata Extraction (No GPU)       │  │
│  │  • SHA256 hash                                            │  │
│  │  • Perceptual hash (phash)                               │  │
│  │  • EXIF extraction                                        │  │
│  │  • FFprobe metadata                                       │  │
│  │  • Thumbnail generation                                   │  │
│  │  • Duplicate detection                                    │  │
│  └───────────────────────┬──────────────────────────────────┘  │
│                          ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │       Phase 2: AI Processing (Serial GPU Loading)        │  │
│  │                                                           │  │
│  │  1. Load InsightFace → Detect faces → Unload            │  │
│  │  2. Load Moondream2 → Generate caption → Unload         │  │
│  │  3. Load CLIP → Generate embedding → Unload             │  │
│  │  4. Load Whisper → Transcribe audio → Unload            │  │
│  │                                                           │  │
│  │  Each model explicitly unloads with torch.cuda.empty()   │  │
│  └───────────────────────┬──────────────────────────────────┘  │
│                          ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │            Sidecar & Database Writer                      │  │
│  └───────────────────────┬──────────────────────────────────┘  │
│                          ▼                                       │
│                  Drive Router (Needs_Review, etc.)              │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      CURATOR DASHBOARD                           │
│                      (Streamlit)                                 │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │   Review     │  │  Duplicates  │  │   People     │         │
│  │   Queue      │  │  Resolution  │  │  Clusters    │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│         │                  │                  │                  │
│         └──────────────────┴──────────────────┘                 │
│                          │                                       │
│                          ▼                                       │
│                    SQLite Database                               │
│                    Drive API (move files)                        │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  ROSETTA STONE GENERATOR                         │
│                  (Static Site Builder)                           │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Query Database & Drive                       │  │
│  └───────────────────────┬──────────────────────────────────┘  │
│                          ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │            Generate HTML Pages                            │  │
│  │  • Index                                                  │  │
│  │  • Decades                                                │  │
│  │  • People                                                 │  │
│  │  • Events                                                 │  │
│  │  • "Who Is This?"                                         │  │
│  │  • README                                                 │  │
│  └───────────────────────┬──────────────────────────────────┘  │
│                          ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         Upload to ROSETTA_STONE/ in Drive                │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow

### Upload Flow

```
User (Mobile/Desktop)
  │
  │ 1. Access /u/{token}
  ▼
Intake Web App
  │
  │ 2. POST /api/upload/init
  │    → Create session, get chunk size
  │
  │ 3. POST /api/upload/chunk (multiple)
  │    → Save chunks to local temp
  │
  │ 4. POST /api/upload/finish
  │    → Reassemble chunks
  │    → Upload to Drive INBOX
  │    → Clean up temp files
  │
  │ 5. POST /api/manifest/save
  │    → Save batch manifest to Drive
  ▼
Google Drive (INBOX_UPLOADS/)
```

### Processing Flow

```
Worker Poll Loop (every 5 minutes)
  │
  │ 1. List files in INBOX_UPLOADS/*
  ▼
Found new files?
  │
  │ YES
  │
  │ 2. Move to PROCESSING/
  │ 3. Download to local cache
  ▼
For each file:
  │
  │ 4. Extract metadata (SHA256, EXIF, etc.)
  │ 5. Create thumbnail/poster
  │ 6. Check for duplicates
  ▼
  │ 7. AI Processing (if not duplicate):
  │
  │    Load InsightFace
  │    ├─> Detect faces
  │    └─> Unload model
  │
  │    Load Moondream2
  │    ├─> Generate caption
  │    └─> Unload model
  │
  │    Load CLIP
  │    ├─> Generate embedding
  │    └─> Unload model
  │
  │    Load Whisper (if video <8min)
  │    ├─> Transcribe audio
  │    └─> Unload model
  │
  │ 8. Write sidecar JSON
  │    ├─> Local cache
  │    └─> Drive METADATA/sidecars_json/
  │
  │ 9. Update SQLite database
  │
  │ 10. Route in Drive:
  │     ├─> Needs_Review/        (default)
  │     ├─> Possible_Duplicates/ (if duplicate)
  │     └─> Low_Confidence/      (if errors)
  ▼
Done, wait for next poll
```

### Curation Flow

```
Curator opens Dashboard
  │
  │ Query SQLite DB
  ▼
Display Review Queue
  │
  │ For each asset:
  │ • Show thumbnail
  │ • Show AI metadata
  │ • Allow editing
  ▼
Curator approves asset
  │
  │ 1. Update metadata in DB
  │ 2. Update sidecar JSON
  │ 3. Move file in Drive:
  │    ├─> ARCHIVE/Originals/{decade}/
  │    └─> ARCHIVE/Videos/{decade}/
  │ 4. Set status = 'archived'
  ▼
Asset archived
```

### Rosetta Stone Flow

```
Scheduled or manual trigger
  │
  │ 1. Query DB for archived assets
  ▼
For each asset:
  │
  │ 2. Copy thumbnail to output dir
  │ 3. Render HTML card
  ▼
Generate pages:
  │
  │ • index.html
  │ • decade-*.html
  │ • person-*.html
  │ • event-*.html
  │ • who-is-this.html
  │ • readme.html
  │
  │ 4. Generate CSS & JS
  │ 5. Create search index JSON
  ▼
Upload to Drive
  │
  └─> ROSETTA_STONE/nightly_site/
```

## Database Schema

### Core Tables

```sql
-- Assets (main table)
CREATE TABLE assets (
    asset_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    phash TEXT,
    drive_file_id TEXT UNIQUE NOT NULL,
    original_filename TEXT NOT NULL,
    contributor_token TEXT NOT NULL,
    batch_id TEXT,
    asset_type TEXT NOT NULL,
    mime_type TEXT,
    file_size_bytes INTEGER,
    upload_timestamp DATETIME NOT NULL,
    exif_date DATETIME,
    estimated_date DATETIME,
    decade INTEGER,
    status TEXT NOT NULL DEFAULT 'uploaded',
    duplicate_of TEXT,
    is_master BOOLEAN DEFAULT TRUE,
    event_name TEXT,
    tags JSON,
    notes TEXT,
    caption TEXT,
    clip_embedding_id TEXT,
    transcript TEXT,
    drive_path TEXT,
    thumbnail_path TEXT,
    gps_latitude REAL,
    gps_longitude REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (duplicate_of) REFERENCES assets(asset_id),
    FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
);

-- Batches
CREATE TABLE batches (
    batch_id TEXT PRIMARY KEY,
    contributor_token TEXT NOT NULL,
    contributor_folder TEXT,
    decade INTEGER,
    event_name TEXT,
    notes TEXT,
    voice_note_file_id TEXT,
    total_files INTEGER DEFAULT 0,
    total_bytes INTEGER DEFAULT 0,
    processed_files INTEGER DEFAULT 0,
    upload_start DATETIME NOT NULL,
    upload_end DATETIME,
    processing_completed DATETIME
);

-- Faces
CREATE TABLE faces (
    face_id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    box_x REAL NOT NULL,
    box_y REAL NOT NULL,
    box_width REAL NOT NULL,
    box_height REAL NOT NULL,
    confidence REAL NOT NULL,
    cluster_id INTEGER,
    person_id TEXT,
    person_name TEXT,
    embedding JSON NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id),
    FOREIGN KEY (cluster_id) REFERENCES clusters(cluster_id)
);

-- Clusters
CREATE TABLE clusters (
    cluster_id INTEGER PRIMARY KEY,
    person_id TEXT UNIQUE,
    person_name TEXT,
    face_count INTEGER DEFAULT 0,
    confidence_score REAL,
    sample_asset_ids JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- CLIP Embeddings
CREATE TABLE clip_embeddings (
    embedding_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    embedding JSON NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id)
);

-- Duplicates
CREATE TABLE duplicates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id TEXT NOT NULL,
    master_asset_id TEXT NOT NULL,
    duplicate_asset_id TEXT NOT NULL,
    similarity_score REAL NOT NULL,
    similarity_type TEXT NOT NULL,
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (master_asset_id) REFERENCES assets(asset_id),
    FOREIGN KEY (duplicate_asset_id) REFERENCES assets(asset_id)
);

-- Reviews
CREATE TABLE reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reviewer TEXT,
    notes TEXT,
    changes JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id)
);
```

## Sidecar JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["asset_id", "sha256", "drive_file_id", "original_filename"],
  "properties": {
    "asset_id": {"type": "string", "format": "uuid"},
    "sha256": {"type": "string"},
    "phash": {"type": ["string", "null"]},
    "drive_file_id": {"type": "string"},
    "original_filename": {"type": "string"},
    "contributor_token": {"type": "string"},
    "batch_id": {"type": "string"},
    "upload_timestamp": {"type": "string", "format": "date-time"},
    "asset_type": {"enum": ["image", "video", "audio"]},
    "mime_type": {"type": "string"},
    "file_size_bytes": {"type": "integer"},
    "exif_data": {
      "type": ["object", "null"],
      "properties": {
        "camera_make": {"type": ["string", "null"]},
        "camera_model": {"type": ["string", "null"]},
        "date_taken": {"type": ["string", "null"], "format": "date-time"},
        "gps_latitude": {"type": ["number", "null"]},
        "gps_longitude": {"type": ["number", "null"]},
        "orientation": {"type": ["integer", "null"]},
        "width": {"type": ["integer", "null"]},
        "height": {"type": ["integer", "null"]}
      }
    },
    "video_metadata": {
      "type": ["object", "null"],
      "properties": {
        "duration_seconds": {"type": "number"},
        "width": {"type": "integer"},
        "height": {"type": "integer"},
        "codec": {"type": ["string", "null"]},
        "fps": {"type": ["number", "null"]},
        "bitrate": {"type": ["integer", "null"]}
      }
    },
    "faces": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "box": {
            "type": "object",
            "properties": {
              "x": {"type": "number"},
              "y": {"type": "number"},
              "width": {"type": "number"},
              "height": {"type": "number"},
              "confidence": {"type": "number"}
            }
          },
          "embedding": {"type": "array", "items": {"type": "number"}},
          "cluster_id": {"type": ["integer", "null"]},
          "person_id": {"type": ["string", "null"]},
          "person_name": {"type": ["string", "null"]}
        }
      }
    },
    "caption": {"type": ["string", "null"]},
    "clip_embedding_id": {"type": ["string", "null"]},
    "transcript": {"type": ["string", "null"]},
    "duplicate_of": {"type": ["string", "null"]},
    "is_master": {"type": "boolean"},
    "status": {"enum": ["uploaded", "processing", "needs_review", "approved", "archived", "duplicate", "error"]},
    "event_name": {"type": ["string", "null"]},
    "tags": {"type": "array", "items": {"type": "string"}},
    "notes": {"type": ["string", "null"]},
    "drive_path": {"type": "string"},
    "thumbnail_path": {"type": ["string", "null"]},
    "processing_errors": {"type": "array", "items": {"type": "string"}},
    "created_at": {"type": "string", "format": "date-time"},
    "updated_at": {"type": "string", "format": "date-time"}
  }
}
```

## AI Models

### InsightFace (Face Detection)
- **Model:** buffalo_l (or configurable)
- **Input:** Image file path
- **Output:** Face bounding boxes + 512-dim embeddings
- **VRAM:** ~1.5GB
- **Provider:** ONNX Runtime (GPU or CPU)

### Moondream2 (Image Captioning)
- **Model:** vikhyatk/moondream2
- **Input:** PIL Image
- **Output:** Text description
- **VRAM:** ~2GB (FP16)
- **Provider:** HuggingFace Transformers

### CLIP (Semantic Embeddings)
- **Model:** clip-ViT-B/32
- **Input:** PIL Image or text
- **Output:** 512-dim embedding
- **VRAM:** ~1GB
- **Provider:** sentence-transformers

### Whisper (Audio Transcription)
- **Model:** base (or tiny/small/medium/large)
- **Input:** Audio file path (or extracted from video)
- **Output:** Text transcript
- **VRAM:** ~1GB (int8 quantization)
- **Provider:** faster-whisper

## Memory Management Strategy

**Problem:** GTX 1650 SUPER has only 4GB VRAM, but models combined require 5-6GB.

**Solution:** Serial model loading with explicit cleanup.

```python
# Process faces
with FaceDetector(use_gpu=True) as detector:
    faces = detector.process(image_path)
# Model automatically unloaded, VRAM freed

# Process caption
with ImageCaptioner(use_gpu=True) as captioner:
    caption = captioner.process(image_path)
# Model automatically unloaded, VRAM freed

# Process embeddings
with CLIPEmbedder(use_gpu=True) as embedder:
    embedding = embedder.process(image_path)
# Model automatically unloaded, VRAM freed
```

**Context manager (`__enter__`/`__exit__`):**
1. Load model on enter
2. Process data
3. On exit: `del self.model`, `torch.cuda.empty_cache()`, `gc.collect()`

**Peak VRAM usage:** ~2GB (largest single model)

## Error Handling

### Worker Resilience

- **Per-asset error handling:** If one asset fails, others continue
- **Errors logged** to sidecar `processing_errors` array
- **Corrupt files skipped:** Never crash entire worker
- **Idempotent:** Safe to re-run on same files

### Intake Resilience

- **Chunked uploads:** Resume from last successful chunk
- **Session storage:** Persists across app restarts
- **Timeouts:** Configurable per chunk
- **Rate limiting:** Prevents abuse

### Drive Resilience

- **Retry logic:** Can add exponential backoff (not in base)
- **Move operations:** Atomic (Drive API handles)
- **Never delete:** Only move files

## Performance Characteristics

### Upload Performance
- **Speed:** Limited by network bandwidth
- **Chunk size:** 10MB default (configurable)
- **Parallel:** Multiple users can upload simultaneously

### Processing Performance
- **Face detection:** ~2-3 seconds per image (GPU)
- **Captioning:** ~3-5 seconds per image (GPU)
- **CLIP:** ~1-2 seconds per image (GPU)
- **Whisper:** ~0.3x realtime (8min video = 2.5min processing)

**Total per image:** ~10-15 seconds (GPU) or ~30-60 seconds (CPU)

### Scaling
- **Bottleneck:** Worker processing (single-threaded per asset)
- **Solution:** Run multiple workers (see DEPLOYMENT.md)
- **Database:** SQLite adequate up to ~100K assets

## Security Model

### Upload Security
- **Token-based:** Secret URLs, not guessable
- **No auth:** Simple "secret link" model
- **Rate limiting:** Prevents spam
- **File type validation:** Only images/videos/audio
- **Size limits:** Configurable max size

### Service Account
- **Principle of least privilege:** Only Drive access
- **Read/Write:** Editor on Family_Archive folder only
- **Key storage:** Local file, never committed to git

### Data Privacy
- **Local AI:** No data sent to cloud services
- **Originals immutable:** Never modified
- **Encryption:** Google Drive encryption at rest
- **Access control:** Service account + token holders only

## Extension Points

### Add New AI Model

1. Create processor in `worker/processors/`:
   ```python
   class NewProcessor(BaseProcessor):
       def load_model(self):
           # Load model

       def process(self, input):
           # Process and return results
   ```

2. Add to worker pipeline in `worker/main.py`

3. Add fields to sidecar model in `shared/models.py`

4. Update database schema in `shared/database.py`

### Add New Upload Source

1. Create route in `intake_webapp/main.py`
2. Follow same flow: init → chunks → finish
3. Generate manifest

### Add New Dashboard View

1. Create function in `curator/main.py`
2. Add to sidebar navigation
3. Query database and render with Streamlit

### Add New Static Page

1. Add generator function in `rosetta/main.py`
2. Call from `generate()` method
3. Link from navigation

---

**Last Updated:** 2025-01-23
