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
* A CLI (`classification-pipeline`) that ties the pieces together and
  writes both the classification results and aggregated metrics to disk.

## Quick start

Install the package in editable mode:

```bash
python -m pip install -e .
```

Run the pipeline over a directory of curated JSON/CSV exports:

```bash
classification-pipeline ./path/to/acceptances_full --output ./outputs --min-views 50000
```

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
