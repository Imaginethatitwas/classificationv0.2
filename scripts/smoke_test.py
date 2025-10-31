#!/usr/bin/env python
"""Run a deterministic smoke test against the bundled sample dataset."""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from classification.curation import curate
from classification.pipeline import process_path

EXPECTED = {
    "1000000000000000001": ("good", None),
    "1000000000000000002": ("bad", None),
    "1000000000000000003": ("tea", None),
    "1000000000000000004": ("tea_weird", None),
}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sample_path = root / "examples" / "sample_batch.json"
    if not sample_path.exists():
        raise SystemExit(f"Sample batch not found at {sample_path}")

    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Verify curation removes duplicates and keeps the highest view count
        duplicate_payload = sample_path.read_text(encoding="utf-8")
        duplicate_path = tmpdir_path / "duplicates.json"
        duplicate_path.write_text(
            duplicate_payload[:-2]
            + ",\n  {\n    \"aweme_id\": \"1000000000000000002\",\n    \"desc\": \"Older snapshot with fewer views\",\n    \"create_time\": 1699990000,\n    \"statistics\": {\n      \"play_count\": 1000,\n      \"comment_count\": 1,\n      \"digg_count\": 1,\n      \"share_count\": 0\n    }\n  }\n]",
            encoding="utf-8",
        )

        curated_path = tmpdir_path / "curated.json"
        report = curate(duplicate_path, curated_path, min_views=0, overwrite=True)

        if report.retained != 4 or report.duplicates_dropped == 0:
            raise SystemExit("Curation did not retain the expected records")

        curated_data = json.loads(curated_path.read_text(encoding="utf-8"))
        if len(curated_data) != 4:
            raise SystemExit("Curated output should contain four unique items")
        view_counts = {
            item["aweme_id"]: item["statistics"]["play_count"] for item in curated_data
        }
        if view_counts.get("1000000000000000002") != 125000:
            raise SystemExit("Curation failed to keep the highest-view snapshot")

        results = process_path(curated_path, tmpdir_path, min_views=0)

        if len(results) != len(EXPECTED):
            raise SystemExit(
                f"Expected {len(EXPECTED)} results, received {len(results)}"
            )

        for result in results:
            expected_category, expected_flag = EXPECTED[result.aweme_id]
            if result.category != expected_category:
                raise SystemExit(
                    f"aweme {result.aweme_id} resolved to {result.category},"
                    f" expected {expected_category}"
                )
            if result.flag != expected_flag:
                raise SystemExit(
                    f"aweme {result.aweme_id} flag {result.flag} did not match"
                    f" expected {expected_flag}"
                )

        metrics_path = tmpdir_path / "bucket_metrics.csv"
        if not metrics_path.exists():
            raise SystemExit("bucket_metrics.csv was not produced")

        with metrics_path.open("r", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))

        if not rows:
            raise SystemExit("bucket_metrics.csv is empty")
        if not any(row.get("top_videos") for row in rows):
            raise SystemExit("No top_videos entries found in bucket metrics")

        categories = Counter(result.category for result in results)
        print("Smoke test passed!")
        for category, count in sorted(categories.items()):
            print(f"  {category}: {count}")
        print(f"Metrics written to {metrics_path}")


if __name__ == "__main__":
    main()
