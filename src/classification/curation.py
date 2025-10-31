"""Curation utilities for preparing TikTok metadata batches."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, MutableMapping
from urllib.parse import urlparse

from .data import VideoRecord
from .io import iter_raw_payloads


@dataclass
class CurationReport:
    """Summary statistics from a curation run."""

    total_records: int
    retained: int
    duplicates_dropped: int
    below_threshold: int
    invalid: int
    destination: str
    output_location: str


def deduplicate_records(records: Iterable[VideoRecord]) -> List[VideoRecord]:
    """Collapse duplicate ``aweme_id`` entries keeping the highest view count."""

    best: Dict[str, VideoRecord] = {}
    for record in records:
        existing = best.get(record.aweme_id)
        if existing is None:
            best[record.aweme_id] = record
            continue

        if _is_better_record(record, existing):
            best[record.aweme_id] = record

    return list(best.values())


def curate(
    source: str | Path,
    destination: str | Path,
    *,
    min_views: int = 50_000,
    overwrite: bool = False,
) -> CurationReport:
    """Run the curation pipeline against ``source`` and write results to ``destination``."""

    total = 0
    below_threshold = 0
    invalid = 0
    duplicates = 0

    best: MutableMapping[str, VideoRecord] = {}

    for payload in iter_raw_payloads(source):
        total += 1
        try:
            record = VideoRecord.from_raw(payload)
        except ValueError:
            invalid += 1
            continue

        if record.view_count < min_views:
            below_threshold += 1
            continue

        existing = best.get(record.aweme_id)
        if existing is None:
            best[record.aweme_id] = record
            continue

        duplicates += 1
        if _is_better_record(record, existing):
            best[record.aweme_id] = record

    records = list(best.values())
    output_payloads = [record.raw for record in records]
    output_location = _write_output(destination, output_payloads, overwrite=overwrite)

    return CurationReport(
        total_records=total,
        retained=len(records),
        duplicates_dropped=duplicates,
        below_threshold=below_threshold,
        invalid=invalid,
        destination=str(destination),
        output_location=output_location,
    )


def _is_better_record(candidate: VideoRecord, incumbent: VideoRecord) -> bool:
    if candidate.view_count != incumbent.view_count:
        return candidate.view_count > incumbent.view_count
    return candidate.create_time > incumbent.create_time


def _write_output(
    destination: str | Path,
    payloads: List[Dict[str, object]],
    *,
    overwrite: bool = False,
) -> str:
    serialized = json.dumps(payloads, ensure_ascii=False)

    if _is_s3_uri(destination):
        return _write_s3(destination, serialized, overwrite=overwrite)

    path = Path(destination)
    if path.is_dir() or str(destination).endswith("/"):
        path.mkdir(parents=True, exist_ok=True)
        filename = _timestamped_filename()
        if overwrite:
            for existing in path.glob("*.json"):
                existing.unlink(missing_ok=True)
        target = path / filename
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        target = path

    target.write_text(serialized, encoding="utf-8")
    return str(target)


def _write_s3(destination: str | Path, body: str, *, overwrite: bool) -> str:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - boto3 may be absent in tests
        raise RuntimeError("boto3 is required for S3 destinations") from exc

    parsed = urlparse(str(destination))
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")

    client = boto3.client("s3")

    if not key or key.endswith("/"):
        prefix = key.rstrip("/") + "/" if key else ""
        if overwrite and prefix:
            _clear_s3_prefix(client, bucket, prefix)
        filename = _timestamped_filename()
        object_key = prefix + filename
    else:
        object_key = key
        if overwrite:
            client.delete_object(Bucket=bucket, Key=object_key)

    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )

    return f"s3://{bucket}/{object_key}"


def _clear_s3_prefix(client, bucket: str, prefix: str) -> None:
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys = [obj["Key"] for obj in page.get("Contents", []) if obj["Key"].endswith(".json")]
        if not keys:
            continue
        client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": key} for key in keys]},
        )


def _timestamped_filename() -> str:
    now = datetime.now(tz=timezone.utc)
    return now.strftime("curated-%Y%m%dT%H%M%SZ.json")


def _is_s3_uri(path: str | Path) -> bool:
    if isinstance(path, Path):
        return False
    return isinstance(path, str) and path.startswith("s3://")

