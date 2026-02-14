"""Tests for scoring and default MVP rules."""

from __future__ import annotations

from dataclasses import dataclass

from diff_ai.diff_parser import FileDiff, parse_unified_diff
from diff_ai.rules.base import Finding
from diff_ai.rules.critical_paths import CriticalPathsRule
from diff_ai.rules.magnitude import MagnitudeRule
from diff_ai.rules.test_signals import TestSignalsRule
from diff_ai.scoring import score_diff_text, score_files


def test_magnitude_rule_flags_large_file_churn() -> None:
    old_lines = [f"old-{idx}" for idx in range(1, 91)]
    new_lines = [f"new-{idx}" for idx in range(1, 91)]
    diff_text = _build_replace_diff("src/core.py", old_lines, new_lines)

    findings = MagnitudeRule().evaluate(parse_unified_diff(diff_text))
    scopes = {finding.scope for finding in findings}
    assert "overall" in scopes
    assert "file:src/core.py" in scopes

    overall_points = sum(f.points for f in findings if f.scope == "overall")
    assert overall_points >= 14
    file_points = sum(f.points for f in findings if f.scope == "file:src/core.py")
    assert file_points >= 12


def test_critical_paths_rule_matches_sensitive_paths() -> None:
    diff_text = "\n".join(
        [
            _build_replace_diff("src/auth/service.py", ["a"], ["b"]),
            _build_replace_diff("src/billing/invoice.py", ["a"], ["b"]),
            _build_replace_diff("db/migrations/20260214_add_table.sql", ["a"], ["b"]),
            _build_replace_diff(".github/workflows/release.yml", ["a"], ["b"]),
        ]
    )
    findings = CriticalPathsRule().evaluate(parse_unified_diff(diff_text))
    assert len(findings) == 4
    assert {finding.scope for finding in findings} == {
        "file:src/auth/service.py",
        "file:src/billing/invoice.py",
        "file:db/migrations/20260214_add_table.sql",
        "file:.github/workflows/release.yml",
    }
    assert sum(finding.points for finding in findings) == 53


def test_test_signals_rule_penalizes_code_without_tests() -> None:
    diff_text = _build_replace_diff("src/feature.py", ["a", "b"], ["c", "d"])
    findings = TestSignalsRule().evaluate(parse_unified_diff(diff_text))
    assert len(findings) == 1
    assert findings[0].scope == "overall"
    assert findings[0].points == 18


def test_test_signals_rule_rewards_test_updates() -> None:
    diff_text = "\n".join(
        [
            _build_replace_diff("src/feature.py", ["a"], ["b"]),
            _build_replace_diff("tests/test_feature.py", ["x"], ["y"]),
        ]
    )
    findings = TestSignalsRule().evaluate(parse_unified_diff(diff_text))
    assert len(findings) == 1
    assert findings[0].scope == "overall"
    assert findings[0].points == -8


def test_score_diff_text_aggregates_default_rules() -> None:
    old_lines = [f"old-{idx}" for idx in range(1, 36)]
    new_lines = [f"new-{idx}" for idx in range(1, 36)]
    diff_text = _build_replace_diff("src/auth/service.py", old_lines, new_lines)

    result = score_diff_text(diff_text)
    assert result.overall_score > 0
    assert len(result.files) == 1
    assert result.files[0].path == "src/auth/service.py"
    assert result.files[0].score > 0

    rule_ids = {finding.rule_id for finding in result.findings}
    assert "magnitude" in rule_ids
    assert "critical_paths" in rule_ids
    assert "test_signals" in rule_ids


def test_score_clamps_to_100() -> None:
    files = parse_unified_diff(_build_replace_diff("src/a.py", ["a"], ["b"]))
    result = score_files(files, rules=[_MaxRule()])
    assert result.overall_score == 100


@dataclass(slots=True)
class _MaxRule:
    rule_id: str = "max_rule"

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        _ = files
        return [
            Finding(
                rule_id=self.rule_id,
                points=500,
                message="Huge risk",
                evidence="Synthetic finding",
                scope="overall",
                suggestion="N/A",
            )
        ]


def _build_replace_diff(path: str, old_lines: list[str], new_lines: list[str]) -> str:
    old_count = len(old_lines)
    new_count = len(new_lines)
    header = [
        f"diff --git a/{path} b/{path}",
        "index 1111111..2222222 100644",
        f"--- a/{path}",
        f"+++ b/{path}",
        f"@@ -1,{old_count} +1,{new_count} @@",
    ]
    body = [f"-{line}" for line in old_lines] + [f"+{line}" for line in new_lines]
    return "\n".join(header + body)
