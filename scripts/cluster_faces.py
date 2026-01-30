"""Script to cluster face embeddings using HDBSCAN."""
import sys
from pathlib import Path
import numpy as np
from sklearn.preprocessing import normalize
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.config import get_settings
from shared.database import DatabaseManager, Face, Cluster


def cluster_faces():
    """Cluster face embeddings to identify recurring people."""
    logger.info("Starting face clustering...")

    settings = get_settings()
    db = DatabaseManager(settings.local_db_path)

    session = db.get_session()
    try:
        # Get all faces with embeddings
        faces = session.query(Face).filter(Face.embedding.isnot(None)).all()

        if len(faces) < settings.face_cluster_min_samples:
            logger.warning(f"Only {len(faces)} faces found. Need at least {settings.face_cluster_min_samples} for clustering.")
            return

        logger.info(f"Clustering {len(faces)} faces...")

        # Extract embeddings
        embeddings = np.array([face.embedding for face in faces])

        # Normalize embeddings
        embeddings = normalize(embeddings, norm='l2')

        # Cluster with HDBSCAN
        import hdbscan

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=settings.face_cluster_min_samples,
            min_samples=2,
            metric='euclidean',
            cluster_selection_method='eom'
        )

        cluster_labels = clusterer.fit_predict(embeddings)

        # Update faces with cluster assignments
        unique_clusters = set(cluster_labels)
        unique_clusters.discard(-1)  # Remove noise label

        logger.info(f"Found {len(unique_clusters)} clusters")

        for cluster_id in unique_clusters:
            # Get faces in this cluster
            cluster_mask = cluster_labels == cluster_id
            cluster_face_ids = [faces[i].face_id for i, mask in enumerate(cluster_mask) if mask]
            cluster_asset_ids = list(set([faces[i].asset_id for i, mask in enumerate(cluster_mask) if mask]))

            # Update or create cluster
            cluster = session.query(Cluster).filter_by(cluster_id=int(cluster_id)).first()
            if not cluster:
                cluster = Cluster(
                    cluster_id=int(cluster_id),
                    face_count=len(cluster_face_ids),
                    sample_asset_ids=cluster_asset_ids[:10]
                )
                session.add(cluster)
            else:
                cluster.face_count = len(cluster_face_ids)
                cluster.sample_asset_ids = cluster_asset_ids[:10]

            # Update face assignments
            for i, mask in enumerate(cluster_mask):
                if mask:
                    faces[i].cluster_id = int(cluster_id)

            logger.info(f"Cluster {cluster_id}: {len(cluster_face_ids)} faces across {len(cluster_asset_ids)} photos")

        session.commit()
        logger.info("✓ Face clustering complete!")

    except Exception as e:
        session.rollback()
        logger.error(f"Error clustering faces: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    cluster_faces()
