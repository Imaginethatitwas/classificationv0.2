import csv
import json
from pathlib import Path

import pytest

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
        return [
            {key: int(value) if key == PLAY_COUNT_COLUMN else value for key, value in row.items()}
            for row in reader
        ]


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
