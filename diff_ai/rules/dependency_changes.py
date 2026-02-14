"""Dependency change risk rule."""

from __future__ import annotations

from pathlib import PurePosixPath

from diff_ai.diff_parser import FileDiff
from diff_ai.rules.base import Finding

MANIFEST_FILES = {
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "package.json",
    "pom.xml",
    "cargo.toml",
    "go.mod",
}

LOCK_FILES = {
    "poetry.lock",
    "pdm.lock",
    "pipfile.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "cargo.lock",
}


class DependencyChangesRule:
    """Raises risk when dependency manifests or lock files are modified."""

    rule_id = "dependency_changes"

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        findings: list[Finding] = []
        dep_file_count = 0

        for file_diff in files:
            path = file_diff.path
            filename = PurePosixPath(path).name.lower()
            changed_lines = _changed_lines(file_diff)
            if changed_lines == 0:
                continue

            if filename in MANIFEST_FILES:
                dep_file_count += 1
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        points=8,
                        message="Dependency manifest changed.",
                        evidence=f"{filename} updated with {changed_lines} changed lines.",
                        scope=f"file:{path}",
                        suggestion="Review version bumps for compatibility and security impact.",
                    )
                )
            elif filename in LOCK_FILES:
                dep_file_count += 1
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        points=5,
                        message="Dependency lock file changed.",
                        evidence=f"{filename} updated with {changed_lines} changed lines.",
                        scope=f"file:{path}",
                        suggestion="Verify lockfile diff matches intended dependency updates.",
                    )
                )

        if dep_file_count >= 3:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=6,
                    message="Multiple dependency files changed.",
                    evidence=f"{dep_file_count} dependency-related files modified.",
                    scope="overall",
                    suggestion="Run dependency audits and full regression tests.",
                )
            )

        return findings


def _changed_lines(file_diff: FileDiff) -> int:
    changed = 0
    for hunk in file_diff.hunks:
        for line in hunk.lines:
            if line.kind in {"add", "delete"}:
                changed += 1
    return changed
