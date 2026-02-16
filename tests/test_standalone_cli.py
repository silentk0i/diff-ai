"""Tests for dependency-light standalone CLI."""

from __future__ import annotations

import json
from pathlib import Path

from diff_ai import __version__
from diff_ai.standalone import main


def test_standalone_version_flag(capsys) -> None:
    exit_code = main(["--version"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.strip() == __version__


def test_standalone_score_json_from_diff_file(capsys) -> None:
    diff_path = Path("tests/fixtures/diffs/simple.diff")
    exit_code = main(["score", "--diff-file", str(diff_path), "--format", "json"])
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert set(payload.keys()) == {"overall_score", "files", "findings", "meta"}
