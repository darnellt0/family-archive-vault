"""
Family Archive Vault - Video Utilities
Transcript retrieval, segment matching, and video metadata helpers.
"""

import json
import sqlite3
from typing import Optional

DB_PATH = r'F:\FamilyArchive\data\archive.db'


def get_db_connection():
    """Get a database connection with Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn, table_name):
    """Check if a table exists in the database."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    ).fetchone()
    return row is not None


def seconds_to_timestamp(seconds):
    """
    Convert seconds to MM:SS or HH:MM:SS format.

    Args:
        seconds: Number of seconds (int or float)

    Returns:
        str: Formatted timestamp
    """
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "00:00"

    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def timestamp_to_seconds(timestamp):
    """
    Convert MM:SS or HH:MM:SS format to seconds.

    Args:
        timestamp: Formatted timestamp string

    Returns:
        int: Total seconds
    """
    parts = str(timestamp).split(':')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        else:
            return int(float(parts[0]))
    except (ValueError, IndexError):
        return 0


def get_transcript(media_id):
    """
    Retrieve transcript for a video.

    Args:
        media_id: The drive_id of the video

    Returns:
        dict: {
            'full_text': str,
            'segments': list of {start, end, text}
        }
        None if no transcript exists
    """
    conn = get_db_connection()

    if not table_exists(conn, 'transcripts'):
        conn.close()
        return None

    # Check available columns
    cols = conn.execute("PRAGMA table_info(transcripts)").fetchall()
    col_names = {c['name'] for c in cols}

    # Determine ID column
    id_col = 'media_id' if 'media_id' in col_names else 'drive_id'

    row = conn.execute(f'''
        SELECT full_text, segments_json
        FROM transcripts
        WHERE {id_col} = ?
    ''', (media_id,)).fetchone()

    conn.close()

    if not row:
        return None

    segments = []
    if row['segments_json']:
        try:
            segments = json.loads(row['segments_json'])
        except json.JSONDecodeError:
            pass

    return {
        'full_text': row['full_text'] or '',
        'segments': segments
    }


def get_transcript_segments(media_id):
    """
    Get formatted transcript segments for display.

    Args:
        media_id: The drive_id of the video

    Returns:
        list: [{time: "MM:SS", text: "..."}]
    """
    transcript = get_transcript(media_id)
    if not transcript:
        return []

    formatted = []
    for seg in transcript.get('segments', []):
        start = seg.get('start') or seg.get('start_time') or 0
        formatted.append({
            'time': seconds_to_timestamp(start),
            'time_seconds': int(float(start)),
            'text': seg.get('text', '')
        })

    return formatted


def search_transcript(media_id, query):
    """
    Search for text within a video's transcript.

    Args:
        media_id: The drive_id of the video
        query: Search query string

    Returns:
        list: Matching segments with timestamps
    """
    transcript = get_transcript(media_id)
    if not transcript:
        return []

    query_lower = query.lower().strip()
    if not query_lower:
        return []

    matches = []
    for seg in transcript.get('segments', []):
        text = seg.get('text', '')
        if query_lower in text.lower():
            start = seg.get('start') or seg.get('start_time') or 0
            matches.append({
                'time': seconds_to_timestamp(start),
                'time_seconds': int(float(start)),
                'text': text,
                'highlight': highlight_text(text, query)
            })

    return matches


def highlight_text(text, query):
    """
    Add highlight markers around matching text.

    Args:
        text: Original text
        query: Query to highlight

    Returns:
        str: Text with <mark> tags around matches
    """
    import re
    if not query:
        return text

    pattern = re.compile(re.escape(query), re.IGNORECASE)
    return pattern.sub(lambda m: f'<mark>{m.group()}</mark>', text)


def search_all_transcripts(query, limit=50):
    """
    Search across all video transcripts.

    Args:
        query: Search query string
        limit: Maximum results to return

    Returns:
        list: [{drive_id, filename, matching_segments}]
    """
    conn = get_db_connection()

    if not table_exists(conn, 'transcripts'):
        conn.close()
        return []

    query_lower = query.lower().strip()
    if not query_lower:
        conn.close()
        return []

    # Check columns
    cols = conn.execute("PRAGMA table_info(transcripts)").fetchall()
    col_names = {c['name'] for c in cols}
    id_col = 'media_id' if 'media_id' in col_names else 'drive_id'

    rows = conn.execute(f'''
        SELECT t.{id_col} as media_id, m.filename, t.full_text, t.segments_json
        FROM transcripts t
        JOIN media m ON t.{id_col} = m.drive_id
        WHERE t.full_text LIKE ? AND m.status = 'approved'
        LIMIT ?
    ''', (f'%{query}%', limit * 2)).fetchall()

    conn.close()

    results = []
    for row in rows:
        if len(results) >= limit:
            break

        segments = []
        if row['segments_json']:
            try:
                segments = json.loads(row['segments_json'])
            except json.JSONDecodeError:
                continue

        matching = []
        for seg in segments:
            text = seg.get('text', '')
            if query_lower in text.lower():
                start = seg.get('start') or seg.get('start_time') or 0
                matching.append({
                    'time': seconds_to_timestamp(start),
                    'time_seconds': int(float(start)),
                    'text': text
                })

        if matching:
            results.append({
                'drive_id': row['media_id'],
                'filename': row['filename'],
                'matching_segments': matching[:5]  # Limit segments per video
            })

    return results


def get_video_metadata(drive_id):
    """
    Get metadata for a video file.

    Args:
        drive_id: The drive_id of the video

    Returns:
        dict: Video metadata including duration, dimensions, etc.
    """
    conn = get_db_connection()

    video = conn.execute('''
        SELECT drive_id, filename, original_filename, mime_type,
               status, uploaded_date, date_taken, ai_caption
        FROM media
        WHERE drive_id = ?
    ''', (drive_id,)).fetchone()

    if not video:
        conn.close()
        return None

    result = dict(video)

    # Get additional metadata if available
    if table_exists(conn, 'metadata'):
        metadata_rows = conn.execute('''
            SELECT key, value FROM metadata
            WHERE media_id = ?
        ''', (drive_id,)).fetchall()

        result['metadata'] = {row['key']: row['value'] for row in metadata_rows}

        # Extract common video properties
        if 'duration_seconds' in result['metadata']:
            result['duration'] = seconds_to_timestamp(
                result['metadata']['duration_seconds']
            )
        if 'width' in result['metadata'] and 'height' in result['metadata']:
            result['resolution'] = (
                f"{result['metadata']['width']}x{result['metadata']['height']}"
            )

    # Get transcript availability
    result['has_transcript'] = False
    if table_exists(conn, 'transcripts'):
        cols = conn.execute("PRAGMA table_info(transcripts)").fetchall()
        col_names = {c['name'] for c in cols}
        id_col = 'media_id' if 'media_id' in col_names else 'drive_id'

        transcript = conn.execute(f'''
            SELECT 1 FROM transcripts WHERE {id_col} = ? LIMIT 1
        ''', (drive_id,)).fetchone()
        result['has_transcript'] = transcript is not None

    conn.close()
    return result


def is_video_file(filename: str, mime_type: Optional[str] = None) -> bool:
    """
    Check if a file is a video based on filename or MIME type.

    Args:
        filename: The filename to check
        mime_type: Optional MIME type

    Returns:
        bool: True if video file
    """
    if mime_type and mime_type.lower().startswith('video/'):
        return True

    video_extensions = (
        '.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v',
        '.wmv', '.flv', '.mpg', '.mpeg', '.3gp'
    )
    return filename.lower().endswith(video_extensions)


def get_all_videos(status='approved'):
    """
    Get all video files from the archive.

    Args:
        status: Filter by status ('approved', 'pending', etc.)

    Returns:
        list: Video records with transcript availability
    """
    conn = get_db_connection()

    # Build filter for video files
    video_filter = '''
        (mime_type LIKE 'video/%'
        OR lower(filename) LIKE '%.mp4'
        OR lower(filename) LIKE '%.mov'
        OR lower(filename) LIKE '%.avi'
        OR lower(filename) LIKE '%.mkv'
        OR lower(filename) LIKE '%.webm'
        OR lower(filename) LIKE '%.m4v')
    '''

    videos = conn.execute(f'''
        SELECT drive_id, filename, original_filename, mime_type,
               status, uploaded_date, date_taken, ai_caption
        FROM media
        WHERE status = ? AND {video_filter}
        ORDER BY uploaded_date DESC
    ''', (status,)).fetchall()

    # Check transcript table
    has_transcripts_table = table_exists(conn, 'transcripts')

    results = []
    for video in videos:
        v = dict(video)
        v['has_transcript'] = False

        if has_transcripts_table:
            cols = conn.execute("PRAGMA table_info(transcripts)").fetchall()
            col_names = {c['name'] for c in cols}
            id_col = 'media_id' if 'media_id' in col_names else 'drive_id'

            transcript = conn.execute(f'''
                SELECT 1 FROM transcripts WHERE {id_col} = ? LIMIT 1
            ''', (v['drive_id'],)).fetchone()
            v['has_transcript'] = transcript is not None

        results.append(v)

    conn.close()
    return results


if __name__ == "__main__":
    print("Video Utilities - Family Archive Vault")
    print("=" * 40)

    # Get all videos
    videos = get_all_videos()
    print(f"\nFound {len(videos)} approved videos")

    for video in videos[:5]:
        print(f"\n- {video['filename']}")
        print(f"  Has transcript: {video['has_transcript']}")

        if video['has_transcript']:
            segments = get_transcript_segments(video['drive_id'])
            print(f"  Segments: {len(segments)}")
            if segments:
                print(f"  First: [{segments[0]['time']}] {segments[0]['text'][:50]}...")
