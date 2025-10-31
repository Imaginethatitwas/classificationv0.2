# classificationv0.2

Utilities for processing curated TikTok datasets ahead of NLP classification.

## Pipeline overview

The pipeline performs three key steps:

1. Load the curated table (CSV or JSONL) and collapse duplicate `aweme_id`
   rows by keeping the entry with the highest `statistics.play_count` value.
2. Partition the deduplicated data into two tables:
   - **Accepted**: rows with at least 50,000 views (configurable).
   - **Filtered**: rows below the view threshold, emitted for auditing.
3. Persist the accepted records into an NLP processing queue. The default
   implementation writes JSONL lines that can be consumed by downstream
   services, but the `QueuePublisher` protocol allows for Kafka or database
   integrations.

## Running the pipeline

```bash
python -m data_pipeline.aweme_processing curated.csv accepted.csv filtered.csv queue.jsonl --threshold 50000
```

Input and output formats are inferred from file extensions: `.csv`, `.jsonl`,
or `.ndjson`.

### Working with folders and AWS S3 prefixes

The `input_path` argument can point to a single file or to a directory/prefix.
When you supply a folder (local) or a URI such as `s3://vanity-classifier/.../`,
the pipeline walks every CSV/JSONL/NDJSON object underneath that path, merges
the rows, and then performs the deduplication/threshold logic. This allows the
job to consume the raw Apify drops exactly where they land in S3.

All pipeline paths also accept `s3://bucket/key` URIs, letting you operate on
the curated datasets that Apify delivered into your S3 bucket. The command
below reads every curated object stored beneath the prefix, writes the
accepted/filtered partitions back to S3, and publishes the accepted rows into an
NLP queue file that also lives in S3:

```bash
python -m data_pipeline.aweme_processing \
  s3://aweme-curated/curated/ \
  s3://aweme-curated/processed/2024-07-11.accepted.jsonl \
  s3://aweme-curated/processed/2024-07-11.filtered.jsonl \
  s3://aweme-curated/queues/2024-07-11.queue.jsonl \
  --threshold 50000
```

Authenticate with AWS using any mechanism supported by `boto3` (environment
variables, IAM role in Codespaces, AWS SSO, etc.). The CLI automatically keeps
the highest `statistics.play_count` per `aweme_id`, writes both audit-friendly
and accepted tables, and ensures the queue output retains each record’s full
JSON payload for downstream NLP enrichment.

Once the `accepted` artefacts are written back to S3 (for example under
`curated/acceptances_full/`), Stage 3 of the pipeline can point directly at that
prefix without needing any intermediate manual downloads.

> **Note:** Install `boto3` in the environment where you run the pipeline:
> `pip install boto3`. Without it, the CLI falls back to local filesystem mode
> and raises a helpful error if an `s3://` path is supplied.

### Troubleshooting: `ModuleNotFoundError` for `data_pipeline`

If the CLI command reports that `data_pipeline` cannot be imported, double check
that your workspace contains the package directory:

```bash
ls
```

You should see a `data_pipeline/` folder. If it is missing, pull the latest
branch contents (e.g. `git fetch origin` followed by `git pull origin
group-and-filter-records-by-play-count`) or recreate the Codespace from the
updated branch so that the package files are available on disk. Once the folder
is present, rerunning the command from the repository root should succeed.

## Testing

```bash
pytest
```
