"""CLIP embeddings for semantic search."""
from pathlib import Path
from typing import List, Optional
from PIL import Image
from loguru import logger

from .base import BaseProcessor


class CLIPEmbedder(BaseProcessor):
    """CLIP embeddings for semantic search."""

    def __init__(self, model_name: str = "clip-ViT-B-32", use_gpu: bool = True):
        super().__init__(use_gpu)
        self.model_name = model_name

    def load_model(self):
        """Load CLIP model."""
        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading CLIP model: {self.model_name}")

            self.model = SentenceTransformer(self.model_name, device=self.device)

            logger.info("CLIP model loaded successfully")
        except Exception as e:
            logger.error(f"Error loading CLIP model: {e}")
            raise

    def process_image(self, image_path: Path) -> Optional[List[float]]:
        """Generate CLIP embedding for an image."""
        if self.model is None:
            raise RuntimeError("Model not loaded. Use context manager or call load_model() first.")

        try:
            # Load image
            image = Image.open(image_path).convert('RGB')

            # Generate embedding
            embedding = self.model.encode(image, convert_to_tensor=False)

            logger.debug(f"Generated CLIP embedding for {image_path.name}")
            return embedding.tolist()

        except Exception as e:
            logger.error(f"Error generating CLIP embedding for {image_path}: {e}")
            return None

    def process_text(self, text: str) -> Optional[List[float]]:
        """Generate CLIP embedding for text (for search queries)."""
        if self.model is None:
            raise RuntimeError("Model not loaded. Use context manager or call load_model() first.")

        try:
            embedding = self.model.encode(text, convert_to_tensor=False)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Error generating CLIP embedding for text: {e}")
            return None

    def process(self, image_path: Path) -> Optional[List[float]]:
        """Alias for process_image."""
        return self.process_image(image_path)
