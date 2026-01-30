"""Metadata extraction from images and videos."""
import hashlib
import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from PIL import Image, ExifTags
import imagehash
from loguru import logger


class MetadataExtractor:
    """Extract metadata from media files."""

    @staticmethod
    def compute_sha256(file_path: Path) -> str:
        """Compute SHA256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    @staticmethod
    def compute_phash(image_path: Path) -> Optional[str]:
        """Compute perceptual hash for image."""
        try:
            img = Image.open(image_path)
            phash = str(imagehash.phash(img))
            return phash
        except Exception as e:
            logger.error(f"Error computing phash for {image_path}: {e}")
            return None

    @staticmethod
    def extract_exif(image_path: Path) -> Optional[Dict[str, Any]]:
        """Extract EXIF data from image."""
        try:
            img = Image.open(image_path)
            exif_data = img._getexif()

            if not exif_data:
                return None

            # Convert EXIF tags to readable names
            exif = {
                ExifTags.TAGS.get(tag, tag): value
                for tag, value in exif_data.items()
            }

            # Extract key fields
            result = {
                "camera_make": exif.get("Make"),
                "camera_model": exif.get("Model"),
                "orientation": exif.get("Orientation"),
                "width": img.width,
                "height": img.height,
                "raw_exif": {}
            }

            # Date taken
            date_str = exif.get("DateTimeOriginal") or exif.get("DateTime")
            if date_str:
                try:
                    result["date_taken"] = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                except:
                    pass

            # GPS coordinates
            gps_info = exif.get("GPSInfo")
            if gps_info:
                try:
                    lat = MetadataExtractor._convert_gps_to_degrees(gps_info.get(2))
                    lon = MetadataExtractor._convert_gps_to_degrees(gps_info.get(4))
                    lat_ref = gps_info.get(1)
                    lon_ref = gps_info.get(3)

                    if lat and lon:
                        result["gps_latitude"] = lat if lat_ref == 'N' else -lat
                        result["gps_longitude"] = lon if lon_ref == 'E' else -lon
                except Exception as e:
                    logger.debug(f"Error parsing GPS data: {e}")

            # Store limited raw EXIF (avoid huge binaries)
            for key in ["Make", "Model", "DateTimeOriginal", "DateTime", "Software"]:
                if key in exif:
                    result["raw_exif"][key] = str(exif[key])

            return result

        except Exception as e:
            logger.error(f"Error extracting EXIF from {image_path}: {e}")
            return None

    @staticmethod
    def _convert_gps_to_degrees(value):
        """Convert GPS coordinates to degrees."""
        if not value:
            return None
        d = float(value[0])
        m = float(value[1])
        s = float(value[2])
        return d + (m / 60.0) + (s / 3600.0)

    @staticmethod
    def extract_video_metadata(video_path: Path) -> Optional[Dict[str, Any]]:
        """Extract video metadata using ffprobe."""
        try:
            import ffmpeg

            probe = ffmpeg.probe(str(video_path))
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)

            if not video_stream:
                return None

            return {
                "duration_seconds": float(probe['format']['duration']),
                "width": int(video_stream['width']),
                "height": int(video_stream['height']),
                "codec": video_stream.get('codec_name'),
                "fps": eval(video_stream.get('r_frame_rate', '0/1')),
                "bitrate": int(probe['format'].get('bit_rate', 0))
            }

        except Exception as e:
            logger.error(f"Error extracting video metadata from {video_path}: {e}")
            return None

    @staticmethod
    def estimate_decade(exif_date: Optional[datetime], filename: str) -> Optional[int]:
        """Estimate decade from EXIF date or filename patterns."""
        # Try EXIF date first
        if exif_date:
            year = exif_date.year
            return (year // 10) * 10

        # Try filename patterns like IMG_19850615_...
        import re
        patterns = [
            r'(\d{4})[_-]?\d{2}[_-]?\d{2}',  # YYYYMMDD
            r'[_-](\d{4})[_-]',  # _YYYY_
            r'(19\d{2}|20\d{2})',  # 4-digit year
        ]

        for pattern in patterns:
            match = re.search(pattern, filename)
            if match:
                year = int(match.group(1))
                if 1940 <= year <= 2030:
                    return (year // 10) * 10

        return None
