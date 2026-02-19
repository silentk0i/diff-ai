"""Integration tests using synthetic git repositories."""

from __future__ import annotations

from diff_ai.diff_parser import parse_unified_diff
from diff_ai.rules import build_rules
from diff_ai.scoring import score_diff_text
from tests.helpers_git import build_numbered_lines, commit_all, git, init_repo, write_file


def test_golden_magnitude_from_real_git_diff(tmp_path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "src/core.py", build_numbered_lines("old", 220))
    write_file(repo, "tests/test_core.py", "def test_ok():\n    assert True\n")
    commit_all(repo, "baseline")

    write_file(repo, "src/core.py", build_numbered_lines("new", 220))
    diff_text = git(repo, "diff", "--no-color")
    result = score_diff_text(diff_text)

    rule_ids = {finding.rule_id for finding in result.findings}
    assert "magnitude" in rule_ids
    assert result.overall_score >= 40
    assert result.overall_score <= 100


def test_golden_critical_paths_from_real_git_diff(tmp_path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "auth/service.py", "ALLOW=False\n")
    write_file(repo, ".github/workflows/ci.yml", "name: ci\n")
    write_file(repo, "terraform/main.tf", 'resource "null_resource" "x" {}\n')
    write_file(repo, "db/migrations/001_init.sql", "create table t(id int);\n")
    commit_all(repo, "baseline")

    write_file(repo, "auth/service.py", "ALLOW=True\n")
    write_file(repo, ".github/workflows/ci.yml", "name: ci-updated\n")
    write_file(repo, "terraform/main.tf", 'resource "null_resource" "y" {}\n')
    write_file(repo, "db/migrations/001_init.sql", "create table t(id bigint);\n")
    diff_text = git(repo, "diff", "--no-color")
    result = score_diff_text(diff_text, rules=build_rules(objective_name="security_strict"))

    critical_scopes = {
        finding.scope for finding in result.findings if finding.rule_id == "critical_paths"
    }
    assert "file:auth/service.py" in critical_scopes
    assert "file:.github/workflows/ci.yml" in critical_scopes
    assert "file:terraform/main.tf" in critical_scopes
    assert "file:db/migrations/001_init.sql" in critical_scopes
    assert result.overall_score >= 40
    assert result.overall_score <= 100


def test_golden_test_signals_when_src_changes_without_tests(tmp_path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "src/service.py", "VALUE = 1\n")
    write_file(repo, "tests/test_service.py", "def test_service():\n    assert 1 == 1\n")
    commit_all(repo, "baseline")

    write_file(repo, "src/service.py", "VALUE = 2\n")
    diff_text = git(repo, "diff", "--no-color")
    result = score_diff_text(diff_text)

    findings = [item for item in result.findings if item.rule_id == "test_signals"]
    assert any(item.points == 24 and item.scope == "overall" for item in findings)
    assert 40 <= result.overall_score <= 70


def test_test_signals_trigger_when_tests_deleted(tmp_path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "src/service.py", "VALUE = 1\n")
    write_file(repo, "tests/test_service.py", "def test_service():\n    assert 1 == 1\n")
    commit_all(repo, "baseline")

    (repo / "tests/test_service.py").unlink()
    diff_text = git(repo, "diff", "--no-color")
    result = score_diff_text(diff_text)

    findings = [item for item in result.findings if item.rule_id == "test_signals"]
    assert any(
        item.scope == "file:tests/test_service.py" and item.points == 16 for item in findings
    )


def test_rename_plus_edit_diff_is_parsed_best_effort(tmp_path) -> None:
    repo = init_repo(tmp_path)
    write_file(repo, "src/old_name.py", "a = 1\nb = 2\n")
    commit_all(repo, "baseline")

    git(repo, "mv", "src/old_name.py", "src/new_name.py")
    write_file(repo, "src/new_name.py", "a = 1\nb = 20\nc = 3\n")
    diff_text = git(repo, "diff", "--no-color", "-M20%", "HEAD")

    parsed = parse_unified_diff(diff_text)
    assert len(parsed) == 1
    file_diff = parsed[0]
    assert file_diff.old_path == "src/old_name.py"
    assert file_diff.new_path == "src/new_name.py"
    assert file_diff.path == "src/new_name.py"
    assert len(file_diff.hunks) >= 1
    assert any(line.kind == "add" for hunk in file_diff.hunks for line in hunk.lines)
