"""Utilities for preparing TikTok aweme records for NLP processing."""

from __future__ import annotations

import copy
import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Protocol, Sequence, Tuple

try:  # pragma: no cover - optional dependency setup
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover - fallback for environments without boto3
    boto3 = None  # type: ignore[assignment]

    class ClientError(Exception):
        def __init__(
            self,
            error_response: Dict[str, Any] | None = None,
            operation_name: str | None = None,
        ):
            self.response = error_response or {"Error": {}}
            self.operation_name = operation_name
            super().__init__(str(self.response))

    class BotoCoreError(Exception):
        pass

Record = Dict[str, Any]

# Column constants
AWEME_ID_COLUMN = "aweme_id"
PLAY_COUNT_COLUMN = "statistics.play_count"
PLAY_COUNT_NESTED_PARENT = "statistics"
PLAY_COUNT_NESTED_CHILD = "play_count"


class QueuePublisher(Protocol):
    """Protocol describing how processed rows are published to a queue."""

    def publish(self, records: Iterable[Record]) -> None:
        """Publish an iterable of dictionary records."""


@dataclass
class JsonlQueuePublisher:
    """Simple queue publisher that appends JSONL rows to a file."""

    destination: Path | str
    append: bool = True

    def publish(self, records: Iterable[Record]) -> None:  # pragma: no cover - simple wrapper
        rows = list(records)
        if not rows:
            return
        if _is_s3_path(self.destination):
            self._publish_to_s3(rows)
            return

        destination = Path(self.destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if self.append and destination.exists() else "w"
        with destination.open(mode, encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _publish_to_s3(self, rows: List[Record]) -> None:
        uri = str(self.destination)
        existing = ""
        if self.append:
            try:
                existing = _read_text_from_s3(uri)
            except FileNotFoundError:
                existing = ""
        new_payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        payload = existing + new_payload
        _write_text_to_s3(uri, payload, ".jsonl")


def _ensure_required_columns(records: Sequence[Record]) -> None:
    if not records:
        return

    missing_aweme_id = any(AWEME_ID_COLUMN not in record for record in records)
    missing_play_count = any(not _has_play_count(record) for record in records)

    if missing_aweme_id or missing_play_count:
        missing: List[str] = []
        if missing_aweme_id:
            missing.append(AWEME_ID_COLUMN)
        if missing_play_count:
            missing.append(
                f"{PLAY_COUNT_COLUMN} or {PLAY_COUNT_NESTED_PARENT}.{PLAY_COUNT_NESTED_CHILD}"
            )
        missing_list = ", ".join(missing)
        raise KeyError(f"Missing required columns: {missing_list}")


def _has_play_count(record: Record) -> bool:
    if PLAY_COUNT_COLUMN in record:
        return True
    statistics = record.get(PLAY_COUNT_NESTED_PARENT)
    if isinstance(statistics, dict) and PLAY_COUNT_NESTED_CHILD in statistics:
        return True
    return False


def _extract_play_count(record: Record) -> int:
    if PLAY_COUNT_COLUMN in record:
        return _to_int(record[PLAY_COUNT_COLUMN])

    statistics = record.get(PLAY_COUNT_NESTED_PARENT)
    if isinstance(statistics, dict) and PLAY_COUNT_NESTED_CHILD in statistics:
        return _to_int(statistics[PLAY_COUNT_NESTED_CHILD])

    raise KeyError(
        f"Missing play count; expected {PLAY_COUNT_COLUMN} or "
        f"{PLAY_COUNT_NESTED_PARENT}.{PLAY_COUNT_NESTED_CHILD}"
    )


def _to_int(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError("Boolean value cannot represent play count")
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("_", "").strip()
        if not cleaned:
            raise ValueError("Empty string cannot represent play count")
        return int(float(cleaned))
    raise TypeError(f"Unsupported type for numeric conversion: {type(value)!r}")


def load_curated_table(path: Path | str) -> List[Record]:
    """Load the curated dataset from CSV or JSON Lines files."""

    if _is_s3_path(path):
        suffix = Path(_parse_s3_uri(str(path))[1]).suffix.lower()
        raw_text = _read_text_from_s3(str(path))
        records = _deserialise_records(raw_text, suffix)
    else:
        resolved = Path(path)
        if not resolved.exists():
            raise FileNotFoundError(f"Curated table not found: {resolved}")

        suffix = resolved.suffix.lower()
        if suffix == ".csv":
            with resolved.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                records = [dict(row) for row in reader]
        elif suffix in {".jsonl", ".ndjson"}:
            with resolved.open("r", encoding="utf-8") as handle:
                records = [json.loads(line) for line in handle if line.strip()]
        else:
            raise ValueError(
                "Unsupported file extension for curated table: " f"{resolved.suffix}"
            )

    _ensure_required_columns(records)
    return records


def select_top_aweme_by_play_count(records: Sequence[Record]) -> List[Record]:
    """Select a single row per aweme with the maximum play count."""

    if not records:
        return []

    _ensure_required_columns(records)
    best_records: Dict[str, Record] = {}
    for record in records:
        aweme_id = record[AWEME_ID_COLUMN]
        play_count = _extract_play_count(record)
        existing = best_records.get(aweme_id)
        if existing is None or play_count > _extract_play_count(existing):
            best_records[aweme_id] = copy.deepcopy(record)

    deduplicated = list(best_records.values())
    deduplicated.sort(
        key=lambda row: (-_extract_play_count(row), row[AWEME_ID_COLUMN])
    )
    return deduplicated


def partition_by_play_count(
    records: Sequence[Record], *, threshold: int = 50_000
) -> Tuple[List[Record], List[Record]]:
    """Partition records into accepted and filtered groups by play count."""

    if not records:
        return [], []

    _ensure_required_columns(records)
    accepted: List[Record] = []
    filtered: List[Record] = []

    for record in records:
        target = accepted if _extract_play_count(record) >= threshold else filtered
        target.append(copy.deepcopy(record))

    return accepted, filtered


def _write_records(records: Sequence[Record], path: Path | str) -> None:
    suffix = _infer_suffix(path)
    payload = _serialise_records(records, suffix)

    if _is_s3_path(path):
        _write_text_to_s3(str(path), payload, suffix)
        return

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    newline = "" if suffix == ".csv" else None
    with destination.open("w", encoding="utf-8", newline=newline) as handle:
        handle.write(payload)


def _serialise_records(records: Sequence[Record], suffix: str) -> str:
    if suffix == ".csv":
        fieldnames: List[str] = []
        if records:
            seen = set()
            for record in records:
                for key in record.keys():
                    if key not in seen:
                        seen.add(key)
                        fieldnames.append(key)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            serialised = {
                key: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list))
                else value
                for key, value in record.items()
            }
            writer.writerow(serialised)
        return buffer.getvalue()
    if suffix in {".jsonl", ".ndjson"}:
        return "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    raise ValueError(f"Unsupported file extension for output: {suffix}")


def _deserialise_records(raw_text: str, suffix: str) -> List[Record]:
    if suffix == ".csv":
        buffer = io.StringIO(raw_text)
        reader = csv.DictReader(buffer)
        return [dict(row) for row in reader]
    if suffix in {".jsonl", ".ndjson"}:
        return [json.loads(line) for line in raw_text.splitlines() if line.strip()]
    raise ValueError(f"Unsupported file extension for curated table: {suffix}")


def _infer_suffix(path: Path | str) -> str:
    if _is_s3_path(path):
        return Path(_parse_s3_uri(str(path))[1]).suffix.lower()
    return Path(path).suffix.lower()


def _is_s3_path(path: Path | str) -> bool:
    value = str(path)
    return value.startswith("s3://") or value.startswith("s3:/")


def _parse_s3_uri(uri: str) -> Tuple[str, str]:
    if uri.startswith("s3://"):
        without_scheme = uri[5:]
    elif uri.startswith("s3:/"):
        without_scheme = uri[4:]
        if without_scheme.startswith("/"):
            without_scheme = without_scheme[1:]
    else:
        raise ValueError(f"Invalid S3 URI: {uri}")
    if not without_scheme:
        raise ValueError(f"Invalid S3 URI: {uri}")
    parts = without_scheme.split("/", 1)
    bucket = parts[0]
    if len(parts) == 1 or not parts[1]:
        raise ValueError(f"S3 URI is missing key: {uri}")
    key = parts[1]
    return bucket, key


def _get_s3_client():
    if boto3 is None:  # pragma: no cover - defensive guard for missing boto3
        raise ModuleNotFoundError(
            "boto3 is required for S3 operations. Install boto3 to enable s3:// support."
        )
    return boto3.client("s3")


def _read_text_from_s3(uri: str) -> str:
    bucket, key = _parse_s3_uri(uri)
    client = _get_s3_client()
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except ClientError as error:
        code = (error.response or {}).get("Error", {}).get("Code")  # type: ignore[union-attr]
        if code in {"NoSuchKey", "404"}:
            raise FileNotFoundError(f"S3 object not found: {uri}") from error
        raise
    body = response["Body"]
    data = body.read()
    close = getattr(body, "close", None)
    if callable(close):
        close()
    return data.decode("utf-8")


def _write_text_to_s3(uri: str, payload: str, suffix: str) -> None:
    bucket, key = _parse_s3_uri(uri)
    client = _get_s3_client()
    content_type = "application/json" if suffix in {".jsonl", ".ndjson"} else "text/csv"
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=payload.encode("utf-8"),
            ContentType=content_type,
        )
    except (ClientError, BotoCoreError) as error:
        raise RuntimeError(f"Failed to write to S3 object {uri}: {error}") from error

def process_curated_table(
    input_path: Path | str,
    *,
    accepted_output: Path | str,
    filtered_output: Path | str,
    queue_publisher: QueuePublisher,
    threshold: int = 50_000,
) -> Tuple[List[Record], List[Record]]:
    """Run the full processing pipeline for aweme records."""

    curated = load_curated_table(input_path)
    curated = select_top_aweme_by_play_count(curated)
    accepted, filtered = partition_by_play_count(curated, threshold=threshold)

    _write_records(accepted, accepted_output)
    _write_records(filtered, filtered_output)

    queue_publisher.publish(accepted)
    return accepted, filtered


def main() -> None:  # pragma: no cover - CLI wrapper
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", type=str, help="Path or s3 URI to the curated input table")
    parser.add_argument(
        "accepted_output",
        type=str,
        help="Path or s3 URI where the accepted rows will be persisted",
    )
    parser.add_argument(
        "filtered_output",
        type=str,
        help="Path or s3 URI where the filtered rows (<threshold) will be persisted",
    )
    parser.add_argument(
        "queue_path",
        type=str,
        help="Path or s3 URI for the JSONL NLP processing queue",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=50_000,
        help="Minimum play count required to accept a record (default: 50k)",
    )

    args = parser.parse_args()
    publisher = JsonlQueuePublisher(args.queue_path)
    process_curated_table(
        args.input_path,
        accepted_output=args.accepted_output,
        filtered_output=args.filtered_output,
        queue_publisher=publisher,
        threshold=args.threshold,
    )


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
