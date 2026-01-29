import sqlite3
import numpy as np
from sentence_transformers import SentenceTransformer
import torch

DB_PATH = r'F:\FamilyArchive\data\archive.db'

def semantic_search(query, top_k=20):
    """
    Perform semantic search on the archive.
    
    Args:
        query (str): Natural language search query (e.g., "family at the beach")
        top_k (int): Number of results to return
    
    Returns:
        list: List of (drive_id, similarity_score) tuples
    """
    # Load model
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer('clip-ViT-B-32', device=device)
    
    # Encode query
    query_embedding = model.encode(query)
    
    # Retrieve embeddings from database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    items = cursor.execute('''
        SELECT drive_id, clip_embedding FROM media 
        WHERE clip_embedding IS NOT NULL AND clip_embedding != X'6661696c6564'
        AND status = 'approved'
    ''').fetchall()
    
    conn.close()
    
    # Calculate similarity scores
    results = []
    for drive_id, embedding_blob in items:
        try:
            embedding = np.frombuffer(embedding_blob, dtype=np.float32)
            # Cosine similarity
            similarity = np.dot(query_embedding, embedding) / (np.linalg.norm(query_embedding) * np.linalg.norm(embedding))
            results.append((drive_id, similarity))
        except Exception as e:
            print(f"Error processing embedding for {drive_id}: {e}")
    
    # Sort by similarity and return top_k
    results.sort(key=lambda x: x[1], reverse=True)
    
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    
    return results[:top_k]

if __name__ == "__main__":
    # Test
    results = semantic_search("family gathering")
    for drive_id, score in results:
        print(f"{drive_id}: {score:.4f}")
