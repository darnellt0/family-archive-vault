import sqlite3
conn = sqlite3.connect(r"F:\FamilyArchive\data\archive.db")

# Check tables
print("=== TABLES ===")
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
for t in tables:
    print(t[0])

# Check media table contents
print("\n=== MEDIA TABLE ===")
try:
    cursor = conn.execute("SELECT * FROM media;")
    rows = cursor.fetchall()
    print(f"Rows: {len(rows)}")
    for row in rows:
        print(row)
except Exception as e:
    print(f"Error: {e}")

conn.close()
