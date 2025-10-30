# TikTok Scrape Ingestion

This repository provisions the storage layout for raw TikTok scrapes and ships
an ingestion Lambda that normalises the data into a curated table.

## Infrastructure overview

Terraform in `infra/` stands up:

* An S3 bucket with three logical prefixes:
  * `raw/` — incoming scrape JSON files partitioned by batch.
  * `curated/` — JSON Lines files with the curated schema.
  * `curated_manifests/` — summary manifests that link raw batches to curated
    outputs.
* Bucket lifecycle rules that
  * transition raw assets to the `STANDARD_IA` storage class after 30 days and
    expire them after one year,
  * expire curated data after two years,
  * keep previous versions via S3 versioning, and
  * enforce default KMS-based encryption and block all public access.
* An AWS Lambda function that is triggered whenever a raw batch manifest is
  uploaded. The Lambda extracts the required fields and publishes the curated
  artefacts.

### Deploying the infrastructure

```
cd infra
terraform init
terraform apply \
  -var="bucket_name=<your-bucket-name>" \
  -var="lambda_package=../dist/ingestion.zip"
```

Package the Lambda by zipping the repository root (or use your preferred build
pipeline). Ensure the archive contains the `ingestion_lambda/` package so that
the handler path `ingestion_lambda.ingestion_handler.lambda_handler` resolves
correctly. The handler expects the following environment variables which the
Terraform module sets automatically:

* `BUCKET_NAME` — target bucket name
* `RAW_PREFIX` — defaults to `raw/`
* `CURATED_PREFIX` — defaults to `curated/`
* `CURATED_BATCH_MANIFEST_PREFIX` — defaults to `curated_manifests/`

## Raw scrape layout

Every scrape batch should upload its raw JSON payloads to
`raw/<batch_id>/<aweme_id>.json` and include a manifest at
`raw/<batch_id>/manifest.json`. The manifest schema is:

```json
{
  "batch_id": "batch-20240601-1200",
  "scraped_at": "2024-06-01T12:00:00Z",
  "objects": [
    "raw/batch-20240601-1200/12345.json",
    "raw/batch-20240601-1200/67890.json"
  ]
}
```

The Lambda uses `scraped_at` as the ingestion timestamp and iterates over every
raw object in `objects`. Non-prefixed entries are automatically prefixed with
`raw/`.

## Curated output

For each batch the ingestion Lambda writes a JSON Lines file to
`curated/batch_id=<batch_id>/part-0000.jsonl`. Each line contains the required
fields:

```json
{
  "aweme_id": "12345",
  "scraped_at": "2024-06-01T12:00:00+00:00",
  "desc": "Video description",
  "hashtags": ["dogs", "fun"],
  "create_time": 1717214400,
  "statistics": {
    "digg_count": 10,
    "play_count": 1024
  }
}
```

The job also stores `curated_manifests/<batch_id>.json` to register a linkage
between the raw files and the curated output artefact.

## Local testing

Create a virtual environment, install dependencies, and run the unit tests:

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

The tests rely on `moto` to simulate S3 interactions and cover the ingestion
flow end-to-end.
