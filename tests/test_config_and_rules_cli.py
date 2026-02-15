"""Step 6 tests for config loading and rules/config CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from diff_ai.cli import app
from diff_ai.config import load_app_config

runner = CliRunner()


def test_load_app_config_prefers_dot_file_over_pyproject(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "\n".join(
            [
                "[tool.diff_ai]",
                'format = "human"',
                "fail_above = 80",
            ]
        ),
        encoding="utf-8",
    )
    (repo / ".diff-ai.toml").write_text(
        "\n".join(
            [
                'format = "json"',
                "fail_above = 25",
                'include = ["src/**"]',
                "",
                "[rules]",
                'enable = ["magnitude"]',
                'disable = ["docs_only"]',
            ]
        ),
        encoding="utf-8",
    )

    config = load_app_config(repo)
    assert config.format == "json"
    assert config.fail_above == 25
    assert config.include == ["src/**"]
    assert config.rule_enable == ["magnitude"]
    assert config.rule_disable == ["docs_only"]
    assert config.objective.name == "feature_oneshot"
    assert config.objective.mode == "standard"
    assert config.source == str(repo / ".diff-ai.toml")


def test_load_app_config_reads_pyproject_hyphenated_key(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "\n".join(
            [
                '[tool."diff-ai"]',
                'format = "json"',
                "",
                '[tool."diff-ai".rules]',
                'enable = ["critical_paths"]',
            ]
        ),
        encoding="utf-8",
    )

    config = load_app_config(repo)
    assert config.format == "json"
    assert config.rule_enable == ["critical_paths"]
    assert config.source == str(repo / "pyproject.toml")


def test_rules_command_json_lists_enabled_state_from_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".diff-ai.toml").write_text(
        "\n".join(
            [
                "[rules]",
                'enable = ["magnitude", "critical_paths", "docs_only"]',
                'disable = ["docs_only"]',
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["rules", "--repo", str(repo), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    rules_by_id = {item["rule_id"]: item for item in payload["rules"]}

    assert rules_by_id["magnitude"]["enabled"] is True
    assert rules_by_id["critical_paths"]["enabled"] is True
    assert rules_by_id["docs_only"]["enabled"] is False
    assert payload["meta"]["config_source"] == str(repo / ".diff-ai.toml")


def test_rules_command_defaults_to_feature_oneshot_packs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    result = runner.invoke(app, ["rules", "--repo", str(repo), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    rules_by_id = {item["rule_id"]: item for item in payload["rules"]}
    assert rules_by_id["critical_paths"]["enabled"] is False
    assert rules_by_id["dangerous_patterns"]["enabled"] is False
    assert rules_by_id["test_signals"]["enabled"] is True


def test_rules_command_objective_can_enable_security_pack(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".diff-ai.toml").write_text(
        "\n".join(
            [
                "[objective]",
                'name = "security_strict"',
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["rules", "--repo", str(repo), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    rules_by_id = {item["rule_id"]: item for item in payload["rules"]}
    assert rules_by_id["critical_paths"]["enabled"] is True
    assert rules_by_id["dangerous_patterns"]["enabled"] is True


def test_config_command_json_shows_resolved_values(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".diff-ai.toml").write_text(
        "\n".join(
            [
                'format = "json"',
                "fail_above = 42",
                'include = ["src/**"]',
                'exclude = ["docs/**"]',
                "",
                "[rules]",
                'enable = ["magnitude", "critical_paths"]',
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["config", "--repo", str(repo), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["format"] == "json"
    assert payload["fail_above"] == 42
    assert payload["include"] == ["src/**"]
    assert payload["exclude"] == ["docs/**"]
    assert payload["rules"]["enable"] == ["magnitude", "critical_paths"]
    assert payload["active_rule_ids"] == ["magnitude", "critical_paths"]
    assert payload["objective"]["name"] == "feature_oneshot"
    assert payload["objective"]["mode"] == "standard"
    assert payload["objective"]["budget_seconds"] == 15
    assert payload["source"] == str(repo / ".diff-ai.toml")


def test_score_uses_config_defaults_for_format_fail_and_rule_selection(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".diff-ai.toml").write_text(
        "\n".join(
            [
                'format = "json"',
                "fail_above = 5",
                "",
                "[rules]",
                'enable = ["critical_paths"]',
            ]
        ),
        encoding="utf-8",
    )
    diff_text = "\n".join(
        [
            "diff --git a/auth/service.py b/auth/service.py",
            "index 1111111..2222222 100644",
            "--- a/auth/service.py",
            "+++ b/auth/service.py",
            "@@ -1 +1 @@",
            "-ALLOW=False",
            "+ALLOW=True",
        ]
    )

    result = runner.invoke(app, ["score", "--repo", str(repo), "--stdin"], input=diff_text)
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["overall_score"] >= 10
    assert {item["rule_id"] for item in payload["findings"]} == {"critical_paths"}


def test_prompt_uses_llm_defaults_from_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".diff-ai.toml").write_text(
        "\n".join(
            [
                "[llm]",
                'style = "paranoid"',
                'persona = "security"',
                "target_score = 12",
                'include_diff = "top-hunks"',
                "max_bytes = 1200",
                "redact_secrets = true",
                'rubric = ["do not change api contract"]',
                "",
                "[rules]",
                'enable = ["critical_paths"]',
            ]
        ),
        encoding="utf-8",
    )
    diff_text = "\n".join(
        [
            "diff --git a/auth/service.py b/auth/service.py",
            "index 1111111..2222222 100644",
            "--- a/auth/service.py",
            "+++ b/auth/service.py",
            "@@ -1 +1,2 @@",
            "-ALLOW=False",
            "+ALLOW=True",
            "+TOKEN=supersecret123456",
        ]
    )

    result = runner.invoke(
        app,
        ["prompt", "--repo", str(repo), "--stdin", "--format", "json"],
        input=diff_text,
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["target_score"] == 12
    assert payload["meta"]["style"] == "paranoid"
    assert payload["meta"]["persona"] == "security"
    assert payload["meta"]["include_diff"] == "top-hunks"
    assert "<redacted>" in payload["prompt_markdown"]
    assert "supersecret123456" not in payload["prompt_markdown"]


def test_load_app_config_from_explicit_config_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = repo / "custom.toml"
    config_path.write_text(
        "\n".join(
            [
                'format = "json"',
                "",
                "[rules]",
                'enable = ["critical_paths"]',
            ]
        ),
        encoding="utf-8",
    )

    config = load_app_config(repo, config_path=Path("custom.toml"))
    assert config.format == "json"
    assert config.rule_enable == ["critical_paths"]
    assert config.source == str(config_path)


def test_profile_signals_from_config_influence_score(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = repo / "profile.toml"
    config_path.write_text(
        "\n".join(
            [
                'format = "json"',
                "",
                "[rules]",
                'enable = ["profile_signals"]',
                "",
                "[profile.paths]",
                'critical = [{ glob = "src/payments/**", points = 20, reason = "payments" }]',
            ]
        ),
        encoding="utf-8",
    )
    diff_text = "\n".join(
        [
            "diff --git a/src/payments/charge.py b/src/payments/charge.py",
            "index 1111111..2222222 100644",
            "--- a/src/payments/charge.py",
            "+++ b/src/payments/charge.py",
            "@@ -1 +1 @@",
            "-x = 1",
            "+x = 2",
        ]
    )
    result = runner.invoke(
        app,
        [
            "score",
            "--repo",
            str(repo),
            "--config",
            str(config_path),
            "--stdin",
        ],
        input=diff_text,
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["overall_score"] >= 20
    assert {item["rule_id"] for item in payload["findings"]} == {"profile_signals"}


def test_objective_category_weight_scales_points(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".diff-ai.toml").write_text(
        "\n".join(
            [
                "[objective.weights]",
                "test_adequacy = 2.0",
                "",
                "[rules]",
                'enable = ["test_signals"]',
            ]
        ),
        encoding="utf-8",
    )
    diff_text = "\n".join(
        [
            "diff --git a/src/feature.py b/src/feature.py",
            "index 1111111..2222222 100644",
            "--- a/src/feature.py",
            "+++ b/src/feature.py",
            "@@ -1 +1 @@",
            "-x = 1",
            "+x = 2",
        ]
    )

    result = runner.invoke(
        app,
        ["score", "--repo", str(repo), "--stdin", "--format", "json"],
        input=diff_text,
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    findings = [item for item in payload["findings"] if item["rule_id"] == "test_signals"]
    assert findings
    assert findings[0]["points"] == 36


def test_config_init_and_validate_commands(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = repo / ".diff-ai.toml"

    init_result = runner.invoke(
        app,
        ["config-init", "--out", str(config_path)],
    )
    assert init_result.exit_code == 0
    assert config_path.exists()
    content = config_path.read_text(encoding="utf-8")
    assert "[objective]" in content
    assert "[objective.packs]" in content
    assert "[objective.weights]" in content
    assert "[profile.paths]" in content
    assert "[profile.patterns]" in content

    validate_result = runner.invoke(
        app,
        ["config-validate", "--repo", str(repo), "--config", str(config_path), "--format", "json"],
    )
    assert validate_result.exit_code == 0
    payload = json.loads(validate_result.stdout)
    assert payload["ok"] is True
    assert "profile_signals" in payload["active_rule_ids"]
