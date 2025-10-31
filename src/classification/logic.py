"""Combinatorial conflict resolution layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set

from .data import ClassificationResult
from .detectors import (
    detect_signals,
    indicates_disturbing_content,
    indicates_karpman_roles,
    is_counterspeech,
    normalise_text,
)
from .signals import Signal

DEFAULT_SIGNAL_THRESHOLD = 0.55


@dataclass
class LogicConfig:
    threshold: float = DEFAULT_SIGNAL_THRESHOLD


class ConflictResolver:
    """Applies the 15-cell conflict matrix to detector scores."""

    def __init__(self, config: Optional[LogicConfig] = None) -> None:
        self.config = config or LogicConfig()

    def classify(self, aweme_id: str, text: str, scores: Optional[Dict[Signal, float]] = None) -> ClassificationResult:
        text_norm = normalise_text(text)
        scores = scores or detect_signals(text_norm)
        active = {
            signal
            for signal, score in scores.items()
            if score >= self.config.threshold
        }

        category, flag = self._resolve(text_norm, active)

        return ClassificationResult(
            aweme_id=aweme_id,
            category=category,
            flag=flag,
            active_signals={signal.value for signal in active},
            scores={signal.value: float(score) for signal, score in scores.items()},
        )

    # pylint: disable=too-many-return-statements,too-many-branches
    def _resolve(self, text: str, active: Set[Signal]) -> tuple[str, Optional[str]]:
        if not active:
            return "unclassified", None

        if active == {Signal.GOOD}:
            return "good", None
        if active == {Signal.BAD}:
            return "bad", None
        if active == {Signal.TEA}:
            return "tea", None
        if active == {Signal.WEIRD}:
            return "weird", None

        if active == {Signal.GOOD, Signal.BAD}:
            return "bad", "safety_override"
        if active == {Signal.GOOD, Signal.TEA}:
            if indicates_karpman_roles(text):
                return "tea", "karpman_conflict"
            return "good", "drama_entertainment"
        if active == {Signal.GOOD, Signal.WEIRD}:
            return "good", "absurd_humor"
        if active == {Signal.BAD, Signal.TEA}:
            if is_counterspeech(text):
                return "tea", "counterspeech"
            return "bad", "harmful_drama"
        if active == {Signal.BAD, Signal.WEIRD}:
            return "bad", "disturbing_content"
        if active == {Signal.TEA, Signal.WEIRD}:
            return "tea_weird", None

        if active == {Signal.GOOD, Signal.BAD, Signal.TEA}:
            if is_counterspeech(text):
                return "good", "good_counterspeech"
            return "bad", "safety_override"
        if active == {Signal.GOOD, Signal.BAD, Signal.WEIRD}:
            return "bad", "disturbing_content"
        if active == {Signal.GOOD, Signal.TEA, Signal.WEIRD}:
            if indicates_karpman_roles(text):
                return "tea_weird", "karpman_conflict"
            return "good", "absurd_humor"
        if active == {Signal.BAD, Signal.TEA, Signal.WEIRD}:
            if is_counterspeech(text):
                return "tea_weird", "counterspeech"
            return "bad", "disturbing_content"

        if active == {Signal.GOOD, Signal.BAD, Signal.TEA, Signal.WEIRD}:
            if is_counterspeech(text):
                if indicates_karpman_roles(text):
                    return "tea_weird", "counterspeech"
                return "good", "good_counterspeech"
            return "bad", "disturbing_content"

        # Fallback for unexpected combinations: prioritise harm > drama > weird > good.
        if Signal.BAD in active:
            if Signal.WEIRD in active or indicates_disturbing_content(text):
                return "bad", "disturbing_content"
            return "bad", "safety_override"
        if Signal.TEA in active and Signal.WEIRD in active:
            return "tea_weird", None
        if Signal.TEA in active:
            return "tea", None
        if Signal.WEIRD in active:
            return "weird", None
        return "good", None


__all__ = ["ConflictResolver", "LogicConfig", "DEFAULT_SIGNAL_THRESHOLD"]
