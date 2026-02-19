"""Scoring orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field

from diff_ai.diff_parser import FileDiff, parse_unified_diff
from diff_ai.rules import default_rules, list_rule_info
from diff_ai.rules.base import Finding, Rule
from diff_ai.scoring_backend import RuleHit, score_rule_hits

_DEFAULT_RULE_CATEGORIES = {info.rule_id: info.category for info in list_rule_info()}


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
    raw_points_total: int = 0
    raw_points_by_category: dict[str, int] = field(default_factory=dict)
    capped_points_by_category: dict[str, float] = field(default_factory=dict)
    transformed_score: float = 0.0
    final_score_0_100: int = 0
    reasons_topN: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.final_score_0_100 == 0 and self.overall_score != 0:
            self.final_score_0_100 = self.overall_score
        elif self.overall_score == 0 and self.final_score_0_100 != 0:
            self.overall_score = self.final_score_0_100


def score_diff_text(diff_text: str, rules: list[Rule] | None = None) -> ScoreResult:
    """Parse and score unified diff text."""
    parsed_files = parse_unified_diff(diff_text)
    return score_files(parsed_files, rules=rules)


def score_files(files: list[FileDiff], rules: list[Rule] | None = None) -> ScoreResult:
    """Score already parsed diff files.

    Rule detection remains unchanged; score aggregation is delegated to
    ``diff_ai.scoring_backend`` for capped category bucketing and
    diminishing-returns transformation.
    """
    active_rules = rules if rules is not None else default_rules()
    all_findings: list[Finding] = []
    for rule in active_rules:
        all_findings.extend(rule.evaluate(files))

    rule_categories = _rule_categories(active_rules)
    rule_hits = [
        _finding_to_rule_hit(finding, rule_categories=rule_categories)
        for finding in all_findings
    ]
    breakdown = score_rule_hits(rule_hits)

    scored_files = _init_file_scores(files)
    file_map = {scored_file.path: scored_file for scored_file in scored_files}

    for finding in all_findings:
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
        overall_score=breakdown.final_score_0_100,
        files=scored_files,
        findings=all_findings,
        raw_points_total=breakdown.raw_points_total,
        raw_points_by_category=breakdown.raw_points_by_category,
        capped_points_by_category=breakdown.capped_points_by_category,
        transformed_score=breakdown.transformed_score,
        final_score_0_100=breakdown.final_score_0_100,
        reasons_topN=breakdown.reasons_topN,
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


def _finding_to_rule_hit(finding: Finding, *, rule_categories: dict[str, str]) -> RuleHit:
    scope_kind, path, hunk_index = _parse_scope(finding.scope)
    if scope_kind == "hunk":
        normalized_scope = "hunk"
    elif scope_kind == "file":
        normalized_scope = "file"
    else:
        normalized_scope = "global"

    return RuleHit(
        id=finding.rule_id,
        category=rule_categories.get(finding.rule_id, "unknown"),
        points=finding.points,
        scope=normalized_scope,
        file_path=path or None,
        hunk_id=hunk_index,
        message=finding.message,
        evidence=finding.evidence,
    )


def _rule_categories(rules: list[Rule]) -> dict[str, str]:
    categories = dict(_DEFAULT_RULE_CATEGORIES)
    for rule in rules:
        rule_id = getattr(rule, "rule_id", None)
        if not isinstance(rule_id, str) or rule_id in categories:
            continue
        category = getattr(rule, "category", None)
        if isinstance(category, str) and category:
            categories[rule_id] = category
    return categories


def _clamp(value: int, lower: int = 0, upper: int = 100) -> int:
    return max(lower, min(upper, value))
