"""Standalone CLI smoke tests."""

from tests.helpers_cli import invoke_cli


def test_root_help_works() -> None:
    result = invoke_cli(["--help"])
    assert result.exit_code == 0
    assert "Analyze git diffs" in result.stdout
    assert "score" in result.stdout
    assert "config-init" in result.stdout
    assert "config-validate" in result.stdout


def test_score_help_works() -> None:
    result = invoke_cli(["score", "--help"])
    assert result.exit_code == 0
    assert "--diff-file" in result.stdout
    assert "--stdin" in result.stdout
