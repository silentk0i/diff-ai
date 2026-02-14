"""Error-handling risk rule."""

from __future__ import annotations

from diff_ai.diff_parser import FileDiff
from diff_ai.rules.base import Finding


class ErrorHandlingRule:
    """Detects weaker guardrails in changed code."""

    rule_id = "error_handling"

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        findings: list[Finding] = []
        for file_diff in files:
            path = file_diff.path
            bare_except = 0
            removed_guards = 0

            for hunk in file_diff.hunks:
                for line in hunk.lines:
                    stripped = line.content.strip()
                    if line.kind == "add" and stripped.startswith("except:"):
                        bare_except += 1

                    if line.kind == "delete" and (
                        stripped.startswith("raise ")
                        or stripped.startswith("assert ")
                        or stripped == "assert"
                    ):
                        removed_guards += 1

            if bare_except > 0:
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        points=min(12, bare_except * 6),
                        message="Bare except block introduced.",
                        evidence=f"{path} adds {bare_except} bare except statement(s).",
                        scope=f"file:{path}",
                        suggestion="Catch specific exception types and log context.",
                    )
                )

            if removed_guards > 0:
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        points=min(10, removed_guards * 3),
                        message="Guard/exception checks were removed.",
                        evidence=f"{path} removes {removed_guards} raise/assert statement(s).",
                        scope=f"file:{path}",
                        suggestion="Re-check failure-mode handling and invariants.",
                    )
                )

        return findings
