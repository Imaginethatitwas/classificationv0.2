#!/usr/bin/env python
"""Run a deterministic smoke test against the bundled sample dataset."""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from classification.pipeline import process_path

EXPECTED = {
    "1000000000000000001": ("good", None),
    "1000000000000000002": ("bad", None),
    "1000000000000000003": ("tea", None),
    "1000000000000000004": ("tea_weird", None),
}


def main() -> None:
    sample_path = Path(__file__).resolve().parents[1] / "examples" / "sample_batch.json"
    if not sample_path.exists():
        raise SystemExit(f"Sample batch not found at {sample_path}")

    with TemporaryDirectory() as tmpdir:
        results = process_path(sample_path, tmpdir, min_views=0)

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

        metrics_path = Path(tmpdir) / "bucket_metrics.csv"
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
