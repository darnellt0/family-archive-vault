import sqlite3
import numpy as np
from sklearn.cluster import DBSCAN
import json

# --- CONFIGURATION ---
DB_PATH = r'F:\FamilyArchive\data\archive.db'

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def cluster_faces():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch all faces and their embeddings
    faces = cursor.execute("SELECT id, embedding FROM faces").fetchall()
    
    if not faces:
        print("No faces found to cluster.")
        return
        
    ids = [f[0] for f in faces]
    embeddings = [np.frombuffer(f[1], dtype=np.float32) for f in faces]
    
    print(f"Clustering {len(embeddings)} faces...")
    
    # Use DBSCAN for clustering (doesn't require knowing number of clusters)
    # eps and min_samples may need tuning based on InsightFace embedding space
    clustering = DBSCAN(eps=0.6, min_samples=3, metric='cosine').fit(embeddings)
    labels = clustering.labels_
    
    # Update database with cluster IDs
    for face_id, label in zip(ids, labels):
        cursor.execute("UPDATE faces SET cluster_id = ? WHERE id = ?", (int(label), face_id))
    
    # Create entries in clusters table for new clusters
    unique_labels = set(labels)
    for label in unique_labels:
        if label == -1: continue # Skip noise
        
        # Check if cluster already exists
        exists = cursor.execute("SELECT id FROM clusters WHERE id = ?", (int(label),)).fetchone()
        if not exists:
            # Find a representative face (the first one in the cluster)
            rep_face = cursor.execute("SELECT id FROM faces WHERE cluster_id = ? LIMIT 1", (int(label),)).fetchone()
            cursor.execute('''
                INSERT INTO clusters (id, name, representative_face_id)
                VALUES (?, ?, ?)
            ''', (int(label), f"Person {label}", rep_face[0]))
            
    conn.commit()
    conn.close()
    print("Clustering complete.")

if __name__ == "__main__":
    cluster_faces()
