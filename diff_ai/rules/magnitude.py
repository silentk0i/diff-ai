"""Magnitude-based risk rule."""

from __future__ import annotations

from diff_ai.diff_parser import FileDiff
from diff_ai.rules.base import Finding


class MagnitudeRule:
    """Scores risk from overall and per-file change size."""

    rule_id = "magnitude"

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        findings: list[Finding] = []

        file_change_totals: dict[str, int] = {}
        total_changed_lines = 0
        total_hunks = 0
        for file_diff in files:
            path = file_diff.path
            changed = 0
            for hunk in file_diff.hunks:
                total_hunks += 1
                for line in hunk.lines:
                    if line.kind in {"add", "delete"}:
                        changed += 1
            file_change_totals[path] = changed
            total_changed_lines += changed

        if total_changed_lines >= 300:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=24,
                    message="Large diff volume increases regression risk.",
                    evidence=f"{total_changed_lines} changed lines across {len(files)} files.",
                    scope="overall",
                    suggestion="Split into smaller PRs or add staged rollout controls.",
                )
            )
        elif total_changed_lines >= 120:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=14,
                    message="Moderately large diff size.",
                    evidence=f"{total_changed_lines} changed lines.",
                    scope="overall",
                    suggestion="Prioritize review of highest-change files.",
                )
            )
        elif total_changed_lines >= 40:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=6,
                    message="Non-trivial amount of changed code.",
                    evidence=f"{total_changed_lines} changed lines.",
                    scope="overall",
                    suggestion="Focus review on edge cases and failure paths.",
                )
            )

        if len(files) >= 15:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=10,
                    message="Wide file spread increases integration risk.",
                    evidence=f"{len(files)} files changed.",
                    scope="overall",
                    suggestion="Verify cross-module behavior with integration tests.",
                )
            )
        elif len(files) >= 8:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=5,
                    message="Multiple files touched.",
                    evidence=f"{len(files)} files changed.",
                    scope="overall",
                    suggestion="Check for incidental coupling and unintended side effects.",
                )
            )

        if total_hunks >= 20:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=6,
                    message="Many change hunks increase review complexity.",
                    evidence=f"{total_hunks} hunks in this diff.",
                    scope="overall",
                    suggestion="Review by file/hunk in multiple passes.",
                )
            )

        for path, changed in file_change_totals.items():
            points = _points_for_file_size(changed)
            if points <= 0:
                continue
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=points,
                    message="File has substantial code churn.",
                    evidence=f"{changed} changed lines in {path}.",
                    scope=f"file:{path}",
                    suggestion="Request focused review from an owner of this area.",
                )
            )

        return findings


def _points_for_file_size(changed_lines: int) -> int:
    if changed_lines >= 160:
        return 12
    if changed_lines >= 80:
        return 8
    if changed_lines >= 30:
        return 4
    return 0
