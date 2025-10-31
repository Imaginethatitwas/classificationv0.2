import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest

import data_pipeline.aweme_processing as aweme_processing
from data_pipeline.aweme_processing import (
    JsonlQueuePublisher,
    PLAY_COUNT_COLUMN,
    AWEME_ID_COLUMN,
    partition_by_play_count,
    process_curated_table,
    select_top_aweme_by_play_count,
)


def _sample_records():
    return [
        {AWEME_ID_COLUMN: "1", PLAY_COUNT_COLUMN: 20_000, "caption": "low"},
        {AWEME_ID_COLUMN: "1", PLAY_COUNT_COLUMN: 80_000, "caption": "high"},
        {AWEME_ID_COLUMN: "2", PLAY_COUNT_COLUMN: 60_000, "caption": "ok"},
        {AWEME_ID_COLUMN: "3", PLAY_COUNT_COLUMN: 40_000, "caption": "nope"},
    ]


def test_select_top_aweme_by_play_count_picks_highest_play_count():
    records = _sample_records()
    result = select_top_aweme_by_play_count(records)
    assert len(result) == 3
    aweme1 = next(record for record in result if record[AWEME_ID_COLUMN] == "1")
    assert aweme1[PLAY_COUNT_COLUMN] == 80_000


def test_partition_by_play_count_splits_records():
    records = select_top_aweme_by_play_count(_sample_records())
    accepted, filtered = partition_by_play_count(records, threshold=50_000)
    assert {record[AWEME_ID_COLUMN] for record in accepted} == {"1", "2"}
    assert {record[AWEME_ID_COLUMN] for record in filtered} == {"3"}


def _write_csv(path: Path, records):
    fieldnames = list(records[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record)


def _read_csv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _write_jsonl(path: Path, records):
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


class _FakeStreamingBody:
    def __init__(self, payload: str):
        self._buffer = io.BytesIO(payload.encode("utf-8"))

    def read(self) -> bytes:
        return self._buffer.read()

    def close(self) -> None:
        self._buffer.close()


class _FakeS3Client:
    def __init__(self) -> None:
        self._expected_calls: list[tuple[str, dict[str, Any]]] = []

    def add_get_object(self, *, bucket: str, key: str, payload: str) -> None:
        self._expected_calls.append(
            ("get_object", {"Bucket": bucket, "Key": key, "payload": payload})
        )

    def add_put_object(
        self,
        *,
        bucket: str,
        key: str,
        payload: str,
        content_type: str,
    ) -> None:
        self._expected_calls.append(
            (
                "put_object",
                {
                    "Bucket": bucket,
                    "Key": key,
                    "payload": payload,
                    "ContentType": content_type,
                },
            )
        )

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        assert self._expected_calls, "No expected S3 calls configured"
        name, params = self._expected_calls.pop(0)
        assert name == "get_object"
        assert params["Bucket"] == Bucket
        assert params["Key"] == Key
        return {"Body": _FakeStreamingBody(params["payload"])}

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str
    ) -> dict[str, Any]:
        assert self._expected_calls, "No expected S3 calls configured"
        name, params = self._expected_calls.pop(0)
        assert name == "put_object"
        assert params["Bucket"] == Bucket
        assert params["Key"] == Key
        assert params["ContentType"] == ContentType
        assert Body == params["payload"].encode("utf-8")
        return {}

    def assert_no_pending(self) -> None:
        assert not self._expected_calls


def test_process_curated_table_writes_outputs(tmp_path: Path):
    records = _sample_records()
    input_path = tmp_path / "curated.csv"
    accepted_path = tmp_path / "accepted.csv"
    filtered_path = tmp_path / "filtered.csv"
    queue_path = tmp_path / "queue.jsonl"

    _write_csv(input_path, records)
    publisher = JsonlQueuePublisher(queue_path, append=False)

    accepted, filtered = process_curated_table(
        input_path,
        accepted_output=accepted_path,
        filtered_output=filtered_path,
        queue_publisher=publisher,
    )

    accepted_disk = _read_csv(accepted_path)
    filtered_disk = _read_csv(filtered_path)

    assert accepted_disk == accepted
    assert filtered_disk == filtered

    with queue_path.open("r", encoding="utf-8") as handle:
        queue_rows = [json.loads(line) for line in handle]

    assert len(queue_rows) == len(accepted)
    assert all(int(row[PLAY_COUNT_COLUMN]) >= 50_000 for row in queue_rows)


def test_process_curated_table_missing_columns(tmp_path: Path):
    input_path = tmp_path / "curated.csv"
    _write_csv(input_path, [{"caption": "oops"}])

    publisher = JsonlQueuePublisher(tmp_path / "queue.jsonl", append=False)

    with pytest.raises(KeyError):
        process_curated_table(
            input_path,
            accepted_output=tmp_path / "accepted.csv",
            filtered_output=tmp_path / "filtered.csv",
            queue_publisher=publisher,
        )


def test_process_curated_table_preserves_full_json_record(tmp_path: Path):
    raw_records = [
        {
            AWEME_ID_COLUMN: "1",
            "statistics": {"play_count": 20_000, "digg_count": 15},
            "desc": "low",
            "author": {"uid": "a1", "nickname": "Alice"},
        },
        {
            AWEME_ID_COLUMN: "1",
            "statistics": {"play_count": 120_000, "digg_count": 70},
            "desc": "high",
            "author": {"uid": "a1", "nickname": "Alice"},
            "extra": {"hashtags": ["fun", "dance"]},
        },
        {
            AWEME_ID_COLUMN: "2",
            "statistics": {"play_count": 55_000, "digg_count": 5},
            "desc": "ok",
        },
    ]

    input_path = tmp_path / "curated.jsonl"
    accepted_path = tmp_path / "accepted.jsonl"
    filtered_path = tmp_path / "filtered.jsonl"
    queue_path = tmp_path / "queue.jsonl"

    _write_jsonl(input_path, raw_records)

    publisher = JsonlQueuePublisher(queue_path, append=False)

    accepted, filtered = process_curated_table(
        input_path,
        accepted_output=accepted_path,
        filtered_output=filtered_path,
        queue_publisher=publisher,
    )

    with accepted_path.open("r", encoding="utf-8") as handle:
        accepted_disk = [json.loads(line) for line in handle if line.strip()]
    with filtered_path.open("r", encoding="utf-8") as handle:
        filtered_disk = [json.loads(line) for line in handle if line.strip()]
    with queue_path.open("r", encoding="utf-8") as handle:
        queue_disk = [json.loads(line) for line in handle if line.strip()]

    assert accepted_disk == accepted == [raw_records[1], raw_records[2]]
    assert filtered_disk == filtered == []
    assert queue_disk == accepted_disk


def test_load_curated_table_from_s3(monkeypatch):
    client = _FakeS3Client()

    records = [
        {AWEME_ID_COLUMN: "1", "statistics": {"play_count": 60_000}},
        {AWEME_ID_COLUMN: "2", "statistics": {"play_count": 10_000}},
    ]
    payload = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    client.add_get_object(bucket="bucket", key="path/curated.jsonl", payload=payload)
    monkeypatch.setattr(aweme_processing, "_get_s3_client", lambda: client)

    loaded = aweme_processing.load_curated_table("s3://bucket/path/curated.jsonl")

    client.assert_no_pending()

    assert loaded == records


def test_load_curated_table_from_directory(tmp_path: Path):
    batch_dir = tmp_path / "curated"
    batch_dir.mkdir()
    csv_path = batch_dir / "part1.csv"
    jsonl_path = batch_dir / "part2.jsonl"

    csv_records = [
        {AWEME_ID_COLUMN: "1", PLAY_COUNT_COLUMN: "10000", "caption": "first"},
        {AWEME_ID_COLUMN: "2", PLAY_COUNT_COLUMN: "55000", "caption": "second"},
    ]
    jsonl_records = [
        {AWEME_ID_COLUMN: "3", "statistics": {"play_count": 70_000}},
    ]

    _write_csv(csv_path, csv_records)
    _write_jsonl(jsonl_path, jsonl_records)

    loaded = aweme_processing.load_curated_table(batch_dir)

    assert loaded == csv_records + jsonl_records


def test_load_curated_table_from_s3_prefix(monkeypatch):
    client = _FakeS3Client()

    prefix = "input/curated/"
    records_a = [
        {AWEME_ID_COLUMN: "1", "statistics": {"play_count": 60_000}},
    ]
    records_b = [
        {AWEME_ID_COLUMN: "2", "statistics": {"play_count": 80_000}},
    ]
    payload_a = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records_a)
    payload_b = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records_b)

    client.add_get_object(bucket="bucket", key=f"{prefix}part-0.jsonl", payload=payload_a)
    client.add_get_object(bucket="bucket", key=f"{prefix}part-1.jsonl", payload=payload_b)

    monkeypatch.setattr(aweme_processing, "_get_s3_client", lambda: client)
    monkeypatch.setattr(
        aweme_processing,
        "_list_s3_keys",
        lambda uri: [f"{prefix}part-0.jsonl", f"{prefix}part-1.jsonl"],
    )

    loaded = aweme_processing.load_curated_table("s3://bucket/input/curated/")

    client.assert_no_pending()

    assert loaded == records_a + records_b


def test_process_curated_table_with_s3(monkeypatch):
    client = _FakeS3Client()

    source_records = [
        {AWEME_ID_COLUMN: "1", "statistics": {"play_count": 20_000}, "caption": "low"},
        {AWEME_ID_COLUMN: "1", "statistics": {"play_count": 80_000}, "caption": "high"},
        {AWEME_ID_COLUMN: "2", "statistics": {"play_count": 60_000}, "caption": "ok"},
        {AWEME_ID_COLUMN: "3", "statistics": {"play_count": 40_000}, "caption": "nope"},
    ]
    source_payload = "".join(
        json.dumps(record, ensure_ascii=False) + "\n" for record in source_records
    )
    client.add_get_object(bucket="bucket", key="input/curated.jsonl", payload=source_payload)

    accepted_expected = [source_records[1], source_records[2]]
    filtered_expected = [source_records[3]]
    accepted_payload = "".join(
        json.dumps(record, ensure_ascii=False) + "\n" for record in accepted_expected
    )
    filtered_payload = "".join(
        json.dumps(record, ensure_ascii=False) + "\n" for record in filtered_expected
    )

    client.add_put_object(
        bucket="bucket",
        key="output/accepted.jsonl",
        payload=accepted_payload,
        content_type="application/json",
    )
    client.add_put_object(
        bucket="bucket",
        key="output/filtered.jsonl",
        payload=filtered_payload,
        content_type="application/json",
    )
    client.add_put_object(
        bucket="bucket",
        key="output/queue.jsonl",
        payload=accepted_payload,
        content_type="application/json",
    )
    monkeypatch.setattr(aweme_processing, "_get_s3_client", lambda: client)

    publisher = JsonlQueuePublisher("s3://bucket/output/queue.jsonl", append=False)
    accepted, filtered = process_curated_table(
        "s3://bucket/input/curated.jsonl",
        accepted_output="s3://bucket/output/accepted.jsonl",
        filtered_output="s3://bucket/output/filtered.jsonl",
        queue_publisher=publisher,
    )

    client.assert_no_pending()

    assert accepted == accepted_expected
    assert filtered == filtered_expected
