import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

import io
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from ingestion_lambda import ingestion_handler


class FakeS3Client:
    def __init__(self):
        self.storage = {}

    def create_bucket(self, Bucket: str):
        self.storage.setdefault(Bucket, {})

    def put_object(self, Bucket: str, Key: str, Body: bytes):
        self.storage.setdefault(Bucket, {})[Key] = Body

    def get_object(self, Bucket: str, Key: str):
        body = self.storage[Bucket][Key]
        return {"Body": io.BytesIO(body)}


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    monkeypatch.setenv("RAW_PREFIX", "raw/")
    monkeypatch.setenv("CURATED_PREFIX", "curated/")
    monkeypatch.setenv("CURATED_BATCH_MANIFEST_PREFIX", "curated_manifests/")
    yield
    ingestion_handler.BUCKET_NAME = os.environ.get("BUCKET_NAME")
    ingestion_handler._s3_client = None


def test_process_manifest_creates_curated_objects(monkeypatch):
    bucket_name = "test-scrape-bucket"
    monkeypatch.setenv("BUCKET_NAME", bucket_name)
    ingestion_handler.BUCKET_NAME = bucket_name

    s3 = FakeS3Client()
    s3.create_bucket(Bucket=bucket_name)
    ingestion_handler._s3_client = s3

    batch_id = "batch-123"
    raw_key = f"raw/{batch_id}/aweme-1.json"
    raw_payload = {
        "aweme_id": "123",
        "desc": "A funny video",
        "create_time": 1700000000,
        "statistics": {"digg_count": 10, "play_count": 100},
        "text_extra": [{"hashtag_name": "Comedy"}, {"name": "fun"}],
    }
    s3.put_object(Bucket=bucket_name, Key=raw_key, Body=json.dumps(raw_payload).encode("utf-8"))

    manifest_key = f"raw/{batch_id}/manifest.json"
    manifest_body = {
        "batch_id": batch_id,
        "scraped_at": "2024-01-01T00:00:00Z",
        "objects": [raw_key],
    }
    s3.put_object(Bucket=bucket_name, Key=manifest_key, Body=json.dumps(manifest_body).encode("utf-8"))

    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket_name},
                    "object": {"key": manifest_key},
                }
            }
        ]
    }

    ingestion_handler.lambda_handler(event, None)

    curated_key = f"curated/batch_id={batch_id}/part-0000.jsonl"
    curated_object = s3.get_object(Bucket=bucket_name, Key=curated_key)
    lines = curated_object["Body"].read().decode("utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record == {
        "aweme_id": "123",
        "scraped_at": "2024-01-01T00:00:00+00:00",
        "desc": "A funny video",
        "hashtags": ["Comedy", "fun"],
        "create_time": 1700000000,
        "statistics": {"digg_count": 10, "play_count": 100},
    }

    curated_manifest_key = f"curated_manifests/{batch_id}.json"
    curated_manifest = json.loads(
        s3.get_object(Bucket=bucket_name, Key=curated_manifest_key)["Body"].read().decode("utf-8")
    )
    assert curated_manifest["curated_object"] == curated_key
    assert curated_manifest["batch_id"] == batch_id


def test_parse_datetime_accepts_epoch(monkeypatch):
    bucket_name = "test"
    monkeypatch.setenv("BUCKET_NAME", bucket_name)
    ingestion_handler.BUCKET_NAME = bucket_name

    s3 = FakeS3Client()
    s3.create_bucket(Bucket=bucket_name)
    ingestion_handler._s3_client = s3

    batch_id = "batch-epoch"
    raw_key = f"raw/{batch_id}/aweme-1.json"
    s3.put_object(
        Bucket=bucket_name,
        Key=raw_key,
        Body=json.dumps({"aweme_id": "123", "statistics": {}}).encode("utf-8"),
    )
    manifest_key = f"raw/{batch_id}/manifest.json"
    s3.put_object(
        Bucket=bucket_name,
        Key=manifest_key,
        Body=json.dumps({"batch_id": batch_id, "scraped_at": 1710000000, "objects": [raw_key]}).encode("utf-8"),
    )

    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket_name},
                    "object": {"key": manifest_key},
                }
            }
        ]
    }

    ingestion_handler.lambda_handler(event, None)

    curated_key = f"curated/batch_id={batch_id}/part-0000.jsonl"
    curated = s3.get_object(Bucket=bucket_name, Key=curated_key)
    record = json.loads(curated["Body"].read().decode("utf-8"))
    expected = datetime.fromtimestamp(1710000000, tz=timezone.utc).isoformat()
    assert record["scraped_at"] == expected
