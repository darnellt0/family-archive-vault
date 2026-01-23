"""Streamlit curator dashboard."""
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List
import streamlit as st
from PIL import Image
import pandas as pd
import numpy as np

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.config import get_settings
from shared.drive_client import DriveClient
from shared.database import DatabaseManager, Asset, Face, Cluster, Duplicate
from shared.models import AssetStatus


# Page configuration
st.set_page_config(
    page_title="Family Archive Curator",
    page_icon="📸",
    layout="wide"
)


@st.cache_resource
def get_clients():
    """Initialize clients (cached)."""
    settings = get_settings()
    db = DatabaseManager(settings.local_db_path)
    drive = DriveClient(settings.service_account_json_path, settings.drive_root_folder_id)
    return settings, db, drive


def main():
    """Main dashboard."""
    st.title("📸 Family Archive Curator")

    settings, db, drive = get_clients()

    # Sidebar navigation
    page = st.sidebar.selectbox(
        "Navigation",
        ["Overview", "Review Queue", "Duplicates", "People Clusters", "Search"]
    )

    if page == "Overview":
        show_overview(db)
    elif page == "Review Queue":
        show_review_queue(db, drive, settings)
    elif page == "Duplicates":
        show_duplicates(db, settings)
    elif page == "People Clusters":
        show_people_clusters(db, settings)
    elif page == "Search":
        show_search(db, settings)


def show_overview(db: DatabaseManager):
    """Show overview statistics."""
    st.header("Archive Overview")

    session = db.get_session()
    try:
        # Total assets
        total_assets = session.query(Asset).count()
        pending_review = session.query(Asset).filter_by(status='needs_review').count()
        approved = session.query(Asset).filter_by(status='approved').count()
        archived = session.query(Asset).filter_by(status='archived').count()
        duplicates = session.query(Asset).filter_by(status='duplicate').count()

        # Display metrics
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total Assets", total_assets)
        col2.metric("Pending Review", pending_review)
        col3.metric("Approved", approved)
        col4.metric("Archived", archived)
        col5.metric("Duplicates", duplicates)

        # Recent uploads
        st.subheader("Recent Uploads")
        recent = session.query(Asset).order_by(Asset.created_at.desc()).limit(20).all()

        if recent:
            data = []
            for asset in recent:
                data.append({
                    "Filename": asset.original_filename,
                    "Type": asset.asset_type,
                    "Status": asset.status,
                    "Decade": asset.decade,
                    "Faces": len(asset.faces) if asset.faces else 0,
                    "Uploaded": asset.created_at.strftime("%Y-%m-%d %H:%M")
                })

            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No assets yet")

        # Face statistics
        st.subheader("Face Detection Statistics")
        total_faces = session.query(Face).count()
        clustered_faces = session.query(Face).filter(Face.cluster_id.isnot(None)).count()
        named_faces = session.query(Face).filter(Face.person_name.isnot(None)).count()

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Faces Detected", total_faces)
        col2.metric("Clustered", clustered_faces)
        col3.metric("Named", named_faces)

    finally:
        session.close()


def show_review_queue(db: DatabaseManager, drive: DriveClient, settings):
    """Show review queue."""
    st.header("Review Queue")

    session = db.get_session()
    try:
        # Get unreviewed assets
        assets = session.query(Asset).filter_by(status='needs_review').order_by(Asset.created_at.desc()).all()

        if not assets:
            st.success("✓ All assets reviewed!")
            return

        st.info(f"{len(assets)} assets awaiting review")

        # Pagination
        items_per_page = 10
        page = st.number_input("Page", min_value=1, max_value=max(1, len(assets) // items_per_page + 1), value=1)
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page

        for asset in assets[start_idx:end_idx]:
            with st.expander(f"📄 {asset.original_filename}", expanded=True):
                col1, col2 = st.columns([1, 2])

                with col1:
                    # Show thumbnail
                    if asset.thumbnail_path and Path(asset.thumbnail_path).exists():
                        st.image(str(asset.thumbnail_path), use_column_width=True)
                    else:
                        st.info("No preview available")

                with col2:
                    # Metadata
                    st.write(f"**Type:** {asset.asset_type}")
                    st.write(f"**Size:** {asset.file_size_bytes / 1024 / 1024:.2f} MB")
                    st.write(f"**Uploaded:** {asset.created_at.strftime('%Y-%m-%d %H:%M')}")

                    if asset.exif_date:
                        st.write(f"**Date Taken:** {asset.exif_date.strftime('%Y-%m-%d')}")

                    if asset.decade:
                        st.write(f"**Decade:** {asset.decade}s")

                    if asset.caption:
                        st.write(f"**AI Caption:** {asset.caption}")

                    if asset.faces:
                        st.write(f"**Faces Detected:** {len(asset.faces)}")

                    if asset.transcript:
                        st.text_area("Transcript", asset.transcript, height=100, key=f"transcript_{asset.asset_id}")

                # Curation form
                st.write("---")
                col1, col2, col3 = st.columns(3)

                with col1:
                    decade = st.selectbox(
                        "Decade",
                        [None, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020],
                        index=0 if not asset.decade else [None, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020].index(asset.decade),
                        key=f"decade_{asset.asset_id}"
                    )

                with col2:
                    event_name = st.text_input(
                        "Event Name",
                        value=asset.event_name or "",
                        key=f"event_{asset.asset_id}"
                    )

                with col3:
                    tags = st.text_input(
                        "Tags (comma-separated)",
                        value=", ".join(asset.tags) if asset.tags else "",
                        key=f"tags_{asset.asset_id}"
                    )

                notes = st.text_area(
                    "Notes",
                    value=asset.notes or "",
                    key=f"notes_{asset.asset_id}"
                )

                # Action buttons
                col1, col2, col3 = st.columns(3)

                with col1:
                    if st.button("✓ Approve & Archive", key=f"approve_{asset.asset_id}", type="primary"):
                        approve_asset(db, drive, asset, decade, event_name, tags, notes, settings)
                        st.success("Asset approved and archived!")
                        st.rerun()

                with col2:
                    if st.button("⏭ Skip", key=f"skip_{asset.asset_id}"):
                        st.info("Skipped")

                with col3:
                    if st.button("🗑 Mark as Low Quality", key=f"lowq_{asset.asset_id}"):
                        mark_low_quality(db, drive, asset)
                        st.warning("Marked as low quality")
                        st.rerun()

    finally:
        session.close()


def approve_asset(db: DatabaseManager, drive: DriveClient, asset: Asset, decade: int, event_name: str, tags: str, notes: str, settings):
    """Approve an asset and move to archive."""
    session = db.get_session()
    try:
        # Update metadata
        asset.decade = decade
        asset.event_name = event_name
        asset.tags = [t.strip() for t in tags.split(",")] if tags else []
        asset.notes = notes
        asset.status = 'archived'
        asset.approved_by = "curator"
        asset.approved_at = datetime.utcnow()

        # Move in Drive
        archive_id = drive.get_or_create_folder("ARCHIVE")

        if asset.asset_type == 'video':
            videos_id = drive.get_or_create_folder("Videos", archive_id)
            decade_folder = f"{decade}s" if decade else "Unknown"
            decade_id = drive.get_or_create_folder(decade_folder, videos_id)
        else:
            originals_id = drive.get_or_create_folder("Originals", archive_id)
            decade_folder = f"{decade}s" if decade else "Unknown"
            decade_id = drive.get_or_create_folder(decade_folder, originals_id)

        drive.move_file(asset.drive_file_id, decade_id)

        session.commit()

    except Exception as e:
        session.rollback()
        st.error(f"Error approving asset: {e}")
    finally:
        session.close()


def mark_low_quality(db: DatabaseManager, drive: DriveClient, asset: Asset):
    """Mark asset as low quality."""
    session = db.get_session()
    try:
        asset.status = 'needs_review'
        asset.tags = asset.tags or []
        if 'low_quality' not in asset.tags:
            asset.tags.append('low_quality')

        # Move to Low_Confidence folder
        holding_id = drive.get_or_create_folder("HOLDING")
        low_conf_id = drive.get_or_create_folder("Low_Confidence", holding_id)
        drive.move_file(asset.drive_file_id, low_conf_id)

        session.commit()
    except Exception as e:
        session.rollback()
        st.error(f"Error marking low quality: {e}")
    finally:
        session.close()


def show_duplicates(db: DatabaseManager, settings):
    """Show and resolve duplicates."""
    st.header("Duplicate Management")

    session = db.get_session()
    try:
        duplicates = session.query(Duplicate).filter_by(resolved=False).all()

        if not duplicates:
            st.success("✓ No unresolved duplicates")
            return

        st.info(f"{len(duplicates)} potential duplicate pairs")

        for dup in duplicates[:10]:  # Show first 10
            master = session.query(Asset).filter_by(asset_id=dup.master_asset_id).first()
            duplicate = session.query(Asset).filter_by(asset_id=dup.duplicate_asset_id).first()

            if not master or not duplicate:
                continue

            st.write("---")
            col1, col2, col3 = st.columns(3)

            with col1:
                st.write("**Master**")
                if master.thumbnail_path and Path(master.thumbnail_path).exists():
                    st.image(str(master.thumbnail_path), use_column_width=True)
                st.write(master.original_filename)
                st.write(f"Size: {master.file_size_bytes / 1024 / 1024:.2f} MB")

            with col2:
                st.write("**Duplicate**")
                if duplicate.thumbnail_path and Path(duplicate.thumbnail_path).exists():
                    st.image(str(duplicate.thumbnail_path), use_column_width=True)
                st.write(duplicate.original_filename)
                st.write(f"Size: {duplicate.file_size_bytes / 1024 / 1024:.2f} MB")

            with col3:
                st.write("**Actions**")
                st.write(f"Similarity: {dup.similarity_score:.2%}")
                st.write(f"Type: {dup.similarity_type}")

                if st.button("✓ Confirm Duplicate", key=f"confirm_{dup.id}"):
                    dup.resolved = True
                    dup.resolved_at = datetime.utcnow()
                    session.commit()
                    st.success("Marked as duplicate")
                    st.rerun()

                if st.button("✗ Not a Duplicate", key=f"reject_{dup.id}"):
                    duplicate.duplicate_of = None
                    duplicate.is_master = True
                    duplicate.status = 'needs_review'
                    dup.resolved = True
                    dup.resolved_at = datetime.utcnow()
                    session.commit()
                    st.success("Marked as unique")
                    st.rerun()

    finally:
        session.close()


def show_people_clusters(db: DatabaseManager, settings):
    """Show and manage face clusters."""
    st.header("People & Faces")

    session = db.get_session()
    try:
        clusters = session.query(Cluster).order_by(Cluster.face_count.desc()).all()

        if not clusters:
            st.info("No face clusters yet. Run face clustering to organize detected faces.")
            return

        st.info(f"{len(clusters)} face clusters detected")

        # Tabs for named vs unnamed
        tab1, tab2 = st.tabs(["Unnamed Clusters", "Named People"])

        with tab1:
            unnamed = [c for c in clusters if not c.person_name]
            st.write(f"{len(unnamed)} unnamed clusters")

            for cluster in unnamed[:20]:  # Show first 20
                with st.expander(f"Cluster #{cluster.cluster_id} ({cluster.face_count} faces)"):
                    # Show sample faces
                    if cluster.sample_asset_ids:
                        cols = st.columns(min(5, len(cluster.sample_asset_ids)))
                        for i, asset_id in enumerate(cluster.sample_asset_ids[:5]):
                            asset = session.query(Asset).filter_by(asset_id=asset_id).first()
                            if asset and asset.thumbnail_path and Path(asset.thumbnail_path).exists():
                                cols[i].image(str(asset.thumbnail_path), use_column_width=True)

                    # Name input
                    person_name = st.text_input(
                        "Person Name",
                        key=f"name_cluster_{cluster.cluster_id}"
                    )

                    if st.button("Save Name", key=f"save_cluster_{cluster.cluster_id}"):
                        if person_name:
                            cluster.person_name = person_name
                            cluster.person_id = person_name.lower().replace(" ", "_")

                            # Update all faces in this cluster
                            faces = session.query(Face).filter_by(cluster_id=cluster.cluster_id).all()
                            for face in faces:
                                face.person_name = person_name
                                face.person_id = cluster.person_id

                            session.commit()
                            st.success(f"Named cluster as {person_name}")
                            st.rerun()

        with tab2:
            named = [c for c in clusters if c.person_name]
            st.write(f"{len(named)} named people")

            for cluster in named:
                with st.expander(f"{cluster.person_name} ({cluster.face_count} photos)"):
                    # Show sample faces
                    if cluster.sample_asset_ids:
                        cols = st.columns(min(5, len(cluster.sample_asset_ids)))
                        for i, asset_id in enumerate(cluster.sample_asset_ids[:5]):
                            asset = session.query(Asset).filter_by(asset_id=asset_id).first()
                            if asset and asset.thumbnail_path and Path(asset.thumbnail_path).exists():
                                cols[i].image(str(asset.thumbnail_path), use_column_width=True)

    finally:
        session.close()


def show_search(db: DatabaseManager, settings):
    """Search interface."""
    st.header("Search Archive")

    search_query = st.text_input("Search by filename, caption, or transcript")

    if search_query:
        session = db.get_session()
        try:
            # Simple text search
            results = session.query(Asset).filter(
                (Asset.original_filename.contains(search_query)) |
                (Asset.caption.contains(search_query)) |
                (Asset.transcript.contains(search_query))
            ).limit(50).all()

            st.write(f"Found {len(results)} results")

            # Display results
            cols = st.columns(4)
            for i, asset in enumerate(results):
                with cols[i % 4]:
                    if asset.thumbnail_path and Path(asset.thumbnail_path).exists():
                        st.image(str(asset.thumbnail_path), use_column_width=True)
                    st.caption(asset.original_filename)
                    if asset.caption:
                        st.caption(asset.caption[:100] + "...")

        finally:
            session.close()


if __name__ == "__main__":
    main()
