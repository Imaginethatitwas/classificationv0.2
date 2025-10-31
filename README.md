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
