"""CLI tests for `diff-ai bundle` and `diff-ai prompt`."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from typer.testing import CliRunner

from diff_ai.cli import app
from tests.helpers_git import commit_all, git, init_repo, write_file

runner = CliRunner()


def test_prompt_command_outputs_markdown_sections(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "src/auth.py", "ALLOW=False\n")
    commit_all(repo, "baseline")
    write_file(repo, "src/auth.py", "ALLOW=True\nTOKEN=supersecret123456\n")
    diff_text = git(repo, "diff", "--no-color")

    result = runner.invoke(
        app,
        ["prompt", "--repo", str(repo), "--stdin", "--redact-secrets"],
        input=diff_text,
    )
    assert result.exit_code == 0
    assert "# Diff AI LLM Handoff" in result.stdout
    assert "## Summary" in result.stdout
    assert "## Findings" in result.stdout
    assert "## Diff" in result.stdout
    assert "## Instructions" in result.stdout
    assert "## Checklist" in result.stdout
    assert "<redacted>" in result.stdout
    assert "supersecret123456" not in result.stdout


def test_bundle_command_creates_expected_files(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "src/auth.py", "ALLOW=False\nTOKEN=oldsecret\n")
    commit_all(repo, "baseline")
    write_file(repo, "src/auth.py", "ALLOW=True\nTOKEN=supersecret123456\n")
    diff_text = git(repo, "diff", "--no-color")

    out_dir = tmp_path / "bundle-out"
    result = runner.invoke(
        app,
        [
            "bundle",
            "--repo",
            str(repo),
            "--stdin",
            "--out",
            str(out_dir),
            "--include-snippets",
            "minimal",
            "--redact-secrets",
        ],
        input=diff_text,
    )
    assert result.exit_code == 0

    findings_json = out_dir / "findings.json"
    findings_md = out_dir / "findings.md"
    patch_diff = out_dir / "patch.diff"
    prompt_md = out_dir / "prompt.md"
    assert findings_json.exists()
    assert findings_md.exists()
    assert patch_diff.exists()
    assert prompt_md.exists()

    findings_payload = json.loads(findings_json.read_text(encoding="utf-8"))
    assert {"overall_score", "files", "findings", "meta"} <= set(findings_payload.keys())

    prompt_text = prompt_md.read_text(encoding="utf-8")
    assert prompt_text.startswith("# Diff AI LLM Handoff")
    assert "## Snippets" in prompt_text

    findings_text = findings_md.read_text(encoding="utf-8")
    assert findings_text.startswith("# Diff AI Findings")

    patch_text = patch_diff.read_text(encoding="utf-8")
    assert "diff --git" in patch_text
    assert "<redacted>" in patch_text
    assert "supersecret123456" not in patch_text


def test_bundle_command_writes_zip_when_requested(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "src/app.py", "VALUE=1\n")
    commit_all(repo, "baseline")
    write_file(repo, "src/app.py", "VALUE=2\n")
    diff_text = git(repo, "diff", "--no-color")

    out_zip = tmp_path / "handoff.zip"
    result = runner.invoke(
        app,
        ["bundle", "--repo", str(repo), "--stdin", "--out", str(out_zip), "--zip"],
        input=diff_text,
    )
    assert result.exit_code == 0
    assert out_zip.exists()

    with zipfile.ZipFile(out_zip) as archive:
        names = set(archive.namelist())
    assert {"findings.json", "findings.md", "patch.diff", "prompt.md"} <= names
