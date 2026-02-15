"""Tests for plugin scheduling and execution metadata."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from diff_ai.cli import app
from diff_ai.plugins import schedule_plugin_rules

runner = CliRunner()


def test_schedule_plugins_respects_mode_and_pack_filters() -> None:
    _, runs = schedule_plugin_rules(
        include_builtin=True,
        active_packs={"logic", "integration", "test_adequacy", "quality", "profile"},
        mode="fast",
        budget_seconds=15,
        enabled_plugin_ids=None,
        disabled_plugin_ids=None,
    )
    runs_by_id = {run.plugin_id: run for run in runs}
    assert runs_by_id["deferred_work_markers"].status == "scheduled"
    assert runs_by_id["cross_layer_touchpoints"].reason == "mode-incompatible"
    assert runs_by_id["network_exposure_probe"].reason == "pack-inactive"


def test_schedule_plugins_respects_total_budget() -> None:
    _, runs = schedule_plugin_rules(
        include_builtin=True,
        active_packs={"logic", "integration", "test_adequacy", "quality", "profile"},
        mode="standard",
        budget_seconds=1,
        enabled_plugin_ids=None,
        disabled_plugin_ids=None,
    )
    runs_by_id = {run.plugin_id: run for run in runs}
    assert runs_by_id["deferred_work_markers"].status == "scheduled"
    assert runs_by_id["cross_layer_touchpoints"].reason == "budget-exceeded"


def test_cli_score_json_includes_plugin_execution_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".diff-ai.toml").write_text(
        "\n".join(
            [
                "format = \"json\"",
                "",
                "[objective]",
                'name = "feature_oneshot"',
                'mode = "standard"',
                "budget_seconds = 15",
                "",
                "[plugins]",
                'enable = ["cross_layer_touchpoints"]',
                "",
                "[rules]",
                'enable = ["magnitude"]',
            ]
        ),
        encoding="utf-8",
    )
    diff_text = "\n".join(
        [
            "diff --git a/src/api/routes.py b/src/api/routes.py",
            "index 1111111..2222222 100644",
            "--- a/src/api/routes.py",
            "+++ b/src/api/routes.py",
            "@@ -1 +1,2 @@",
            "-def route():",
            "+def route(user_id: str):",
            "+    return user_id",
        ]
    )

    result = runner.invoke(
        app,
        ["score", "--repo", str(repo), "--stdin", "--format", "json"],
        input=diff_text,
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "plugins" in payload["meta"]
    plugin_runs = payload["meta"]["plugins"]
    run = next(item for item in plugin_runs if item["plugin_id"] == "cross_layer_touchpoints")
    assert run["status"] == "ran"
    assert run["findings"] >= 1
    assert any(
        item["rule_id"] == "plugin_cross_layer_touchpoints" for item in payload["findings"]
    )


def test_cli_plugins_command_json_shows_dry_run_schedule(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".diff-ai.toml").write_text(
        "\n".join(
            [
                "[objective]",
                'name = "feature_oneshot"',
                'mode = "standard"',
                "budget_seconds = 2",
                "",
                "[plugins]",
                'enable = ["cross_layer_touchpoints"]',
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["plugins", "--repo", str(repo), "--format", "json", "--dry-run"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["meta"]["dry_run"] is True
    assert payload["meta"]["objective_mode"] == "standard"
    plugin = next(
        item for item in payload["plugins"] if item["plugin_id"] == "cross_layer_touchpoints"
    )
    assert plugin["schedule"] is not None
    assert plugin["schedule"]["status"] == "skipped"
    assert plugin["schedule"]["reason"] == "budget-exceeded"


def test_cli_plugins_command_json_no_dry_run_omits_schedule(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    result = runner.invoke(
        app,
        ["plugins", "--repo", str(repo), "--format", "json", "--no-dry-run"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["meta"]["dry_run"] is False
    assert all(item["schedule"] is None for item in payload["plugins"])
