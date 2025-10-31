# Implementation Guide

This guide explains how to run and extend the TikTok multi-signal classification pipeline that ships with this repository. It mirrors the staged workflow discussed during planning so that you can plug the existing S3 ingestion flow straight into the NLP stack and iterate safely.

## 1. Prerequisites

* Python 3.10 or later.
* Access to the AWS account that stores the TikTok scrapes. The IAM identity must have permission to `s3:GetObject` (and optionally `s3:ListBucket`/`s3:PutObject`) on the relevant prefixes.
* Raw scrape batches organised by day/batch (either as local files or under an S3 prefix). The curation CLI will transform these into the deduplicated `acceptances_full` dataset required for Section 3.

Install the package in editable mode:

```bash
python -m pip install -e .
```

This exposes both CLI entry points (`classification-curate` and `classification-pipeline`) and pulls in `boto3` for S3 access.

## 2. Producing the curated dataset (Section 2)

Run the curation step against the raw scrape prefix. The command walks every JSON/CSV payload, rebuilds `VideoRecord`s, drops clips below the threshold, and keeps only the snapshot with the highest view count per `aweme_id`:

```bash
classification-curate s3://your-bucket/raw/ \
  s3://your-bucket/curated/acceptances_full/ \
  --min-views 50000 --overwrite
```

Key behaviours:

1. **Deduplication:** when the same `aweme_id` appears multiple times, the tool retains the record with the greatest `play_count` (breaking ties by the most recent `create_time`).
2. **Thresholding:** clips below `--min-views` are discarded before writing the curated batch.
3. **Full payload preservation:** each retained record is written back with the original JSON payload so the classifier has access to all metadata fields.
4. **Destination hygiene:** pass `--overwrite` when targeting a directory/prefix dedicated to `acceptances_full` so that previous curated files are cleared before the new snapshot is uploaded.

The command accepts local paths as well, enabling analysts to curate ad-hoc batches on their workstation when experimenting.

## 3. Directory conventions

The loader accepts either a local directory or an S3 prefix. Keep the curated exports under an `acceptances_full/` style directory that contains the de-duplicated CSV/JSON batches. Example S3 layout:

```
s3://your-bucket/curated/
  └── 2024-05-05/
      └── acceptances_full/
          ├── 20240505T0000_batch.csv
          ├── 20240505T0800_batch.json
          └── ...
```

Files can be nested arbitrarily; the loader walks sub-folders and accepts both CSV and JSON. Within CSVs, the `raw` column must contain the original JSON document for each video so that `VideoRecord.from_raw` can reconstruct the full payload.

## 4. Running the end-to-end pipeline

Run the CLI against either a local path or an S3 URI. The example below reads straight from S3 and writes artefacts to a local folder named `outputs`:

```bash
classification-pipeline s3://your-bucket/curated/acceptances_full/ \
  --output ./outputs \
  --min-views 50000
```

The command performs the following steps:

1. `io.load_records` resolves every curated batch (streaming from S3 if needed) and converts the payloads into `VideoRecord` dataclasses. Any remaining duplicates are collapsed in-memory using the same "keep highest view count" rule before the `--min-views` filter is applied.
2. `pipeline._classify_records` builds the feature text from the caption and hashtags, calls `detectors.detect_signals` to obtain four signal probabilities, and then hands the result to `logic.ConflictResolver` which applies the 15-cell matrix (including the Safety Override, Karpman filter, and Use-vs-Mention heuristics).
3. `aggregator.aggregate` groups all accepted videos into 15-minute UTC buckets per resolved category, computing summary metrics and selecting the three most-viewed clips for traceability.
4. Outputs are materialised inside the directory supplied to `--output`:
   * `classified_records.jsonl` — per-video classification details with scores and active signal flags.
   * `bucket_metrics.csv` — 15-minute metrics and top-three video lists for each bucket/category pair.

## 5. Integrating with the existing orchestration

1. **Scheduled runs:** trigger the CLI from your scheduler (e.g., cron, Airflow, Prefect) using the same S3 prefix pattern that your de-duplication step writes to. You can reuse the `--output` flag to push artefacts back into S3 by invoking `aws s3 sync` after the pipeline finishes.
2. **Manual analyst runs:** the CLI is idempotent. Analysts can pull down a development batch with `aws s3 sync` or point the CLI directly at a staging prefix. Provide a lightweight wrapper script or a web hook that collects the target prefix and runs the CLI with the desired thresholds.

## 6. Extending the NLP components

The scaffolding currently uses the rule-based seeds in `classification.detectors.detect_signals`. Replace this with your trained spaCy `textcat_multilabel` component once it is available:

1. Train the detector separately and persist it as a pipeline (e.g., `./models/multisignal`).
2. Update `detect_signals` to load the spaCy pipeline on first use and return the four probabilities.
3. For emergent states that require sub-models (Use vs Mention, Karpman filter, disturbing amplifier), plug the learned models into `classification.logic.ConflictResolver`. Each helper currently lives in a dedicated method to make swapping implementations trivial.

## 7. Output hand-off

* The JSONL can be ingested by your Blender animation workflow or forwarded to other analytics services. Each line contains the `aweme_id`, resolved `category`, optional `flag`, active signals, and the underlying probabilities.
* The CSV is intentionally wide so that other tools (dashboards, notebooks, Blender) can parse the metrics with minimal transformation. The `top_videos` column concatenates the three most-viewed clips with their stats using `;` and `|` separators — this keeps the file CSV-compatible while preserving the quick links back to the videos that moved the market.

## 8. Troubleshooting checklist

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `RuntimeError: boto3 is required` | The package is not installed in editable mode or `boto3` missing. | Re-run `python -m pip install -e .`. |
| `botocore.exceptions.NoCredentialsError` | AWS credentials not available in the environment. | Export `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` or configure an IAM role. |
| Empty `bucket_metrics.csv` | All records fell below `--min-views` or were missing stats. | Lower the threshold or validate the curated data for missing `play_count`. |
| Unexpected category/flag | The seed lexicons fired a different combination than expected. | Inspect the `scores` and `active_signals` fields in `classified_records.jsonl`, tweak the seeds in `classification/seeds.py`, or plug in the trained spaCy model. |

With these steps you can ingest batches straight from S3, run the combinatorial classification, and feed the artefacts into the downstream analytics/visualisation layers without additional wiring.
