# Sample Batch

The file `sample_batch.json` contains four synthetic TikTok metadata records designed to exercise the rule-based detectors and the conflict resolver. Each entry includes:

* A unique `aweme_id`.
* Caption text with keywords that map to the Good, Bad, Tea, and Weird signals.
* 15-minute spaced `create_time` stamps (Unix epoch seconds).
* Engagement statistics high enough to survive the default `--min-views` threshold.

Use this dataset to run the smoke test (`python scripts/smoke_test.py`) or to familiarise yourself with the output artefacts produced by `classification-pipeline`.
