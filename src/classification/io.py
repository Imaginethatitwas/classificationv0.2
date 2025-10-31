"""Utilities for loading curated TikTok metadata."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence

from .data import VideoRecord, batch_from_raw


def load_records(path: str | Path) -> List[VideoRecord]:
    """Load :class:`VideoRecord` objects from a JSON or CSV file/directory."""

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
