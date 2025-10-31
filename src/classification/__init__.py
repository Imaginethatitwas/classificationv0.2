"""Classification pipeline for TikTok metadata."""

from .data import VideoRecord, ClassificationResult
from .pipeline import process_path

__all__ = [
    "VideoRecord",
    "ClassificationResult",
    "process_path",
]
