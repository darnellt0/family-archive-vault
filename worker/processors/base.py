"""Base processor class for AI models."""
import gc
import torch
from abc import ABC, abstractmethod
from loguru import logger


class BaseProcessor(ABC):
    """Base class for AI processors with memory management."""

    def __init__(self, use_gpu: bool = True):
        self.use_gpu = use_gpu and torch.cuda.is_available()
        self.device = "cuda" if self.use_gpu else "cpu"
        self.model = None

    @abstractmethod
    def load_model(self):
        """Load the model into memory."""
        pass

    @abstractmethod
    def process(self, *args, **kwargs):
        """Process input and return results."""
        pass

    def unload_model(self):
        """Unload model from memory and free GPU VRAM."""
        if self.model is not None:
            del self.model
            self.model = None

        if self.use_gpu:
            torch.cuda.empty_cache()

        gc.collect()
        logger.debug(f"{self.__class__.__name__} model unloaded and memory freed")

    def __enter__(self):
        """Context manager entry."""
        self.load_model()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.unload_model()
