"""CLI end-to-end tests for score command JSON and CI gating."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from diff_ai.cli import app
from tests.helpers_git import build_numbered_lines, commit_all, git, init_repo, write_file

runner = CliRunner()


def test_cli_score_json_from_stdin_has_schema_keys(tmp_path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "auth/service.py", "ALLOW=False\n")
    commit_all(repo, "baseline")
    write_file(repo, "auth/service.py", "ALLOW=True\n")
    diff_text = git(repo, "diff", "--no-color")

    result = runner.invoke(app, ["score", "--stdin", "--format", "json"], input=diff_text)
    assert result.exit_code == 0

    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"overall_score", "files", "findings", "meta"}
    assert isinstance(payload["overall_score"], int)
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

    fail_result = runner.invoke(
        app,
        ["score", "--stdin", "--format", "json", "--fail-above", "20"],
        input=diff_text,
    )
    assert fail_result.exit_code == 1

    ok_result = runner.invoke(
        app,
        ["score", "--stdin", "--format", "json", "--fail-above", "99"],
        input=diff_text,
    )
    assert ok_result.exit_code == 0
