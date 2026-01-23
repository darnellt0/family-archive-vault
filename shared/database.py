"""Database models and operations for Family Archive Vault."""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    create_engine, Column, String, Integer, Float, Boolean,
    DateTime, Text, ForeignKey, Index, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from loguru import logger
import json

Base = declarative_base()


class Asset(Base):
    """Main asset table."""
    __tablename__ = 'assets'

    asset_id = Column(String, primary_key=True)
    sha256 = Column(String, nullable=False, index=True)
    phash = Column(String, index=True)

    # Origin
    drive_file_id = Column(String, unique=True, nullable=False, index=True)
    original_filename = Column(String, nullable=False)
    contributor_token = Column(String, nullable=False, index=True)
    batch_id = Column(String, ForeignKey('batches.batch_id'), index=True)

    # Type
    asset_type = Column(String, nullable=False, index=True)
    mime_type = Column(String)
    file_size_bytes = Column(Integer)

    # Dates
    upload_timestamp = Column(DateTime, nullable=False)
    exif_date = Column(DateTime, index=True)
    estimated_date = Column(DateTime, index=True)
    decade = Column(Integer, index=True)

    # Status
    status = Column(String, nullable=False, default='uploaded', index=True)
    duplicate_of = Column(String, ForeignKey('assets.asset_id'))
    is_master = Column(Boolean, default=True)

    # Curation
    event_name = Column(String, index=True)
    tags = Column(JSON)
    notes = Column(Text)
    approved_by = Column(String)
    approved_at = Column(DateTime)

    # AI Metadata
    caption = Column(Text)
    clip_embedding_id = Column(String)
    transcript = Column(Text)

    # Paths
    drive_path = Column(String)
    thumbnail_path = Column(String)
    sidecar_path = Column(String)

    # Geo
    gps_latitude = Column(Float)
    gps_longitude = Column(Float)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    faces = relationship("Face", back_populates="asset", cascade="all, delete-orphan")
    batch = relationship("Batch", back_populates="assets")

    __table_args__ = (
        Index('idx_status_date', 'status', 'estimated_date'),
        Index('idx_decade_status', 'decade', 'status'),
    )


class Batch(Base):
    """Upload batch table."""
    __tablename__ = 'batches'

    batch_id = Column(String, primary_key=True)
    contributor_token = Column(String, nullable=False, index=True)
    contributor_folder = Column(String)

    # Context
    decade = Column(Integer)
    event_name = Column(String)
    notes = Column(Text)
    voice_note_file_id = Column(String)

    # Stats
    total_files = Column(Integer, default=0)
    total_bytes = Column(Integer, default=0)
    processed_files = Column(Integer, default=0)

    # Timestamps
    upload_start = Column(DateTime, nullable=False)
    upload_end = Column(DateTime)
    processing_completed = Column(DateTime)

    # Relationships
    assets = relationship("Asset", back_populates="batch")


class Face(Base):
    """Detected face table."""
    __tablename__ = 'faces'

    face_id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(String, ForeignKey('assets.asset_id'), nullable=False, index=True)

    # Detection
    box_x = Column(Float, nullable=False)
    box_y = Column(Float, nullable=False)
    box_width = Column(Float, nullable=False)
    box_height = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)

    # Clustering & Identity
    cluster_id = Column(Integer, ForeignKey('clusters.cluster_id'), index=True)
    person_id = Column(String, index=True)
    person_name = Column(String, index=True)

    # Embedding (stored as JSON array)
    embedding = Column(JSON, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    asset = relationship("Asset", back_populates="faces")
    cluster = relationship("Cluster", back_populates="faces")


class Cluster(Base):
    """Face cluster table."""
    __tablename__ = 'clusters'

    cluster_id = Column(Integer, primary_key=True)
    person_id = Column(String, unique=True, index=True)
    person_name = Column(String, index=True)

    face_count = Column(Integer, default=0)
    confidence_score = Column(Float)

    # Sample faces for preview (JSON array of asset_ids)
    sample_asset_ids = Column(JSON)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    faces = relationship("Face", back_populates="cluster")


class ClipEmbedding(Base):
    """CLIP embedding table for semantic search."""
    __tablename__ = 'clip_embeddings'

    embedding_id = Column(String, primary_key=True)
    asset_id = Column(String, ForeignKey('assets.asset_id'), nullable=False, index=True)

    # Embedding (stored as JSON array for simplicity; could use pgvector in production)
    embedding = Column(JSON, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)


class Duplicate(Base):
    """Duplicate tracking table."""
    __tablename__ = 'duplicates'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False, index=True)
    master_asset_id = Column(String, ForeignKey('assets.asset_id'), nullable=False)
    duplicate_asset_id = Column(String, ForeignKey('assets.asset_id'), nullable=False)

    similarity_score = Column(Float, nullable=False)
    similarity_type = Column(String, nullable=False)  # 'exact' or 'near'

    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_duplicate_unresolved', 'resolved', 'group_id'),
    )


class Review(Base):
    """Review actions history."""
    __tablename__ = 'reviews'

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(String, ForeignKey('assets.asset_id'), nullable=False, index=True)

    action = Column(String, nullable=False)  # 'approve', 'reject', 'tag', 'name_person', etc.
    reviewer = Column(String)
    notes = Column(Text)

    # Changes made (JSON)
    changes = Column(JSON)

    created_at = Column(DateTime, default=datetime.utcnow)


class DatabaseManager:
    """Database manager for Family Archive Vault."""

    def __init__(self, db_path: str):
        """Initialize database connection."""
        self.db_path = db_path
        self.engine = create_engine(f'sqlite:///{db_path}', echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def init_db(self):
        """Create all tables."""
        Base.metadata.create_all(self.engine)
        logger.info(f"Database initialized at {self.db_path}")

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    def upsert_asset(self, sidecar_data: dict) -> Asset:
        """Insert or update an asset from sidecar data."""
        session = self.get_session()
        try:
            asset = session.query(Asset).filter_by(
                drive_file_id=sidecar_data['drive_file_id']
            ).first()

            if asset:
                # Update existing
                for key, value in sidecar_data.items():
                    if key not in ['faces', 'asset_id'] and hasattr(asset, key):
                        setattr(asset, key, value)
                asset.updated_at = datetime.utcnow()
            else:
                # Create new
                asset_dict = {k: v for k, v in sidecar_data.items() if k != 'faces'}
                asset = Asset(**asset_dict)
                session.add(asset)

            session.commit()
            session.refresh(asset)
            return asset
        except Exception as e:
            session.rollback()
            logger.error(f"Error upserting asset: {e}")
            raise
        finally:
            session.close()

    def upsert_faces(self, asset_id: str, faces_data: List[dict]):
        """Insert or update faces for an asset."""
        session = self.get_session()
        try:
            # Delete existing faces for this asset
            session.query(Face).filter_by(asset_id=asset_id).delete()

            # Insert new faces
            for face_data in faces_data:
                face = Face(
                    asset_id=asset_id,
                    box_x=face_data['box']['x'],
                    box_y=face_data['box']['y'],
                    box_width=face_data['box']['width'],
                    box_height=face_data['box']['height'],
                    confidence=face_data['box']['confidence'],
                    embedding=face_data['embedding'],
                    cluster_id=face_data.get('cluster_id'),
                    person_id=face_data.get('person_id'),
                    person_name=face_data.get('person_name')
                )
                session.add(face)

            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Error upserting faces: {e}")
            raise
        finally:
            session.close()

    def get_assets_by_status(self, status: str, limit: Optional[int] = None) -> List[Asset]:
        """Get assets by status."""
        session = self.get_session()
        try:
            query = session.query(Asset).filter_by(status=status)
            if limit:
                query = query.limit(limit)
            return query.all()
        finally:
            session.close()

    def get_unprocessed_assets(self, limit: int = 10) -> List[Asset]:
        """Get assets that need processing."""
        session = self.get_session()
        try:
            return session.query(Asset).filter(
                Asset.status.in_(['uploaded', 'processing'])
            ).limit(limit).all()
        finally:
            session.close()

    def mark_duplicate(self, duplicate_asset_id: str, master_asset_id: str,
                       similarity_score: float, similarity_type: str, group_id: str):
        """Mark an asset as a duplicate."""
        session = self.get_session()
        try:
            # Update asset
            asset = session.query(Asset).filter_by(asset_id=duplicate_asset_id).first()
            if asset:
                asset.duplicate_of = master_asset_id
                asset.is_master = False
                asset.status = 'duplicate'

            # Add to duplicates table
            duplicate = Duplicate(
                group_id=group_id,
                master_asset_id=master_asset_id,
                duplicate_asset_id=duplicate_asset_id,
                similarity_score=similarity_score,
                similarity_type=similarity_type
            )
            session.add(duplicate)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Error marking duplicate: {e}")
            raise
        finally:
            session.close()

    def get_duplicates(self, resolved: bool = False) -> List[Duplicate]:
        """Get duplicate groups."""
        session = self.get_session()
        try:
            return session.query(Duplicate).filter_by(resolved=resolved).all()
        finally:
            session.close()
