from services.worker.db import init_db, get_conn

if __name__ == "__main__":
    init_db()
    conn = get_conn()
    assets = conn.execute("SELECT COUNT(*) AS count FROM assets").fetchone()["count"]
    media = conn.execute("SELECT COUNT(*) AS count FROM media").fetchone()["count"]
    conn.close()
    print(f"Assets: {assets}")
    print(f"Media: {media}")
