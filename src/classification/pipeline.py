"""High-level orchestration for the classification workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Sequence

from .aggregator import aggregate, write_bucket_metrics
from .data import ClassificationResult, VideoRecord
from .detectors import detect_signals
from .io import load_records
from .logic import ConflictResolver


def process_path(
    source: str | Path,
    output_dir: str | Path | None = None,
    *,
    min_views: int = 50_000,
    resolver: ConflictResolver | None = None,
) -> List[ClassificationResult]:
    """Load records from *source* and return classification results.

    If *output_dir* is provided, classified records and aggregated metrics are
    written to disk.
    """

    records = load_records(source)
    resolver = resolver or ConflictResolver()

    filtered_records = [record for record in records if record.view_count >= min_views]
    results = _classify_records(filtered_records, resolver)

    if output_dir:
        write_outputs(filtered_records, results, output_dir)

    return results


def _classify_records(records: Sequence[VideoRecord], resolver: ConflictResolver) -> List[ClassificationResult]:
    results: List[ClassificationResult] = []
    for record in records:
        text = record.desc + " " + " ".join(record.hashtags)
        scores = detect_signals(text)
        result = resolver.classify(record.aweme_id, text, scores)
        results.append(result)
    return results


def write_outputs(records: Sequence[VideoRecord], results: Sequence[ClassificationResult], output_dir: str | Path) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    _write_results(results, output_path / "classified_records.jsonl")
    metrics = aggregate(records, results)
    write_bucket_metrics(metrics, output_path / "bucket_metrics.csv")


def _write_results(results: Sequence[ClassificationResult], path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for result in results:
            fh.write(json.dumps(
                {
                    "aweme_id": result.aweme_id,
                    "category": result.category,
                    "flag": result.flag,
                    "active_signals": sorted(result.active_signals),
                    "scores": result.scores,
                },
                ensure_ascii=False,
            ))
            fh.write("\n")
