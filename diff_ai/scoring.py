"""Scoring orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field

from diff_ai.diff_parser import FileDiff, parse_unified_diff
from diff_ai.rules import default_rules
from diff_ai.rules.base import Finding, Rule


@dataclass(slots=True)
class HunkScore:
    """Risk scoring details for a single hunk."""

    header: str
    score: int = 0
    findings: list[Finding] = field(default_factory=list)


@dataclass(slots=True)
class FileScore:
    """Risk scoring details for a single file."""

    path: str
    score: int = 0
    hunks: list[HunkScore] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


@dataclass(slots=True)
class ScoreResult:
    """Top-level score output from deterministic rules."""

    overall_score: int
    files: list[FileScore]
    findings: list[Finding]


def score_diff_text(diff_text: str, rules: list[Rule] | None = None) -> ScoreResult:
    """Parse and score unified diff text."""
    parsed_files = parse_unified_diff(diff_text)
    return score_files(parsed_files, rules=rules)


def score_files(files: list[FileDiff], rules: list[Rule] | None = None) -> ScoreResult:
    """Score already parsed diff files."""
    active_rules = rules if rules is not None else default_rules()
    all_findings: list[Finding] = []
    for rule in active_rules:
        all_findings.extend(rule.evaluate(files))

    scored_files = _init_file_scores(files)
    file_map = {scored_file.path: scored_file for scored_file in scored_files}
    overall = 0

    for finding in all_findings:
        overall += finding.points
        scope_kind, path, hunk_index = _parse_scope(finding.scope)

        if scope_kind == "overall":
            continue

        file_score = file_map.get(path)
        if file_score is None:
            continue

        file_score.score += finding.points
        file_score.findings.append(finding)

        if (
            scope_kind == "hunk"
            and hunk_index is not None
            and 0 <= hunk_index < len(file_score.hunks)
        ):
            file_score.hunks[hunk_index].score += finding.points
            file_score.hunks[hunk_index].findings.append(finding)

    for file_score in scored_files:
        file_score.score = _clamp(file_score.score)
        for hunk_score in file_score.hunks:
            hunk_score.score = _clamp(hunk_score.score)

    return ScoreResult(
        overall_score=_clamp(overall),
        files=scored_files,
        findings=all_findings,
    )


def _init_file_scores(files: list[FileDiff]) -> list[FileScore]:
    scored_files: list[FileScore] = []
    for file_diff in files:
        scored_files.append(
            FileScore(
                path=file_diff.path,
                hunks=[HunkScore(header=hunk.header) for hunk in file_diff.hunks],
            )
        )
    return scored_files


def _parse_scope(scope: str) -> tuple[str, str, int | None]:
    if scope == "overall":
        return ("overall", "", None)
    if scope.startswith("file:"):
        return ("file", scope[len("file:") :], None)
    if scope.startswith("hunk:"):
        remainder = scope[len("hunk:") :]
        path, sep, index_text = remainder.rpartition(":")
        if not sep:
            return ("file", remainder, None)
        try:
            return ("hunk", path, int(index_text))
        except ValueError:
            return ("file", path or remainder, None)
    return ("overall", "", None)


def _clamp(value: int, lower: int = 0, upper: int = 100) -> int:
    return max(lower, min(upper, value))
