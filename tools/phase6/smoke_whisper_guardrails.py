import argparse
from pathlib import Path
from services.worker.pipeline import run_transcription, ffprobe_info
from services.worker.config import MAX_VIDEO_TRANSCRIBE_MINUTES

parser = argparse.ArgumentParser()
parser.add_argument("file", help="Path to a video or audio file")
args = parser.parse_args()

path = Path(args.file)
info = ffprobe_info(path)
print("Duration info:", info)
print("Guardrail minutes:", MAX_VIDEO_TRANSCRIBE_MINUTES)

segments = run_transcription(path)
if segments is None:
    print("Transcription deferred (transcribe_later).")
else:
    print(f"Transcribed {len(segments)} segments.")
