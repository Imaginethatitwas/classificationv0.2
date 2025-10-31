"""Signal definitions used by the classifiers and logic layer."""

from __future__ import annotations

from enum import Enum


class Signal(str, Enum):
    GOOD = "G"
    BAD = "B"
    TEA = "T"
    WEIRD = "W"

    def label(self) -> str:
        return self.value
