"""Command line entry points for the classification pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import process_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the TikTok classification pipeline")
    parser.add_argument("source", help="Path to JSON/CSV file or directory to process")
    parser.add_argument("--output", dest="output", help="Directory for outputs", default=None)
    parser.add_argument(
        "--min-views",
        dest="min_views",
        type=int,
        default=50_000,
        help="Minimum play count required to include a record",
    )
    args = parser.parse_args()

    results = process_path(args.source, args.output, min_views=args.min_views)
    print(f"Processed {len(results)} records")


if __name__ == "__main__":
    main()
