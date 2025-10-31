"""Data structures for the classification pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set


@dataclass
class VideoRecord:
    """Normalized view of a TikTok metadata record."""

    aweme_id: str
    desc: str
    create_time: datetime
    view_count: int
    comment_count: int
    like_count: int
    share_count: int
    hashtags: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "VideoRecord":
        aweme_id = str(raw.get("aweme_id"))
        if not aweme_id:
            raise ValueError("aweme_id missing from record")

        desc = raw.get("desc") or ""
        create_ts = raw.get("create_time")
        if create_ts is None:
            raise ValueError(f"create_time missing for {aweme_id}")
        create_time = datetime.fromtimestamp(int(create_ts), tz=timezone.utc)

        statistics = raw.get("statistics") or {}
        view_count = int(statistics.get("play_count") or 0)
        comment_count = int(statistics.get("comment_count") or 0)
        like_count = int(statistics.get("digg_count") or 0)
        share_count = int(statistics.get("share_count") or 0)

        hashtags = sorted(set(_collect_hashtags(raw)))

        return cls(
            aweme_id=aweme_id,
            desc=desc,
            create_time=create_time,
            view_count=view_count,
            comment_count=comment_count,
            like_count=like_count,
            share_count=share_count,
            hashtags=hashtags,
            raw=raw,
        )


@dataclass
class ClassificationResult:
    """Final output of the combinatorial classification."""

    aweme_id: str
    category: str
    flag: Optional[str]
    active_signals: Set[str]
    scores: Dict[str, float]


def _collect_hashtags(raw: Dict[str, Any]) -> Iterable[str]:
    """Collect hashtags from several possible fields in the raw payload."""

    desc = raw.get("desc") or ""
    for token in desc.split():
        if token.startswith("#"):
            yield token.strip()

    text_extra = raw.get("text_extra") or []
    for item in text_extra:
        name = item.get("hashtag_name")
        if name:
            yield f"#{name}".strip()

    cha_list = raw.get("cha_list") or []
    for challenge in cha_list:
        cha_name = challenge.get("cha_name")
        if cha_name:
            yield f"#{cha_name}".strip()


def batch_from_raw(records: Sequence[Dict[str, Any]]) -> List[VideoRecord]:
    """Convert a sequence of raw dicts into :class:`VideoRecord` objects."""

    output: List[VideoRecord] = []
    for raw in records:
        try:
            output.append(VideoRecord.from_raw(raw))
        except ValueError:
            # Skip records missing critical information.
            continue
    return output
