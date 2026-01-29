import sqlite3

DB_PATH = r'F:\FamilyArchive\data\archive.db'

def fix_schema():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # List of columns that should exist in the 'media' table
    required_columns = [
        ('ai_caption', 'TEXT'),
        ('clip_embedding', 'BLOB'),
        ('phash', 'TEXT'),
        ('date_taken', 'TEXT'),
        ('camera_make', 'TEXT'),
        ('camera_model', 'TEXT')
    ]
    
    for col_name, col_type in required_columns:
        try:
            cursor.execute(f"ALTER TABLE media ADD COLUMN {col_name} {col_type}")
            print(f"Added column: {col_name}")
        except sqlite3.OperationalError:
            print(f"Column already exists: {col_name}")
            
    conn.commit()
    conn.close()
    print("Schema fix complete.")

if __name__ == "__main__":
    fix_schema()
