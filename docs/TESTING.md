# Testing & Validation

This document outlines reproducible steps to confirm that the pipeline ingests curated datasets correctly, applies the combinatorial logic, and emits artefacts that match expectations.

## 1. Smoke test with bundled sample data

A miniature batch is provided under `examples/sample_batch.json`. It covers distinct signal combinations so that the resolver exercises the Safety Override, Karpman filter, and multi-label paths.

Run the automated smoke test script:

```bash
python scripts/smoke_test.py
```

The script performs the following checks:

1. Builds a temporary batch with a duplicate `aweme_id` and runs `classification-curate` programmatically to ensure the curation step keeps the highest-view snapshot while discarding lower-view duplicates.
2. Calls `classification.pipeline.process_path` on the curated output with `min_views=0` so that all sample clips are processed.
3. Verifies that four classification results are returned.
4. Confirms that the resolved categories span the expected set (`good`, `bad`, `tea`, `tea_weird`) and that no unexpected flags are emitted.
5. Writes temporary artefacts (JSONL/CSV) and validates that the metrics file contains at least one bucket with top-video entries.

The script prints a concise summary and exits with status code 0 on success. Any assertion failure indicates a regression in either the detectors or the logic layer.

## 2. End-to-end validation against curated S3 batches

Once the smoke test passes, run the full pipeline on a recent curated batch from S3:

```bash
classification-curate s3://your-bucket/raw/ \
  s3://your-bucket/curated/acceptances_full/ \
  --min-views 50000 --overwrite

classification-pipeline s3://your-bucket/curated/acceptances_full/ \
  --output ./outputs \
  --min-views 50000
```

### Validate the outputs

1. **Spot-check classifications:**
   * Open `outputs/classified_records.jsonl`.
   * Inspect a few entries with known characteristics (e.g., deliberately "good" clips) and confirm that `category`, `flag`, and `active_signals` match expectations.
   * If the heuristics disagree, adjust the seeds in `classification/seeds.py` or lower/raise thresholds in `classification.logic.ConflictResolver`.

2. **Verify aggregation integrity:**
   * Load `outputs/bucket_metrics.csv` into your analytics tool of choice or open it in a spreadsheet.
   * Ensure that bucket timestamps align to 15-minute boundaries and that the `top_videos` column lists three entries (or fewer when the bucket contains fewer than three clips).
   * Cross-check the sum of `total_views` for a bucket against the raw records for that time slice.

3. **Regression harness (optional):**
   * Persist a "golden" copy of the JSONL/CSV outputs for a known scrape date under `tests/golden/` in your internal repo.
   * As you evolve the NLP models, compare new outputs to the golden files using a diff tool to monitor how categories shift.

## 3. Continuous monitoring hooks

* Integrate the smoke test into your CI pipeline so that changes to the detectors, logic layer, or IO helpers are validated automatically.
* For production jobs, log the number of accepted vs. filtered clips and emit alerts when the counts drop unexpectedly — this usually indicates upstream ingestion issues.

Following these steps ensures the pipeline behaves consistently from local development through production deployments.
