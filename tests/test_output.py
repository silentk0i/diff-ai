"""Output rendering tests for Step 5."""

from __future__ import annotations

import json

from diff_ai.output import render_human, render_json
from diff_ai.rules.base import Finding
from diff_ai.scoring import FileScore, HunkScore, ScoreResult


def test_render_human_has_top_five_reasons_and_file_summary() -> None:
    findings = [
        _finding("rule_a", 9, "A"),
        _finding("rule_b", 8, "B"),
        _finding("rule_c", 7, "C"),
        _finding("rule_d", 6, "D"),
        _finding("rule_e", 5, "E"),
        _finding("rule_f", 4, "F"),
    ]
    result = ScoreResult(
        overall_score=62,
        files=[
            FileScore(
                path="src/api.py",
                score=22,
                hunks=[HunkScore(header="@@ -1 +1 @@", score=0, findings=[])],
                findings=[findings[0]],
            )
        ],
        findings=findings,
    )

    output = render_human(result)
    assert "Overall risk score: 62/100 (MEDIUM)" in output
    assert "Top reasons:" in output
    assert "Per-file summary:" in output
    assert "6." not in output
    assert "src/api.py: 22/100" in output


def test_render_json_has_stable_schema_keys() -> None:
    result = ScoreResult(
        overall_score=18,
        files=[
            FileScore(
                path="src/main.py",
                score=10,
                hunks=[HunkScore(header="@@ -1 +1 @@", score=2, findings=[_finding("x", 2, "m")])],
                findings=[_finding("x", 2, "m")],
            )
        ],
        findings=[_finding("x", 2, "m"), _finding("y", 5, "n")],
    )

    payload = json.loads(
        render_json(result, input_source="stdin", base="abc123", head="def456")
    )
    assert set(payload.keys()) == {"overall_score", "files", "findings", "meta"}
    assert payload["overall_score"] == 18
    assert set(payload["meta"].keys()) == {
        "generated_at",
        "base",
        "head",
        "input_source",
        "version",
    }
    assert payload["meta"]["base"] == "abc123"
    assert payload["meta"]["head"] == "def456"
    assert payload["meta"]["input_source"] == "stdin"
    assert isinstance(payload["files"], list)
    assert isinstance(payload["findings"], list)

    first_file = payload["files"][0]
    assert set(first_file.keys()) == {"path", "score", "hunks", "findings"}
    first_hunk = first_file["hunks"][0]
    assert set(first_hunk.keys()) == {"header", "score", "findings"}

    first_finding = payload["findings"][0]
    assert set(first_finding.keys()) == {
        "rule_id",
        "points",
        "message",
        "evidence",
        "scope",
        "suggestion",
    }


def _finding(rule_id: str, points: int, message: str) -> Finding:
    return Finding(
        rule_id=rule_id,
        points=points,
        message=message,
        evidence=f"evidence:{rule_id}",
        scope="overall",
        suggestion=f"suggestion:{rule_id}",
    )
