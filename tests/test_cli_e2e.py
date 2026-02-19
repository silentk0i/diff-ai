"""CLI end-to-end tests for score command JSON and CI gating."""

from __future__ import annotations

import json

from tests.helpers_cli import invoke_cli
from tests.helpers_git import build_numbered_lines, commit_all, git, init_repo, write_file


def test_cli_score_json_from_stdin_has_schema_keys(tmp_path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "auth/service.py", "ALLOW=False\n")
    commit_all(repo, "baseline")
    write_file(repo, "auth/service.py", "ALLOW=True\n")
    diff_text = git(repo, "diff", "--no-color")

    result = invoke_cli(["score", "--stdin", "--format", "json"], input_text=diff_text)
    assert result.exit_code == 0

    payload = json.loads(result.stdout)
    assert {
        "overall_score",
        "final_score_0_100",
        "raw_points_total",
        "raw_points_by_category",
        "capped_points_by_category",
        "transformed_score",
        "reasons_topN",
        "files",
        "findings",
        "meta",
    } <= set(payload.keys())
    assert isinstance(payload["overall_score"], int)
    assert isinstance(payload["final_score_0_100"], int)
    assert isinstance(payload["raw_points_total"], int)
    assert isinstance(payload["raw_points_by_category"], dict)
    assert isinstance(payload["capped_points_by_category"], dict)
    assert isinstance(payload["transformed_score"], float)
    assert isinstance(payload["reasons_topN"], list)
    assert isinstance(payload["files"], list)
    assert isinstance(payload["findings"], list)
    assert isinstance(payload["meta"], dict)

    meta = payload["meta"]
    assert {"generated_at", "base", "head", "input_source", "version"} <= set(meta.keys())

    if payload["findings"]:
        finding = payload["findings"][0]
        assert {
            "rule_id",
            "points",
            "message",
            "evidence",
            "scope",
            "suggestion",
        } <= set(finding.keys())


def test_cli_fail_above_sets_exit_code(tmp_path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "src/core.py", build_numbered_lines("old", 220))
    commit_all(repo, "baseline")
    write_file(repo, "src/core.py", build_numbered_lines("new", 220))
    diff_text = git(repo, "diff", "--no-color")

    fail_result = invoke_cli(
        ["score", "--stdin", "--format", "json", "--fail-above", "20"],
        input_text=diff_text,
    )
    assert fail_result.exit_code == 1

    ok_result = invoke_cli(
        ["score", "--stdin", "--format", "json", "--fail-above", "99"],
        input_text=diff_text,
    )
    assert ok_result.exit_code == 0
