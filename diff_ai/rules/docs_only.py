"""Documentation-only diff risk reducer."""

from __future__ import annotations

from pathlib import PurePosixPath

from diff_ai.diff_parser import FileDiff
from diff_ai.rules.base import Finding

DOC_SUFFIXES = {".md", ".rst", ".adoc", ".txt"}


class DocsOnlyRule:
    """Reduces risk score when a diff changes docs only."""

    rule_id = "docs_only"

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        if not files:
            return []
        if not all(_is_doc_path(file_diff.path) for file_diff in files):
            return []

        points = -16 if len(files) >= 8 else -12
        return [
            Finding(
                rule_id=self.rule_id,
                points=points,
                message="Documentation-only diff.",
                evidence=f"{len(files)} documentation files changed.",
                scope="overall",
                suggestion="Verify docs accurately describe implementation behavior.",
            )
        ]


def _is_doc_path(path: str) -> bool:
    lowered = path.lower()
    if lowered.startswith("docs/") or "/docs/" in lowered:
        return True
    return PurePosixPath(lowered).suffix in DOC_SUFFIXES
