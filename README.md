# classificationv0.2

This repository contains a lightweight scaffolding of the TikTok
multi-signal classification workflow described in the project brief. It
provides:

* Normalisation utilities that load curated JSON/CSV payloads into
  dataclasses.
* A rule-based approximation of the independent signal detectors using
  the seed lexicons for Good, Bad, Tea, and Weird.
* A logic layer that implements the 15-cell conflict matrix, including
  heuristics for counterspeech, the Karpman filter, and the disturbing
  content amplifier.
* Aggregation helpers that collapse classified videos into 15-minute
  market buckets and capture the top three clips per bucket for
  traceability.
* Two CLIs: `classification-curate` prepares the deduplicated
  `acceptances_full` batches directly from S3, and `classification-pipeline`
  classifies those curated records and emits the analytics artefacts.

## Quick start

Install the package in editable mode:

```bash
python -m pip install -e .
```

First, curate the raw scrapes into a deduplicated dataset. The command keeps
the highest-view snapshot per `aweme_id`, drops clips below the threshold, and
writes the enriched payloads back to disk or S3:

```bash
classification-curate s3://your-bucket/raw/ \ 
  s3://your-bucket/curated/acceptances_full/ \ 
  --min-views 50000 --overwrite
```

Then run the classifier over the curated dataset (local paths or S3
prefix/object):

```bash
classification-pipeline ./path/to/acceptances_full --output ./outputs --min-views 50000
# or read directly from S3
classification-pipeline s3://your-bucket/curated/acceptances_full/ --output ./outputs
```

When pointing at S3 URIs, ensure the environment has AWS credentials with read
access to the bucket; the pipeline uses `boto3` under the hood and will stream
JSON/CSV objects directly without a manual sync step.

The command produces two artefacts inside `./outputs`:

* `classified_records.jsonl` – one line per accepted video containing the
  final category, flags, active signals, and detector scores.
* `bucket_metrics.csv` – 15-minute aggregations with video counts,
  engagement totals, and the top three clips per bucket (including
  permalinks for quick manual review).

The scaffolding is intentionally modular. Replace the rule-based
`detect_signals` function with the spaCy `textcat_multilabel` model once
it has been trained, and plug your learned secondary classifiers into the
hooks inside `logic.ConflictResolver` as they become available.

## Documentation & smoke tests

* See `docs/IMPLEMENTATION_GUIDE.md` for a detailed walkthrough of how to
  connect the S3 ingestion flow, wire the CLI into your orchestrator, and swap
  in trained NLP models.
* See `docs/TESTING.md` for validation procedures, including the bundled smoke
  test.
* To run the smoke test locally, execute:

  ```bash
  python scripts/smoke_test.py
  ```

  This verifies that the sample dataset in `examples/sample_batch.json` can be
  processed end-to-end and that the logic layer emits the expected
  classifications and market buckets.
