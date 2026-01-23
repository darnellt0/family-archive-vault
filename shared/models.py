"""Data models for Family Archive Vault."""
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field
import uuid


class AssetStatus(str, Enum):
    """Status of an asset in the processing pipeline."""
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    ARCHIVED = "archived"
    DUPLICATE = "duplicate"
    ERROR = "error"


class AssetType(str, Enum):
    """Type of media asset."""
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class FaceBox(BaseModel):
    """Bounding box for a detected face."""
    x: float
    y: float
    width: float
    height: float
    confidence: float


class DetectedFace(BaseModel):
    """A detected face with embedding."""
    box: FaceBox
    embedding: List[float]
    cluster_id: Optional[int] = None
    person_id: Optional[str] = None
    person_name: Optional[str] = None


class ExifData(BaseModel):
    """EXIF metadata extracted from images."""
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    date_taken: Optional[datetime] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    orientation: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    raw_exif: Optional[Dict[str, Any]] = None


class VideoMetadata(BaseModel):
    """Metadata for video files."""
    duration_seconds: float
    width: int
    height: int
    codec: Optional[str] = None
    fps: Optional[float] = None
    bitrate: Optional[int] = None


class AssetSidecar(BaseModel):
    """Sidecar JSON metadata for an asset."""

    # Identity
    asset_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sha256: str
    phash: Optional[str] = None  # For images only

    # Origin
    drive_file_id: str
    original_filename: str
    contributor_token: str
    batch_id: str
    upload_timestamp: datetime

    # Type & Format
    asset_type: AssetType
    mime_type: str
    file_size_bytes: int

    # Dates
    exif_date: Optional[datetime] = None
    estimated_date: Optional[datetime] = None
    decade: Optional[int] = None

    # Location
    exif_data: Optional[ExifData] = None

    # Video-specific
    video_metadata: Optional[VideoMetadata] = None

    # AI-generated metadata
    faces: List[DetectedFace] = Field(default_factory=list)
    caption: Optional[str] = None
    clip_embedding_id: Optional[str] = None
    transcript: Optional[str] = None

    # Duplicates
    duplicate_of: Optional[str] = None  # Reference to master asset_id
    is_master: bool = True

    # Workflow
    status: AssetStatus = AssetStatus.UPLOADED
    processing_errors: List[str] = Field(default_factory=list)

    # Curation
    event_name: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None

    # Review history
    review_history: List[Dict[str, Any]] = Field(default_factory=list)

    # Paths
    drive_path: str  # Current path in Drive
    thumbnail_path: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class UploadManifest(BaseModel):
    """Manifest for a batch upload."""
    batch_id: str = Field(default_factory=lambda: f"batch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}")
    contributor_token: str
    contributor_folder: str

    # Optional user-provided context
    decade: Optional[int] = None
    event_name: Optional[str] = None
    notes: Optional[str] = None
    voice_note_file_id: Optional[str] = None

    # Upload tracking
    uploaded_files: List[Dict[str, str]] = Field(default_factory=list)  # [{drive_file_id, filename, mime_type}]
    upload_start: datetime = Field(default_factory=datetime.utcnow)
    upload_end: Optional[datetime] = None

    # Stats
    total_files: int = 0
    total_bytes: int = 0


class FaceCluster(BaseModel):
    """A cluster of similar faces."""
    cluster_id: int
    person_id: Optional[str] = None
    person_name: Optional[str] = None
    face_count: int
    sample_asset_ids: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    confidence_score: Optional[float] = None


class DuplicateGroup(BaseModel):
    """Group of duplicate or near-duplicate assets."""
    group_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    master_asset_id: str
    duplicate_asset_ids: List[str]
    similarity_score: float
    similarity_type: str  # "exact" or "near"
