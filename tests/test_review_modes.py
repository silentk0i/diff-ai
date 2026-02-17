"""Tests for review-mode diff scoping."""

from __future__ import annotations

import json

from tests.helpers_cli import invoke_cli
from tests.helpers_git import commit_all, init_repo, write_file


def test_ai_task_mode_supports_repos_without_commits(tmp_path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "src/new_repo.py", "VALUE = 1\n")

    first = invoke_cli(
        ["score", "--repo", str(repo), "--review-mode", "ai-task", "--format", "json"]
    )
    assert first.exit_code == 0
    first_payload = json.loads(first.stdout)
    assert first_payload["files"]
    assert first_payload["meta"]["review_mode"] == "ai-task"
    assert (repo / ".diff-ai-task-state.json").exists()

    second = invoke_cli(
        ["score", "--repo", str(repo), "--review-mode", "ai-task", "--format", "json"]
    )
    assert second.exit_code == 0
    second_payload = json.loads(second.stdout)
    assert second_payload["files"] == []


def test_ai_task_mode_includes_committed_changes_since_last_checkpoint(tmp_path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "src/app.py", "VALUE = 1\n")
    commit_all(repo, "baseline")

    baseline = invoke_cli(
        ["score", "--repo", str(repo), "--review-mode", "ai-task", "--format", "json"]
    )
    assert baseline.exit_code == 0

    write_file(repo, "src/app.py", "VALUE = 2\n")
    commit_all(repo, "update")

    after_commit = invoke_cli(
        ["score", "--repo", str(repo), "--review-mode", "ai-task", "--format", "json"]
    )
    assert after_commit.exit_code == 0
    payload = json.loads(after_commit.stdout)
    assert payload["files"]
    assert payload["meta"]["review_mode"] == "ai-task"
    assert payload["meta"]["base"] is not None
    assert payload["meta"]["head"] is not None


def test_ai_task_mode_rejects_base_head_flags(tmp_path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "src/app.py", "VALUE = 1\n")
    commit_all(repo, "baseline")

    result = invoke_cli(
        [
            "score",
            "--repo",
            str(repo),
            "--review-mode",
            "ai-task",
            "--base",
            "HEAD",
            "--head",
            "HEAD",
        ]
    )
    assert result.exit_code == 2
    assert "ai-task mode does not use --base/--head" in result.stderr
