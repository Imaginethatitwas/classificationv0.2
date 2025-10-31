"""Command line entry point for the curation workflow."""

from __future__ import annotations

import argparse

from .curation import curate


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate TikTok metadata batches")
    parser.add_argument("source", help="Raw dataset path or S3 prefix to process")
    parser.add_argument(
        "destination",
        help="Output path or S3 prefix for curated records",
    )
    parser.add_argument(
        "--min-views",
        dest="min_views",
        type=int,
        default=50_000,
        help="Minimum play count a record must have to be retained",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Remove existing JSON files at the destination before writing",
    )
    args = parser.parse_args()

    report = curate(
        args.source,
        args.destination,
        min_views=args.min_views,
        overwrite=args.overwrite,
    )

    message = (
        f"Curated {report.retained} of {report.total_records} records. "
        f"Dropped {report.duplicates_dropped} duplicates and "
        f"{report.below_threshold} below-threshold items. "
        f"Output: {report.output_location}"
    )
    print(message)


if __name__ == "__main__":
    main()

