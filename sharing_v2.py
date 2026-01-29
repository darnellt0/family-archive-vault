"""
Family Archive Vault - Advanced Sharing v2
Password protection, view limits, and granular access controls.
"""

import sqlite3
import secrets
import hashlib
from datetime import datetime, timedelta

DB_PATH = r'F:\FamilyArchive\data\archive.db'


def get_db_connection():
    """Get a database connection with Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_share_links_table():
    """Create the share_links table with all v2 columns if it doesn't exist."""
    conn = get_db_connection()
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
            view_count INTEGER DEFAULT 0,
            password_hash TEXT,
            password_salt TEXT,
            max_views INTEGER,
            allow_download BOOLEAN DEFAULT 0
        )
    ''')

    conn.commit()
    conn.close()


def upgrade_schema():
    """Add v2 columns to existing share_links table."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get existing columns
    cursor.execute("PRAGMA table_info(share_links)")
    existing_cols = {row['name'] for row in cursor.fetchall()}

    # Add missing columns
    new_columns = [
        ("password_hash", "TEXT"),
        ("password_salt", "TEXT"),
        ("max_views", "INTEGER"),
        ("allow_download", "BOOLEAN DEFAULT 0"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE share_links ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass

    conn.commit()
    conn.close()


def hash_password(password, salt=None):
    """
    Hash a password using PBKDF2-HMAC-SHA256.

    Args:
        password: The plaintext password
        salt: Optional salt (generated if not provided)

    Returns:
        tuple: (hash_hex, salt_hex)
    """
    if salt is None:
        salt = secrets.token_hex(16)

    password_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000  # iterations
    ).hex()

    return password_hash, salt


def verify_password(password, stored_hash, stored_salt):
    """Verify a password against stored hash and salt."""
    computed_hash, _ = hash_password(password, stored_salt)
    return secrets.compare_digest(computed_hash, stored_hash)


def generate_share_link(
    name,
    expires_days=30,
    access_type='view',
    password=None,
    max_views=None,
    allow_download=False
):
    """
    Generate a secure sharing link with advanced options.

    Args:
        name: Description of the share (e.g., "Grandma's Birthday")
        expires_days: Days until expiration (None = never)
        access_type: 'view' or 'download'
        password: Optional password protection
        max_views: Maximum number of views allowed
        allow_download: Whether downloads are permitted

    Returns:
        str: The shareable token
    """
    ensure_share_links_table()
    upgrade_schema()

    token = secrets.token_urlsafe(32)
    created_date = datetime.now().isoformat()

    expires_date = None
    if expires_days:
        expires_date = (datetime.now() + timedelta(days=expires_days)).isoformat()

    password_hash = None
    password_salt = None
    if password:
        password_hash, password_salt = hash_password(password)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO share_links (
            token, name, created_date, expires_date, access_type,
            is_active, view_count, password_hash, password_salt,
            max_views, allow_download
        )
        VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?)
    ''', (
        token, name, created_date, expires_date, access_type,
        password_hash, password_salt, max_views, 1 if allow_download else 0
    ))

    conn.commit()
    conn.close()

    return token


def verify_share_link(token, password=None):
    """
    Verify a share link is valid, not expired, and password-protected access.

    Args:
        token: The share link token
        password: Optional password for protected links

    Returns:
        dict: Share link info if valid
        dict with 'requires_password': True if password needed
        None if invalid/expired
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    link = cursor.execute('''
        SELECT * FROM share_links
        WHERE token = ? AND is_active = 1
    ''', (token,)).fetchone()

    if not link:
        conn.close()
        return None

    link_dict = dict(link)

    # Check expiration
    if link_dict.get('expires_date'):
        try:
            expires = datetime.fromisoformat(link_dict['expires_date'])
            if datetime.now() > expires:
                conn.close()
                return None
        except ValueError:
            pass

    # Check view limit
    max_views = link_dict.get('max_views')
    view_count = link_dict.get('view_count') or 0
    if max_views and view_count >= max_views:
        # Auto-deactivate link
        cursor.execute(
            'UPDATE share_links SET is_active = 0 WHERE token = ?',
            (token,)
        )
        conn.commit()
        conn.close()
        return None

    # Check password
    if link_dict.get('password_hash'):
        if not password:
            conn.close()
            return {'requires_password': True, 'link': link_dict}

        if not verify_password(
            password,
            link_dict['password_hash'],
            link_dict.get('password_salt') or ''
        ):
            conn.close()
            return {'requires_password': True, 'link': link_dict}

    # Increment view count
    cursor.execute(
        'UPDATE share_links SET view_count = view_count + 1 WHERE token = ?',
        (token,)
    )
    conn.commit()
    conn.close()

    link_dict['requires_password'] = False
    return link_dict


def get_all_share_links():
    """Get all active share links."""
    conn = get_db_connection()

    links = conn.execute('''
        SELECT * FROM share_links
        WHERE is_active = 1
        ORDER BY created_date DESC
    ''').fetchall()

    conn.close()
    return [dict(link) for link in links]


def get_share_link_stats(token):
    """Get detailed statistics for a share link."""
    conn = get_db_connection()

    link = conn.execute('''
        SELECT * FROM share_links WHERE token = ?
    ''', (token,)).fetchone()

    conn.close()

    if not link:
        return None

    link_dict = dict(link)

    # Calculate remaining views
    max_views = link_dict.get('max_views')
    view_count = link_dict.get('view_count') or 0
    link_dict['remaining_views'] = (max_views - view_count) if max_views else None

    # Calculate days until expiration
    if link_dict.get('expires_date'):
        try:
            expires = datetime.fromisoformat(link_dict['expires_date'])
            delta = expires - datetime.now()
            link_dict['days_remaining'] = max(0, delta.days)
            link_dict['is_expired'] = delta.total_seconds() < 0
        except ValueError:
            link_dict['days_remaining'] = None
            link_dict['is_expired'] = False
    else:
        link_dict['days_remaining'] = None
        link_dict['is_expired'] = False

    return link_dict


def revoke_share_link(token):
    """Revoke/deactivate a share link."""
    conn = get_db_connection()
    conn.execute(
        'UPDATE share_links SET is_active = 0 WHERE token = ?',
        (token,)
    )
    conn.commit()
    conn.close()


def update_share_link(token, **kwargs):
    """
    Update share link properties.

    Supported kwargs: name, expires_days, password, max_views, allow_download
    """
    conn = get_db_connection()

    updates = []
    params = []

    if 'name' in kwargs:
        updates.append('name = ?')
        params.append(kwargs['name'])

    if 'expires_days' in kwargs:
        if kwargs['expires_days']:
            expires_date = (
                datetime.now() + timedelta(days=kwargs['expires_days'])
            ).isoformat()
        else:
            expires_date = None
        updates.append('expires_date = ?')
        params.append(expires_date)

    if 'password' in kwargs:
        if kwargs['password']:
            password_hash, password_salt = hash_password(kwargs['password'])
        else:
            password_hash, password_salt = None, None
        updates.append('password_hash = ?')
        updates.append('password_salt = ?')
        params.extend([password_hash, password_salt])

    if 'max_views' in kwargs:
        updates.append('max_views = ?')
        params.append(kwargs['max_views'])

    if 'allow_download' in kwargs:
        updates.append('allow_download = ?')
        params.append(1 if kwargs['allow_download'] else 0)

    if updates:
        params.append(token)
        sql = f"UPDATE share_links SET {', '.join(updates)} WHERE token = ?"
        conn.execute(sql, params)
        conn.commit()

    conn.close()


if __name__ == "__main__":
    # Initialize/upgrade schema
    ensure_share_links_table()
    upgrade_schema()
    print("Share links table initialized with v2 schema.")

    # Demo: Create a password-protected link
    token = generate_share_link(
        name="Family Reunion 2024",
        expires_days=30,
        password="family123",
        max_views=50,
        allow_download=True
    )
    print(f"Created share link: {token}")

    # Verify without password
    result = verify_share_link(token)
    print(f"Without password: {result}")

    # Verify with correct password
    result = verify_share_link(token, password="family123")
    print(f"With password: {result}")

    # Get stats
    stats = get_share_link_stats(token)
    print(f"Stats: {stats}")
