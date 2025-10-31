"""Utilities for loading curated TikTok metadata."""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Dict, Iterator, List, Sequence
from urllib.parse import urlparse

from .data import VideoRecord, batch_from_raw


def load_records(path: str | Path) -> List[VideoRecord]:
    """Load :class:`VideoRecord` objects from a JSON or CSV file/directory."""

    if _is_s3_uri(path):
        return _load_from_s3(path)

    path = Path(path)
    if path.is_dir():
        records: List[VideoRecord] = []
        for file in sorted(path.glob("**/*.json")):
            records.extend(_load_from_json_file(file))
        for file in sorted(path.glob("**/*.csv")):
            records.extend(_load_from_csv_file(file))
        return records

    if path.suffix.lower() == ".json":
        return _load_from_json_file(path)
    if path.suffix.lower() == ".csv":
        return _load_from_csv_file(path)

    raise ValueError(f"Unsupported file type for {path}")


def _load_from_json_file(path: Path) -> List[VideoRecord]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, Sequence):
        raise ValueError(f"Unexpected JSON payload in {path}")
    return batch_from_raw(list(data))


def _load_from_csv_file(path: Path) -> List[VideoRecord]:
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    records: List[VideoRecord] = []
    for row in rows:
        payload = _row_to_raw(row)
        if payload:
            try:
                records.append(VideoRecord.from_raw(payload))
            except ValueError:
                continue
    return records


def _row_to_raw(row: Dict[str, str]) -> Dict[str, object] | None:
    if "raw" in row and row["raw"]:
        try:
            return json.loads(row["raw"])
        except json.JSONDecodeError:
            return None

    if row.get("payload"):
        try:
            return json.loads(row["payload"])
        except json.JSONDecodeError:
            return None

    minimal = {}
    for key in ("aweme_id", "desc", "create_time"):
        if not row.get(key):
            return None
        minimal[key] = row[key]

    statistics = {
        "play_count": row.get("view_count") or row.get("play_count"),
        "comment_count": row.get("comment_count"),
        "digg_count": row.get("digg_count") or row.get("like_count"),
        "share_count": row.get("share_count"),
    }
    minimal["statistics"] = statistics

    hashtags = []
    if row.get("hashtags"):
        try:
            hashtags = json.loads(row["hashtags"])
        except json.JSONDecodeError:
            hashtags = [tag.strip() for tag in row["hashtags"].split() if tag]
    minimal["text_extra"] = [
        {"hashtag_name": tag.lstrip("#")} for tag in hashtags
    ]

    return minimal


def iter_raw_payloads(path: str | Path) -> Iterator[Dict[str, object]]:
    """Iterate over raw payloads without materialising :class:`VideoRecord`."""

    if _is_s3_uri(path):
        yield from _iter_s3_payloads(path)
        return

    path = Path(path)
    if path.is_dir():
        for file in sorted(path.glob("**/*.json")):
            yield from iter_raw_payloads(file)
        for file in sorted(path.glob("**/*.csv")):
            yield from iter_raw_payloads(file)
        return

    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, Sequence):
            raise ValueError(f"Unexpected JSON payload in {path}")
        for item in data:
            yield item
        return

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                payload = _row_to_raw(row)
                if payload:
                    yield payload
        return

    raise ValueError(f"Unsupported file type for {path}")


def _is_s3_uri(path: str | Path) -> bool:
    if isinstance(path, Path):
        return False
    return isinstance(path, str) and path.startswith("s3://")


def _load_from_s3(uri: str | Path) -> List[VideoRecord]:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - dependency missing in env
        raise RuntimeError("boto3 is required to read from S3 URIs") from exc

    parsed = urlparse(str(uri))
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")

    client = boto3.client("s3")

    if not key or key.endswith("/"):
        records: List[VideoRecord] = []
        for object_key in _iter_s3_keys(client, bucket, key):
            records.extend(_load_records_from_s3_object(client, bucket, object_key))
        return records

    try:
        return _load_records_from_s3_object(client, bucket, key)
    except client.exceptions.NoSuchKey:  # type: ignore[attr-defined]
        prefix = key.rstrip("/") + "/"
        records: List[VideoRecord] = []
        for object_key in _iter_s3_keys(client, bucket, prefix):
            records.extend(_load_records_from_s3_object(client, bucket, object_key))
        return records


def _iter_s3_payloads(uri: str | Path) -> Iterator[Dict[str, object]]:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - dependency missing in env
        raise RuntimeError("boto3 is required to read from S3 URIs") from exc

    parsed = urlparse(str(uri))
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")

    client = boto3.client("s3")

    if key and not key.endswith("/"):
        try:
            yield from _iter_payloads_from_s3_object(client, bucket, key)
            return
        except client.exceptions.NoSuchKey:  # type: ignore[attr-defined]
            key = key.rstrip("/") + "/"

    for object_key in _iter_s3_keys(client, bucket, key):
        yield from _iter_payloads_from_s3_object(client, bucket, object_key)


def _iter_s3_keys(client, bucket: str, prefix: str | None) -> Iterator[str]:
    continuation_token: str | None = None
    collected: List[str] = []
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix} if prefix else {"Bucket": bucket}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**kwargs)
        for obj in response.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            if not key.lower().endswith((".json", ".csv")):
                continue
            collected.append(key)
        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")
    for key in sorted(collected):
        yield key


def _load_records_from_s3_object(client, bucket: str, key: str) -> List[VideoRecord]:
    body = client.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    if key.lower().endswith(".json"):
        data = json.loads(body)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, Sequence):
            raise ValueError(f"Unexpected JSON payload in s3://{bucket}/{key}")
        return batch_from_raw(list(data))
    if key.lower().endswith(".csv"):
        reader = csv.DictReader(StringIO(body))
        records: List[VideoRecord] = []
        for row in reader:
            payload = _row_to_raw(row)
            if payload:
                try:
                    records.append(VideoRecord.from_raw(payload))
                except ValueError:
                    continue
        return records
    raise ValueError(f"Unsupported file type for s3://{bucket}/{key}")


def _iter_payloads_from_s3_object(client, bucket: str, key: str) -> Iterator[Dict[str, object]]:
    body = client.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    if key.lower().endswith(".json"):
        data = json.loads(body)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, Sequence):
            raise ValueError(f"Unexpected JSON payload in s3://{bucket}/{key}")
        for item in data:
            yield item
        return
    if key.lower().endswith(".csv"):
        reader = csv.DictReader(StringIO(body))
        for row in reader:
            payload = _row_to_raw(row)
            if payload:
                yield payload
        return
    raise ValueError(f"Unsupported file type for s3://{bucket}/{key}")
