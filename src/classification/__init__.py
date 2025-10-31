"""Classification pipeline for TikTok metadata."""

from .curation import CurationReport, curate, deduplicate_records
from .data import ClassificationResult, VideoRecord
from .pipeline import process_path

__all__ = [
    "VideoRecord",
    "ClassificationResult",
    "process_path",
    "curate",
    "CurationReport",
    "deduplicate_records",
]
