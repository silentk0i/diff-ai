"""Test-signal risk rule."""

from __future__ import annotations

from pathlib import PurePosixPath

from diff_ai.diff_parser import FileDiff
from diff_ai.rules.base import Finding


class TestSignalsRule:
    """Scores risk from presence or absence of test changes."""

    rule_id = "test_signals"

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        findings: list[Finding] = []

        changed_test_paths = [
            file_diff.path for file_diff in files if _is_test_path(file_diff.path)
        ]
        changed_code_paths = [
            file_diff.path
            for file_diff in files
            if _is_code_path(file_diff.path) and not _is_test_path(file_diff.path)
        ]
        deleted_tests = [
            file_diff.path
            for file_diff in files
            if file_diff.is_deleted_file and _is_test_path(file_diff.path)
        ]

        if changed_code_paths and not changed_test_paths:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=18,
                    message="Code changed without corresponding test changes.",
                    evidence=f"{len(changed_code_paths)} code files changed, 0 test files changed.",
                    scope="overall",
                    suggestion="Add or update tests covering the modified behaviors.",
                )
            )

        if changed_code_paths and changed_test_paths:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=-8,
                    message="Test updates accompany code changes.",
                    evidence=(
                        f"{len(changed_test_paths)} test files changed "
                        f"with {len(changed_code_paths)} code files."
                    ),
                    scope="overall",
                    suggestion="Ensure new tests cover boundary and failure scenarios.",
                )
            )

        if not changed_code_paths and changed_test_paths:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=-4,
                    message="Test-only changes reduce implementation risk.",
                    evidence=f"{len(changed_test_paths)} test files changed.",
                    scope="overall",
                    suggestion="Run full test suite to confirm signal quality.",
                )
            )

        for test_path in deleted_tests:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=12,
                    message="Test file removed.",
                    evidence=f"Deleted test file: {test_path}.",
                    scope=f"file:{test_path}",
                    suggestion="Confirm equivalent coverage remains elsewhere.",
                )
            )

        return findings


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    pure_path = PurePosixPath(lowered)
    name = pure_path.name
    return (
        lowered.startswith("tests/")
        or "/tests/" in lowered
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _is_code_path(path: str) -> bool:
    lowered = path.lower()
    if lowered.endswith(".md") or lowered.endswith(".rst") or lowered.endswith(".txt"):
        return False
    return "." in PurePosixPath(lowered).name
