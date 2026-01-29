import json
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from .config import (
    CACHE_DIR,
    LOGS_DIR,
    SIDECARE_DIR,
    TRANSCRIPTS_DIR,
    MIN_FREE_DISK_GB,
    MAX_BACKLOG_ITEMS,
)
from .db import init_db, get_conn, set_ops_state
from .drive import get_drive_service, load_drive_schema, list_files, download_file, move_file, upload_json
from .pipeline import (
    compute_sha256,
    compute_phash,
    extract_exif,
    ffprobe_info,
    make_thumbnail,
    run_face_detection,
    run_caption,
    run_clip_embedding,
    run_transcription,
)

LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "worker.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def has_backpressure() -> bool:
    total, used, free = shutil.disk_usage(CACHE_DIR)
    free_gb = free / (1024 ** 3)
    if free_gb < MIN_FREE_DISK_GB:
        logger.warning("Backpressure: low disk space")
        return True

    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) AS count FROM assets WHERE status = 'processing'").fetchone()
    conn.close()
    if row and row["count"] > MAX_BACKLOG_ITEMS:
        logger.warning("Backpressure: backlog too high")
        return True

    return False


def record_error(file_id: str, error: Exception):
    error_dir = LOGS_DIR / "errors"
    error_dir.mkdir(parents=True, exist_ok=True)
    with (error_dir / f"{file_id}.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{datetime.utcnow().isoformat()} {error}\n")


def load_manifests(service, schema):
    manifests = list_files(service, schema["INBOX_MANIFESTS"])
    manifest_map = {}
    conn = get_conn()
    for item in manifests:
        try:
            data = service.files().get_media(fileId=item["id"]).execute()
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            manifest = json.loads(data)
            files = manifest.get("files", [])
            for f in files:
                drive_file_id = f.get("drive_file_id")
                if drive_file_id:
                    manifest_map[drive_file_id] = {
                        "batch_id": manifest.get("batch_id"),
                        "contributor_token": manifest.get("contributor_token"),
                        "contributor_display_name": manifest.get("contributor_display_name"),
                    }
            conn.execute(
                "INSERT OR IGNORE INTO batches (batch_id, contributor_token, created_at, decade, event, notes) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    manifest.get("batch_id"),
                    manifest.get("contributor_token"),
                    manifest.get("created_at"),
                    manifest.get("decade"),
                    manifest.get("event"),
                    manifest.get("notes"),
                ),
            )
        except Exception as exc:
            logger.warning("Failed to read manifest: %s", exc)
    conn.commit()
    conn.close()
    return manifest_map


def asset_exists(conn, drive_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM assets WHERE drive_file_id = ?", (drive_id,)).fetchone()
    return row is not None


def _estimate_decade(exif_date: str):
    if not exif_date:
        return None, 0.0
    try:
        year = int(str(exif_date)[:4])
        decade = f"{year // 10 * 10}s"
        return decade, 0.6
    except Exception:
        return None, 0.0


def process_asset(service, schema, file_info: dict, manifest_meta: dict | None):
    drive_id = file_info["id"]
    filename = file_info["name"]
    mime_type = file_info.get("mimeType")
    size_bytes = int(file_info.get("size", 0)) if file_info.get("size") else None

    asset_id = str(uuid.uuid4())
    local_path = CACHE_DIR / f"{drive_id}_{filename}"

    move_file(service, drive_id, schema["PROCESSING"])
    download_file(service, drive_id, local_path)

    sha256 = compute_sha256(local_path)
    phash = compute_phash(local_path) if mime_type and mime_type.startswith("image/") else None

    exif_date, gps_lat, gps_lon = extract_exif(local_path) if mime_type and mime_type.startswith("image/") else (None, None, None)
    decade, decade_conf = _estimate_decade(exif_date)

    ffprobe = ffprobe_info(local_path) if mime_type and mime_type.startswith("video/") else {}
    duration_seconds = None
    try:
        duration_seconds = float(ffprobe.get("format", {}).get("duration", 0))
    except Exception:
        duration_seconds = None

    make_thumbnail(local_path, mime_type.startswith("video/") if mime_type else False)

    faces = run_face_detection(local_path) if mime_type and mime_type.startswith("image/") else []
    caption = run_caption(local_path) if mime_type and mime_type.startswith("image/") else None
    clip_embedding = run_clip_embedding(local_path) if mime_type and mime_type.startswith("image/") else None
    clip_ref = None
    if clip_embedding:
        clip_path = SIDECARE_DIR / f"{asset_id}_clip.json"
        clip_path.write_text(json.dumps(clip_embedding), encoding="utf-8")
        clip_ref = clip_path.name

    transcript_segments = run_transcription(local_path) if mime_type and (mime_type.startswith("video/") or mime_type.startswith("audio/")) else None

    status = "needs_review"
    holding_folder = schema["HOLDING_NEEDS_REVIEW"]

    if transcript_segments is None and mime_type and mime_type.startswith("video/"):
        status = "transcribe_later"
        holding_folder = schema["HOLDING_TRANSCRIBE_LATER"]

    conn = get_conn()
    duplicate_row = conn.execute("SELECT asset_id FROM assets WHERE sha256 = ?", (sha256,)).fetchone()
    duplicate_of = duplicate_row["asset_id"] if duplicate_row else None
    if not duplicate_of and phash:
        rows = conn.execute("SELECT asset_id, phash FROM assets WHERE phash IS NOT NULL").fetchall()
        for row in rows:
            try:
                distance = sum(c1 != c2 for c1, c2 in zip(phash, row["phash"]))
            except Exception:
                distance = 99
            if distance <= 6:
                duplicate_of = row["asset_id"]
                conn.execute("INSERT INTO duplicates (asset_id, duplicate_of, method) VALUES (?, ?, ?)", (asset_id, duplicate_of, "phash"))
                status = "possible_duplicates"
                holding_folder = schema["HOLDING_DUPLICATES"]
                break
    if duplicate_of:
        status = "possible_duplicates"
        holding_folder = schema["HOLDING_DUPLICATES"]
        conn.execute("INSERT INTO duplicates (asset_id, duplicate_of, method) VALUES (?, ?, ?)", (asset_id, duplicate_of, "sha256"))

    conn.execute(
        "INSERT INTO assets (asset_id, drive_file_id, contributor_token, batch_id, original_filename, mime_type, size_bytes, status, sha256, phash, exif_date, gps_lat, gps_lon, decade, decade_confidence, caption, clip_embedding_ref, transcript_ref, created_at, processed_at, duplicate_of) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            asset_id,
            drive_id,
            (manifest_meta or {}).get("contributor_token"),
            (manifest_meta or {}).get("batch_id"),
            filename,
            mime_type,
            size_bytes,
            status,
            sha256,
            phash,
            exif_date,
            gps_lat,
            gps_lon,
            decade,
            decade_conf,
            caption,
            clip_ref,
            None,
            datetime.utcnow().isoformat(),
            datetime.utcnow().isoformat(),
            duplicate_of,
        ),
    )

    conn.execute(
        "INSERT OR IGNORE INTO media (drive_id, filename, original_filename, mime_type, size_bytes, sha256, status, uploaded_at, date_taken) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            drive_id,
            filename,
            filename,
            mime_type,
            size_bytes,
            sha256,
            "pending",
            file_info.get("createdTime"),
            exif_date,
        ),
    )

    if duration_seconds:
        conn.execute(
            "INSERT OR IGNORE INTO metadata (media_id, key, value, source) VALUES ((SELECT id FROM media WHERE drive_id = ?), ?, ?, ?)",
            (drive_id, "duration_seconds", str(duration_seconds), "ffprobe"),
        )

    conn.commit()
    conn.close()

    if faces:
        conn = get_conn()
        for face in faces:
            conn.execute(
                "INSERT INTO faces (asset_id, bbox_json, embedding_ref, confidence) VALUES (?, ?, ?, ?)",
                (asset_id, json.dumps(face.get("bbox")), json.dumps(face.get("embedding")), face.get("confidence")),
            )
        conn.commit()
        conn.close()

    transcript_ref = None
    if transcript_segments:
        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        transcript_path = TRANSCRIPTS_DIR / f"{asset_id}_transcript.json"
        transcript_path.write_text(json.dumps(transcript_segments, indent=2), encoding="utf-8")
        transcript_ref = transcript_path.name
        conn = get_conn()
        conn.execute(
            "UPDATE assets SET transcript_ref = ? WHERE asset_id = ?",
            (transcript_ref, asset_id),
        )
        conn.commit()
        conn.close()

    sidecar = {
        "asset_id": asset_id,
        "drive_file_id": drive_id,
        "contributor_token": (manifest_meta or {}).get("contributor_token"),
        "batch_id": (manifest_meta or {}).get("batch_id"),
        "original_filename": filename,
        "sha256": sha256,
        "phash": phash,
        "exif_date": exif_date,
        "gps": {"lat": gps_lat, "lon": gps_lon},
        "decade_estimate": decade,
        "decade_confidence": decade_conf,
        "faces": faces,
        "caption": caption,
        "clip_embedding_ref": clip_ref,
        "transcript_ref": transcript_ref,
        "status": status,
        "duplicate_of": duplicate_of,
        "processing": {
            "processed_at": datetime.utcnow().isoformat(),
        },
        "video_duration_seconds": duration_seconds,
    }

    SIDECARE_DIR.mkdir(parents=True, exist_ok=True)
    sidecar_path = SIDECARE_DIR / f"{asset_id}.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    upload_json(service, schema["METADATA_SIDECARS"], f"{asset_id}.json", sidecar)

    move_file(service, drive_id, holding_folder)

    try:
        local_path.unlink(missing_ok=True)
    except Exception:
        pass

    logger.info("Processed %s", filename)


def run_once():
    init_db()
    if has_backpressure():
        return

    service = get_drive_service()
    schema = load_drive_schema(service)

    manifest_map = load_manifests(service, schema)

    contributor_folders = [
        folder for folder in list_files(service, schema["INBOX_UPLOADS"]) if not folder["name"].startswith("_")
    ]

    conn = get_conn()
    for folder in contributor_folders:
        files = list_files(service, folder["id"])
        for file_info in files:
            if asset_exists(conn, file_info["id"]):
                continue
            try:
                process_asset(service, schema, file_info, manifest_map.get(file_info["id"]))
            except Exception as exc:
                logger.exception("Failed processing %s", file_info.get("name"))
                record_error(file_info.get("id", "unknown"), exc)
    conn.close()
    set_ops_state("last_worker_run", datetime.utcnow().isoformat())


def main():
    run_once()


if __name__ == "__main__":
    main()
