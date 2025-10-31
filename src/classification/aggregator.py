"""Aggregation utilities for 15-minute market buckets."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from .data import ClassificationResult, VideoRecord


@dataclass
class BucketMetrics:
    bucket_start: datetime
    category: str
    video_count: int
    total_views: int
    total_comments: int
    total_likes: int
    total_shares: int
    engagement_rate: float
    top_videos: List[Dict[str, object]] = field(default_factory=list)


def floor_to_interval(dt: datetime, minutes: int = 15) -> datetime:
    minutes_delta = (dt.minute // minutes) * minutes
    return datetime(
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        minutes_delta,
        tzinfo=dt.tzinfo or timezone.utc,
    )


def aggregate(records: Sequence[VideoRecord], results: Sequence[ClassificationResult]) -> List[BucketMetrics]:
    by_id = {record.aweme_id: record for record in records}
    buckets: Dict[tuple[datetime, str], List[VideoRecord]] = {}
    for result in results:
        record = by_id.get(result.aweme_id)
        if not record:
            continue
        bucket_key = (floor_to_interval(record.create_time), result.category)
        buckets.setdefault(bucket_key, []).append(record)

    metrics: List[BucketMetrics] = []
    for (bucket_start, category), bucket_records in sorted(buckets.items()):
        total_views = sum(r.view_count for r in bucket_records)
        total_comments = sum(r.comment_count for r in bucket_records)
        total_likes = sum(r.like_count for r in bucket_records)
        total_shares = sum(r.share_count for r in bucket_records)
        engagement_base = max(total_views, 1)
        engagement_rate = (total_comments + total_likes + total_shares) / engagement_base
        top_videos = _top_videos(bucket_records)
        metrics.append(
            BucketMetrics(
                bucket_start=bucket_start,
                category=category,
                video_count=len(bucket_records),
                total_views=total_views,
                total_comments=total_comments,
                total_likes=total_likes,
                total_shares=total_shares,
                engagement_rate=engagement_rate,
                top_videos=top_videos,
            )
        )
    return metrics


def write_bucket_metrics(metrics: Sequence[BucketMetrics], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "bucket_start",
        "category",
        "video_count",
        "total_views",
        "total_comments",
        "total_likes",
        "total_shares",
        "engagement_rate",
        "top_videos",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for metric in metrics:
            writer.writerow(
                {
                    "bucket_start": metric.bucket_start.isoformat(),
                    "category": metric.category,
                    "video_count": metric.video_count,
                    "total_views": metric.total_views,
                    "total_comments": metric.total_comments,
                    "total_likes": metric.total_likes,
                    "total_shares": metric.total_shares,
                    "engagement_rate": f"{metric.engagement_rate:.6f}",
                    "top_videos": _serialise_top_videos(metric.top_videos),
                }
            )


def _top_videos(records: Sequence[VideoRecord], limit: int = 3) -> List[Dict[str, object]]:
    sorted_records = sorted(records, key=lambda r: r.view_count, reverse=True)[:limit]
    top: List[Dict[str, object]] = []
    for record in sorted_records:
        top.append(
            {
                "aweme_id": record.aweme_id,
                "url": f"https://www.tiktok.com/@/video/{record.aweme_id}",
                "views": record.view_count,
                "comments": record.comment_count,
                "likes": record.like_count,
                "shares": record.share_count,
            }
        )
    return top


def _serialise_top_videos(top_videos: Iterable[Dict[str, object]]) -> str:
    parts = []
    for video in top_videos:
        parts.append(
            "|".join(
                [
                    video.get("aweme_id", ""),
                    str(video.get("views", "")),
                    str(video.get("comments", "")),
                    str(video.get("likes", "")),
                    str(video.get("shares", "")),
                    video.get("url", ""),
                ]
            )
        )
    return ";".join(parts)


__all__ = ["BucketMetrics", "aggregate", "floor_to_interval", "write_bucket_metrics"]
