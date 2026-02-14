"""Destructive change risk rule."""

from __future__ import annotations

from pathlib import PurePosixPath

from diff_ai.diff_parser import FileDiff
from diff_ai.rules.base import Finding


class DestructiveChangesRule:
    """Raises risk when deletions dominate or files are removed."""

    rule_id = "destructive_changes"

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        findings: list[Finding] = []
        total_added = 0
        total_deleted = 0
        deleted_files = 0

        for file_diff in files:
            path = file_diff.path
            added, deleted = _count_changes(file_diff)
            total_added += added
            total_deleted += deleted

            if file_diff.is_deleted_file and not _is_low_risk_removed_path(path):
                deleted_files += 1
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        points=9,
                        message="File deletion detected.",
                        evidence=f"Deleted file: {path}.",
                        scope=f"file:{path}",
                        suggestion="Validate downstream imports and runtime references.",
                    )
                )

        if total_deleted >= 60 and total_deleted >= total_added * 2:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=10,
                    message="Deletion-heavy diff detected.",
                    evidence=f"{total_deleted} deleted lines vs {total_added} added lines.",
                    scope="overall",
                    suggestion="Double-check behavior removed by this change.",
                )
            )

        if deleted_files >= 3:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=8,
                    message="Multiple files deleted.",
                    evidence=f"{deleted_files} non-doc/test files were removed.",
                    scope="overall",
                    suggestion="Run integration checks for orphaned dependencies.",
                )
            )

        return findings


def _count_changes(file_diff: FileDiff) -> tuple[int, int]:
    added = 0
    deleted = 0
    for hunk in file_diff.hunks:
        for line in hunk.lines:
            if line.kind == "add":
                added += 1
            elif line.kind == "delete":
                deleted += 1
    return added, deleted


def _is_low_risk_removed_path(path: str) -> bool:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    return (
        lowered.startswith("docs/")
        or "/docs/" in lowered
        or lowered.startswith("tests/")
        or "/tests/" in lowered
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".md")
        or name.endswith(".rst")
    )
