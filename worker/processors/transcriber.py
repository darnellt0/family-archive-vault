"""Audio transcription using Whisper."""
from pathlib import Path
from typing import Optional
from loguru import logger

from .base import BaseProcessor


class AudioTranscriber(BaseProcessor):
    """Audio transcription using faster-whisper."""

    def __init__(self, model_name: str = "base", device: str = "cuda", use_gpu: bool = True):
        super().__init__(use_gpu)
        self.model_name = model_name
        self._device = device if use_gpu else "cpu"

    def load_model(self):
        """Load Whisper model."""
        try:
            from faster_whisper import WhisperModel

            logger.info(f"Loading Whisper model: {self.model_name}")

            # Use int8 quantization for GPU to save VRAM
            compute_type = "int8" if self.use_gpu else "int8"

            self.model = WhisperModel(
                self.model_name,
                device=self._device,
                compute_type=compute_type
            )

            logger.info("Whisper model loaded successfully")
        except Exception as e:
            logger.error(f"Error loading Whisper model: {e}")
            raise

    def process(self, audio_path: Path) -> Optional[str]:
        """Transcribe audio file."""
        if self.model is None:
            raise RuntimeError("Model not loaded. Use context manager or call load_model() first.")

        try:
            # Transcribe
            segments, info = self.model.transcribe(
                str(audio_path),
                beam_size=5,
                language=None  # Auto-detect
            )

            # Combine segments
            transcript = " ".join([segment.text for segment in segments])

            logger.info(f"Transcribed {audio_path.name} ({info.language}): {len(transcript)} chars")
            return transcript.strip()

        except Exception as e:
            logger.error(f"Error transcribing {audio_path}: {e}")
            return None

    def extract_audio_from_video(self, video_path: Path, output_path: Path) -> bool:
        """Extract audio track from video."""
        try:
            import ffmpeg

            (
                ffmpeg
                .input(str(video_path))
                .output(str(output_path), acodec='libmp3lame', ac=1, ar='16000')
                .overwrite_output()
                .run(quiet=True)
            )

            logger.info(f"Extracted audio from {video_path.name} to {output_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error extracting audio from {video_path}: {e}")
            return False
