"""AWS Lambda handler that curates TikTok scrape batches.

The function is triggered whenever a manifest file is uploaded under the
``raw/`` prefix. The manifest describes a scrape batch and lists the raw
objects that belong to it. For each raw item we pull the relevant fields and
write a normalised JSON Lines document to ``curated/<batch_id>/`` while also
producing a batch level manifest.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Sequence
from urllib.parse import unquote_plus

try:
    import boto3
except ModuleNotFoundError:  # pragma: no cover - boto3 is available in Lambda
    boto3 = None

RAW_PREFIX = os.environ.get("RAW_PREFIX", "raw/")
CURATED_PREFIX = os.environ.get("CURATED_PREFIX", "curated/")
CURATED_MANIFEST_PREFIX = os.environ.get(
    "CURATED_BATCH_MANIFEST_PREFIX", "curated_manifests/"
)
BUCKET_NAME = os.environ.get("BUCKET_NAME")

_s3_client = None


def get_s3_client():
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    if boto3 is None:
        raise RuntimeError("boto3 is required to create an S3 client")
    _s3_client = boto3.client("s3")
    return _s3_client


@dataclass
class BatchManifest:
    """Metadata for a scrape batch."""

    batch_id: str
    scraped_at: datetime
    objects: Sequence[str]

    @classmethod
    def from_json(cls, payload: Dict) -> "BatchManifest":
        try:
            batch_id = payload["batch_id"]
            scraped_at_raw = payload["scraped_at"]
            objects = payload["objects"]
        except KeyError as exc:  # pragma: no cover - defensive programming
            raise ValueError(f"Manifest is missing required field: {exc.args[0]}") from exc

        if not isinstance(objects, Sequence) or isinstance(objects, (str, bytes)):
            raise ValueError("Manifest 'objects' must be a sequence")

        scraped_at = parse_datetime(scraped_at_raw)
        return cls(batch_id=batch_id, scraped_at=scraped_at, objects=list(objects))


def parse_datetime(value: str) -> datetime:
    """Parse a timestamp from ISO8601 or epoch seconds."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)

    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            if value.endswith("Z"):
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
        except (ValueError, TypeError):
            continue
    # Fallback to fromisoformat for other variations
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Unsupported datetime format: {value}") from exc


def lambda_handler(event, _context):
    """Entry point for AWS Lambda."""
    if not BUCKET_NAME:
        raise RuntimeError("BUCKET_NAME environment variable is required")

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        if bucket != BUCKET_NAME:
            # Skip events for other buckets that may be configured.
            continue
        process_manifest_object(bucket, key)


def process_manifest_object(bucket: str, key: str) -> None:
    """Load a manifest file and process its batch."""
    payload = json.loads(read_s3_text(bucket, key))
    manifest = BatchManifest.from_json(payload)

    curated_records = []
    for raw_object in manifest.objects:
        raw_key = raw_object if raw_object.startswith(RAW_PREFIX) else f"{RAW_PREFIX}{raw_object}"
        raw_payload = json.loads(read_s3_text(bucket, raw_key))
        curated_records.append(
            build_curated_record(raw_payload, manifest.scraped_at)
        )

    write_curated_batch(bucket, manifest.batch_id, curated_records, manifest)


def build_curated_record(payload: Dict, scraped_at: datetime) -> Dict:
    """Extract the curated schema from the raw payload."""
    aweme_id_value = payload.get("aweme_id") or payload.get("id") or payload.get("awemeId")
    if aweme_id_value is None:
        raise ValueError("Raw payload does not contain an aweme identifier")
    aweme_id = str(aweme_id_value)
    desc = payload.get("desc") or payload.get("description") or ""
    create_time = payload.get("create_time") or payload.get("createTime")
    statistics = payload.get("statistics") or {}

    hashtags: List[str] = []
    for collection in (
        payload.get("hashtags"),
        payload.get("text_extra"),
        payload.get("textExtra"),
    ):
        if isinstance(collection, Iterable):
            for item in collection:
                if isinstance(item, dict):
                    value = item.get("hashtag_name") or item.get("hashtagName") or item.get("name")
                    if value:
                        hashtags.append(value)
                elif isinstance(item, str):
                    hashtags.append(item)

    record = {
        "aweme_id": aweme_id,
        "scraped_at": scraped_at.isoformat(),
        "desc": desc,
        "hashtags": sorted(set(hashtags)),
        "create_time": create_time,
        "statistics": statistics,
    }
    return record


def write_curated_batch(
    bucket: str, batch_id: str, records: Sequence[Dict], manifest: BatchManifest
) -> None:
    if not records:
        return

    curated_key = f"{CURATED_PREFIX}batch_id={batch_id}/part-0000.jsonl"
    body = "\n".join(json.dumps(record, separators=(",", ":")) for record in records)
    client = get_s3_client()
    client.put_object(Bucket=bucket, Key=curated_key, Body=body.encode("utf-8"))

    curated_manifest_key = f"{CURATED_MANIFEST_PREFIX}{batch_id}.json"
    client.put_object(
        Bucket=bucket,
        Key=curated_manifest_key,
        Body=json.dumps(
            {
                "batch_id": batch_id,
                "scraped_at": manifest.scraped_at.isoformat(),
                "raw_manifest": manifest.objects,
                "curated_object": curated_key,
            },
            separators=(",", ":"),
        ).encode("utf-8"),
    )


def read_s3_text(bucket: str, key: str) -> str:
    client = get_s3_client()
    response = client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")
