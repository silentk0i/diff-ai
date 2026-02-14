"""Base rule protocol and finding model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from diff_ai.diff_parser import FileDiff


@dataclass(slots=True)
class Finding:
    """A single risk finding emitted by a rule."""

    rule_id: str
    points: int
    message: str
    evidence: str
    scope: str
    suggestion: str


class Rule(Protocol):
    """Protocol for deterministic scoring rules."""

    rule_id: str

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        """Evaluate parsed files and return findings."""
