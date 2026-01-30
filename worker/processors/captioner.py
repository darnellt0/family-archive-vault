"""Image captioning using Moondream2 or similar small vision model."""
from pathlib import Path
from typing import Optional
from PIL import Image
from loguru import logger

from .base import BaseProcessor


class ImageCaptioner(BaseProcessor):
    """Image captioning using a local vision-language model."""

    def __init__(self, model_name: str = "vikhyatk/moondream2", use_gpu: bool = True):
        super().__init__(use_gpu)
        self.model_name = model_name
        self.tokenizer = None

    def load_model(self):
        """Load captioning model."""
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch

            logger.info(f"Loading caption model: {self.model_name}")

            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                torch_dtype=torch.float16 if self.use_gpu else torch.float32
            )

            if self.use_gpu:
                self.model = self.model.to(self.device)

            self.model.eval()

            logger.info("Caption model loaded successfully")
        except Exception as e:
            logger.error(f"Error loading caption model: {e}")
            raise

    def process(self, image_path: Path) -> Optional[str]:
        """Generate caption for an image."""
        if self.model is None:
            raise RuntimeError("Model not loaded. Use context manager or call load_model() first.")

        try:
            # Load image
            image = Image.open(image_path).convert('RGB')

            # Generate caption using moondream2's query method
            enc_image = self.model.encode_image(image)
            caption = self.model.query(enc_image, "Describe this image in detail.")["answer"]

            logger.info(f"Generated caption for {image_path.name}: {caption[:100]}...")
            return caption

        except Exception as e:
            logger.error(f"Error generating caption for {image_path}: {e}")
            return None
