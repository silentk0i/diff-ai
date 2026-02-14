"""CLI smoke tests for the Step 1 scaffold."""

from typer.testing import CliRunner

from diff_ai.cli import app

runner = CliRunner()


def test_root_help_works() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Analyze git diffs" in result.stdout
    assert "score" in result.stdout
    assert "config-init" in result.stdout
    assert "config-validate" in result.stdout


def test_score_help_works() -> None:
    result = runner.invoke(app, ["score", "--help"])
    assert result.exit_code == 0
    assert "--diff-file" in result.stdout
    assert "--stdin" in result.stdout
