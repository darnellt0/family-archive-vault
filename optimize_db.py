import sqlite3
import os

# Path to your database
DB_PATH = r'F:\FamilyArchive\data\archive.db'

def create_indexes():
    """
    Creates indexes on frequently queried columns to improve search and filtering performance.
    """
    if not os.path.exists(DB_PATH):
        # For simulation/testing in sandbox
        db_dir = os.path.dirname(DB_PATH)
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)
        print(f"Warning: {DB_PATH} not found. Creating a mock database for script verification.")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("Starting database optimization...")
    
    # List of indexes to create
    # Format: (index_name, table_name, column_name)
    indexes = [
        ('idx_media_status', 'media', 'status'),
        ('idx_media_date_taken', 'media', 'date_taken'),
        ('idx_media_phash', 'media', 'phash'),
        ('idx_media_uploaded_date', 'media', 'uploaded_date'),
        ('idx_share_links_token', 'share_links', 'token'),
        ('idx_faces_media_id', 'faces', 'media_id'),
        ('idx_faces_cluster_id', 'faces', 'cluster_id')
    ]
    
    for idx_name, table, col in indexes:
        try:
            # Check if table exists before indexing
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if cursor.fetchone():
                cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({col})")
                print(f"Successfully indexed {table}({col})")
            else:
                print(f"Skipping index for {table}: Table does not exist yet.")
        except sqlite3.OperationalError as e:
            print(f"Error creating index {idx_name}: {e}")
            
    # Run VACUUM to defragment the database and reduce file size
    print("Running VACUUM to optimize storage...")
    conn.execute("VACUUM")
    
    # Run ANALYZE to help the query planner make better decisions
    print("Running ANALYZE to optimize query planning...")
    conn.execute("ANALYZE")
    
    conn.commit()
    conn.close()
    print("Database optimization complete.")

if __name__ == "__main__":
    create_indexes()
