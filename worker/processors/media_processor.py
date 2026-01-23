"""Image and video processing utilities."""
from pathlib import Path
from typing import Optional
from PIL import Image
import cv2
from loguru import logger


class MediaProcessor:
    """Process images and videos to create thumbnails and posters."""

    @staticmethod
    def create_thumbnail(image_path: Path, output_path: Path, max_size: int = 800) -> bool:
        """Create a thumbnail from an image."""
        try:
            img = Image.open(image_path)

            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background

            # Resize maintaining aspect ratio
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

            # Save as JPEG
            output_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(output_path, 'JPEG', quality=85, optimize=True)

            logger.debug(f"Created thumbnail for {image_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error creating thumbnail for {image_path}: {e}")
            return False

    @staticmethod
    def create_video_poster(video_path: Path, output_path: Path, time_seconds: float = 1.0) -> bool:
        """Extract a poster frame from a video."""
        try:
            import ffmpeg

            output_path.parent.mkdir(parents=True, exist_ok=True)

            (
                ffmpeg
                .input(str(video_path), ss=time_seconds)
                .filter('scale', 800, -1)
                .output(str(output_path), vframes=1, format='image2', vcodec='mjpeg')
                .overwrite_output()
                .run(quiet=True)
            )

            logger.debug(f"Created video poster for {video_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error creating video poster for {video_path}: {e}")
            return False

    @staticmethod
    def extract_keyframes(video_path: Path, output_dir: Path, max_frames: int = 10) -> list:
        """Extract keyframes from a video."""
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            keyframe_paths = []

            # Open video
            cap = cv2.VideoCapture(str(video_path))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)

            # Calculate frame interval
            frame_interval = max(1, total_frames // max_frames)

            for i in range(0, total_frames, frame_interval):
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ret, frame = cap.read()

                if ret:
                    keyframe_path = output_dir / f"keyframe_{i:06d}.jpg"
                    cv2.imwrite(str(keyframe_path), frame)
                    keyframe_paths.append(keyframe_path)

                if len(keyframe_paths) >= max_frames:
                    break

            cap.release()
            logger.debug(f"Extracted {len(keyframe_paths)} keyframes from {video_path.name}")
            return keyframe_paths

        except Exception as e:
            logger.error(f"Error extracting keyframes from {video_path}: {e}")
            return []
