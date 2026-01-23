"""Face detection and embedding using InsightFace."""
import numpy as np
from typing import List, Dict, Any
from pathlib import Path
import cv2
from loguru import logger

from .base import BaseProcessor


class FaceDetector(BaseProcessor):
    """Face detection and embedding using InsightFace."""

    def __init__(self, model_name: str = "buffalo_l", min_confidence: float = 0.6, use_gpu: bool = True):
        super().__init__(use_gpu)
        self.model_name = model_name
        self.min_confidence = min_confidence

    def load_model(self):
        """Load InsightFace model."""
        try:
            import insightface
            from insightface.app import FaceAnalysis

            logger.info(f"Loading InsightFace model: {self.model_name}")

            self.model = FaceAnalysis(
                name=self.model_name,
                providers=['CUDAExecutionProvider'] if self.use_gpu else ['CPUExecutionProvider']
            )
            self.model.prepare(ctx_id=0 if self.use_gpu else -1, det_size=(640, 640))

            logger.info("InsightFace model loaded successfully")
        except Exception as e:
            logger.error(f"Error loading InsightFace model: {e}")
            raise

    def process(self, image_path: Path) -> List[Dict[str, Any]]:
        """Detect faces and extract embeddings."""
        if self.model is None:
            raise RuntimeError("Model not loaded. Use context manager or call load_model() first.")

        try:
            # Read image
            img = cv2.imread(str(image_path))
            if img is None:
                logger.error(f"Failed to read image: {image_path}")
                return []

            # Detect faces
            faces = self.model.get(img)

            results = []
            for face in faces:
                # Filter by confidence
                if face.det_score < self.min_confidence:
                    continue

                bbox = face.bbox.astype(int)
                embedding = face.embedding.tolist()

                results.append({
                    "box": {
                        "x": float(bbox[0]),
                        "y": float(bbox[1]),
                        "width": float(bbox[2] - bbox[0]),
                        "height": float(bbox[3] - bbox[1]),
                        "confidence": float(face.det_score)
                    },
                    "embedding": embedding,
                    "cluster_id": None,
                    "person_id": None,
                    "person_name": None
                })

            logger.info(f"Detected {len(results)} faces in {image_path.name}")
            return results

        except Exception as e:
            logger.error(f"Error detecting faces in {image_path}: {e}")
            return []
