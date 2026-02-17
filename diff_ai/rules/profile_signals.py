"""Repo-profile risk signals from user-defined config."""

from __future__ import annotations

import fnmatch
import re

from diff_ai.config import ProfileConfig, ProfilePathSignal, ProfilePatternSignal
from diff_ai.diff_parser import FileDiff
from diff_ai.rules.base import Finding


class ProfileSignalsRule:
    """Apply repo-specific path and pattern signals from config profile."""

    rule_id = "profile_signals"

    def __init__(self, profile: ProfileConfig | None = None) -> None:
        self._profile = profile or ProfileConfig()

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        findings: list[Finding] = []
        if not self._profile.has_signals():
            return findings

        changed_paths = [file_diff.path for file_diff in files]
        test_changed = any(
            _matches_any(file_diff.path, self._profile.tests.test_globs) for file_diff in files
        )

        for file_diff in files:
            path = file_diff.path
            findings.extend(
                self._path_signal_findings(
                    path,
                    self._profile.critical,
                    category="critical",
                )
            )
            findings.extend(
                self._path_signal_findings(
                    path,
                    self._profile.sensitive,
                    category="sensitive",
                )
            )
            findings.extend(self._pattern_findings(file_diff, self._profile.unsafe_added))

        required_matches = [
            path for path in changed_paths if _matches_any(path, self._profile.tests.required_for)
        ]
        if required_matches and not test_changed:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=12,
                    message="Profile requires tests for changed paths, but no tests changed.",
                    evidence=(
                        f"{len(required_matches)} matching path(s): "
                        + ", ".join(sorted(required_matches)[:5])
                    ),
                    scope="overall",
                    suggestion="Add or update tests for profile-required paths.",
                )
            )

        return findings

    def _path_signal_findings(
        self,
        path: str,
        signals: list[ProfilePathSignal],
        *,
        category: str,
    ) -> list[Finding]:
        findings: list[Finding] = []
        for signal in signals:
            if not fnmatch.fnmatch(path, signal.glob):
                continue
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=signal.points,
                    message=f"Profile {category} path matched.",
                    evidence=f"{path} matches {signal.glob} ({signal.reason}).",
                    scope=f"file:{path}",
                    suggestion="Review this path according to repository risk profile.",
                )
            )
        return findings

    def _pattern_findings(
        self,
        file_diff: FileDiff,
        signals: list[ProfilePatternSignal],
    ) -> list[Finding]:
        findings: list[Finding] = []
        seen: set[str] = set()
        for hunk in file_diff.hunks:
            for line in hunk.lines:
                if line.kind != "add":
                    continue
                for signal in signals:
                    if signal.regex in seen:
                        continue
                    if re.search(signal.regex, line.content):
                        seen.add(signal.regex)
                        findings.append(
                            Finding(
                                rule_id=self.rule_id,
                                points=signal.points,
                                message="Profile unsafe pattern added.",
                                evidence=(
                                    f"{file_diff.path} matches /{signal.regex}/ ({signal.reason})."
                                ),
                                scope=f"file:{file_diff.path}",
                                suggestion="Refactor to avoid configured unsafe pattern.",
                            )
                        )
        return findings


def _matches_any(path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in globs)
