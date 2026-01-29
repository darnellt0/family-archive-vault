import hashlib
import json
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List

from .config import THUMBNAIL_DIR, VIDEO_POSTERS_DIR, TRANSCRIPTS_DIR, MAX_VIDEO_TRANSCRIBE_MINUTES


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_phash(path: Path) -> Optional[str]:
    try:
        from PIL import Image
        import imagehash
    except Exception:
        return None

    try:
        img = Image.open(path)
        return str(imagehash.phash(img))
    except Exception:
        return None


def extract_exif(path: Path) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS, GPSTAGS
    except Exception:
        return None, None, None

    try:
        img = Image.open(path)
        exif = img._getexif() or {}
    except Exception:
        return None, None, None

    date_taken = None
    gps_lat = None
    gps_lon = None

    for tag, value in exif.items():
        name = TAGS.get(tag, tag)
        if name == "DateTimeOriginal":
            date_taken = value
        if name == "GPSInfo" and isinstance(value, dict):
            gps_data = {}
            for key, gps_val in value.items():
                gps_data[GPSTAGS.get(key, key)] = gps_val
            gps_lat = gps_data.get("GPSLatitude")
            gps_lon = gps_data.get("GPSLongitude")

    return date_taken, gps_lat, gps_lon


def ffprobe_info(path: Path) -> dict:
    try:
        result = subprocess.check_output([
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ])
        return json.loads(result)
    except Exception:
        return {}


def make_thumbnail(path: Path, is_video: bool) -> Optional[Path]:
    if is_video:
        output = VIDEO_POSTERS_DIR / f"{path.stem}.jpg"
        try:
            subprocess.check_call([
                "ffmpeg", "-y", "-i", str(path), "-frames:v", "1", "-q:v", "2", str(output)
            ])
            return output
        except Exception:
            return None

    try:
        from PIL import Image
    except Exception:
        return None

    output = THUMBNAIL_DIR / f"{path.stem}.jpg"
    try:
        img = Image.open(path)
        img.thumbnail((800, 800))
        img.save(output, format="JPEG")
        return output
    except Exception:
        return None


def run_face_detection(path: Path) -> List[dict]:
    try:
        import numpy as np
        import cv2
        from insightface.app import FaceAnalysis
    except Exception:
        return []

    faces_out = []
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))

    try:
        img = cv2.imread(str(path))
        if img is None:
            return []
        faces = app.get(img)
        for face in faces:
            faces_out.append({
                "bbox": face.bbox.tolist(),
                "embedding": face.embedding.tolist(),
                "confidence": float(face.det_score),
            })
    finally:
        del app

    return faces_out


def run_caption(path: Path) -> Optional[str]:
    try:
        from PIL import Image
        from moondream import Moondream
    except Exception:
        return None

    model = Moondream()
    try:
        img = Image.open(path)
        caption = model.caption(img)
    except Exception:
        caption = None
    finally:
        del model
    return caption


def run_clip_embedding(path: Path) -> Optional[List[float]]:
    try:
        from sentence_transformers import SentenceTransformer
        from PIL import Image
    except Exception:
        return None

    model = SentenceTransformer("clip-ViT-B-32")
    try:
        img = Image.open(path)
        embedding = model.encode(img)
        return embedding.tolist()
    except Exception:
        return None
    finally:
        del model


def run_transcription(path: Path) -> Optional[List[dict]]:
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return None

    info = ffprobe_info(path)
    duration = 0
    try:
        duration = float(info.get("format", {}).get("duration", 0))
    except Exception:
        duration = 0

    if duration > (MAX_VIDEO_TRANSCRIBE_MINUTES * 60):
        return None

    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments_out = []
    try:
        segments, _ = model.transcribe(str(path))
        for seg in segments:
            segments_out.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
            })
    except Exception:
        segments_out = []
    finally:
        del model

    return segments_out
