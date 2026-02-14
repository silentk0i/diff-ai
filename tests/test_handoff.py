"""Unit tests for LLM handoff document generation."""

from __future__ import annotations

from diff_ai.diff_parser import parse_unified_diff
from diff_ai.handoff import PromptSpec, build_prompt_markdown
from diff_ai.rules.base import Finding
from diff_ai.scoring import FileScore, HunkScore, ScoreResult, score_diff_text


def test_prompt_generation_is_deterministic_for_fixed_inputs() -> None:
    diff_text = "\n".join(
        [
            "diff --git a/src/auth.py b/src/auth.py",
            "index 1111111..2222222 100644",
            "--- a/src/auth.py",
            "+++ b/src/auth.py",
            "@@ -1 +1,2 @@",
            "-ALLOW=False",
            "+ALLOW=True",
            "+TOKEN=supersecret123456",
        ]
    )
    files = parse_unified_diff(diff_text)
    result = ScoreResult(
        overall_score=58,
        files=[FileScore(path="src/auth.py", score=22, hunks=[HunkScore(header="@@ -1 +1,2 @@")])],
        findings=[
            Finding(
                rule_id="critical_paths",
                points=16,
                message="Security-sensitive code path modified.",
                evidence="Matched critical path category 'security' in src/auth.py.",
                scope="file:src/auth.py",
                suggestion="Validate authentication and authorization edge cases.",
            ),
            Finding(
                rule_id="dangerous_patterns",
                points=8,
                message="Shell execution path added.",
                evidence="src/auth.py: `os.system(cmd)`",
                scope="file:src/auth.py",
                suggestion="Use subprocess APIs with explicit args.",
            ),
        ],
    )
    spec = PromptSpec(
        target_score=30,
        style="thorough",
        persona="reviewer",
        include_diff="full",
        max_bytes=200000,
        redact_secrets=False,
    )

    prompt_a = build_prompt_markdown(result=result, files=files, spec=spec)
    prompt_b = build_prompt_markdown(result=result, files=files, spec=spec)
    assert prompt_a == prompt_b
    assert "## Summary" in prompt_a
    assert "## Findings" in prompt_a
    assert "## Diff" in prompt_a
    assert "## Instructions" in prompt_a
    assert "## Checklist" in prompt_a


def test_prompt_diff_truncation_is_stable_and_keeps_sections() -> None:
    old_lines = [f"old-{idx}" for idx in range(1, 180)]
    new_lines = [f"new-{idx}" for idx in range(1, 180)]
    diff_text = _build_replace_diff("src/big.py", old_lines, new_lines)
    files = parse_unified_diff(diff_text)
    result = score_diff_text(diff_text)
    spec = PromptSpec(
        target_score=30,
        style="paranoid",
        persona="security",
        include_diff="full",
        max_bytes=300,
    )

    prompt = build_prompt_markdown(result=result, files=files, spec=spec)
    assert "... [diff truncated to max-bytes] ..." in prompt
    assert "## Diff" in prompt
    assert "## Instructions" in prompt
    assert "## Checklist" in prompt


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
