import sqlite3
import secrets
import hashlib
from datetime import datetime, timedelta

DB_PATH = r'F:\FamilyArchive\data\archive.db'

def create_share_table():
    """Create the sharing links table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS share_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_date TEXT NOT NULL,
            expires_date TEXT,
            access_type TEXT DEFAULT 'view',
            is_active BOOLEAN DEFAULT 1,
            view_count INTEGER DEFAULT 0
        )
    ''')
    
    conn.commit()
    conn.close()

def generate_share_link(name, expires_days=30, access_type='view'):
    """
    Generate a secure sharing link.
    
    Args:
        name (str): Name/description of the share (e.g., "Grandma's Birthday")
        expires_days (int): Days until the link expires (None = never)
        access_type (str): 'view' or 'download'
    
    Returns:
        str: The shareable token
    """
    create_share_table()
    
    # Generate a secure random token
    token = secrets.token_urlsafe(32)
    
    created_date = datetime.now().isoformat()
    expires_date = None
    if expires_days:
        expires_date = (datetime.now() + timedelta(days=expires_days)).isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO share_links (token, name, created_date, expires_date, access_type)
        VALUES (?, ?, ?, ?, ?)
    ''', (token, name, created_date, expires_date, access_type))
    
    conn.commit()
    conn.close()
    
    return token

def verify_share_link(token):
    """
    Verify a share link is valid and not expired.
    
    Returns:
        dict: Share link info if valid, None otherwise
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    link = cursor.execute('''
        SELECT * FROM share_links 
        WHERE token = ? AND is_active = 1
    ''', (token,)).fetchone()
    
    if not link:
        conn.close()
        return None
    
    # Check if expired
    if link['expires_date']:
        expires = datetime.fromisoformat(link['expires_date'])
        if datetime.now() > expires:
            conn.close()
            return None
    
    # Increment view count
    cursor.execute('UPDATE share_links SET view_count = view_count + 1 WHERE token = ?', (token,))
    conn.commit()
    conn.close()
    
    return dict(link)

def get_all_share_links():
    """Get all active share links."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    links = cursor.execute('''
        SELECT * FROM share_links 
        WHERE is_active = 1
        ORDER BY created_date DESC
    ''').fetchall()
    
    conn.close()
    return [dict(link) for link in links]

def revoke_share_link(token):
    """Revoke a share link."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('UPDATE share_links SET is_active = 0 WHERE token = ?', (token,))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    # Test
    create_share_table()
    token = generate_share_link("Test Share", expires_days=7)
    print(f"Generated token: {token}")
    
    link = verify_share_link(token)
    print(f"Link info: {link}")
