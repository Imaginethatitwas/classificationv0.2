"""Rule-based detectors that approximate the independent signal layer."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, Iterable

from .seeds import COUNTERSPEECH_HINTS, KARPMAN_HINTS, SEED_KEYWORDS
from .signals import Signal

TOKEN_RE = re.compile(r"[#\w']+")


def normalise_text(text: str) -> str:
    return " ".join(text.lower().split())


def tokenise(text: str) -> Iterable[str]:
    for match in TOKEN_RE.finditer(text.lower()):
        yield match.group(0)


def keyword_score(text: str, signal: Signal) -> float:
    keywords = SEED_KEYWORDS[signal]
    text_norm = text.lower()
    hits = sum(1 for kw in keywords if kw in text_norm)
    if hits == 0:
        return 0.0
    # Use a saturating function so repeated hits approach 1.0.
    return 1.0 - math.exp(-hits)


def detect_signals(text: str) -> Dict[Signal, float]:
    text_norm = normalise_text(text)
    scores = {signal: keyword_score(text_norm, signal) for signal in Signal}
    return scores


def is_counterspeech(text: str) -> bool:
    text_norm = normalise_text(text)
    tokens = set(tokenise(text_norm))
    if any(token in {"said", "saying"} for token in tokens):
        if '"' in text or "'" in text:
            return True
    for hint in COUNTERSPEECH_HINTS:
        if hint in text_norm:
            return True
    return False


def indicates_karpman_roles(text: str) -> bool:
    text_norm = normalise_text(text)
    for hint in KARPMAN_HINTS:
        if hint in text_norm:
            return True
    second_person = {"you", "your", "yourself"}
    tokens = Counter(tokenise(text_norm))
    return any(token in second_person for token in tokens if tokens[token] >= 2)


def indicates_disturbing_content(text: str) -> bool:
    text_norm = normalise_text(text)
    for hint in SEED_KEYWORDS[Signal.WEIRD]:
        if hint in text_norm:
            for bad_hint in ("blood", "gore", "scream", "nightmare"):
                if bad_hint in text_norm:
                    return True
    return False
