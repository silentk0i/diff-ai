"""Dependency-light CLI for skill/runtime usage without package install."""

from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from diff_ai import __version__
from diff_ai.config import AppConfig, default_config_template, load_app_config
from diff_ai.diff_parser import FileDiff, parse_unified_diff
from diff_ai.git import GitError, get_diff_between, get_working_tree_diff
from diff_ai.handoff import (
    PromptSpec,
    build_findings_markdown,
    build_prompt_markdown,
    build_snippets_markdown,
    redact_payload_strings,
    redact_text,
    select_diff_for_handoff,
    truncate_text_to_bytes,
)
from diff_ai.plugins import PluginRun, list_plugin_info, schedule_plugin_rules
from diff_ai.rules import build_rules, list_rule_info, resolve_active_packs
from diff_ai.rules.base import Finding, Rule
from diff_ai.scoring import FileScore, ScoreResult, score_files


class CliUsageError(Exception):
    """Invalid CLI usage."""


class CliRuntimeError(Exception):
    """Runtime failure during command execution."""


@dataclass(slots=True)
class ScoreContext:
    """Resolved score inputs and outputs for shared command flows."""

    result: ScoreResult
    files: list[FileDiff]
    diff_text: str
    input_source: str
    plugin_runs: list[PluginRun]


def main(argv: list[str] | None = None) -> int:
    """Program entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    if args.command is None:
        parser.print_help()
        return 0

    try:
        return _dispatch(args)
    except CliUsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except CliRuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "score":
        return _cmd_score(args)
    if args.command == "prompt":
        return _cmd_prompt(args)
    if args.command == "bundle":
        return _cmd_bundle(args)
    if args.command == "rules":
        return _cmd_rules(args)
    if args.command == "plugins":
        return _cmd_plugins(args)
    if args.command == "config":
        return _cmd_config(args)
    if args.command == "config-init":
        return _cmd_config_init(args)
    if args.command == "config-validate":
        return _cmd_config_validate(args)
    if args.command == "explain":
        print("Not implemented yet. Step 1 scaffold complete.")
        return 0
    raise CliUsageError(f"unknown command: {args.command}")


def _cmd_score(args: argparse.Namespace) -> int:
    app_config = _load_config_or_raise(args.repo, args.config_file)
    output_format = (args.format or app_config.format).lower()
    _validate_choice(output_format, {"human", "json"}, "--format")
    _validate_diff_selection(args)

    score_ctx = _prepare_score_context(
        diff_file=args.diff_file,
        stdin=args.stdin,
        repo=args.repo,
        base=args.base,
        head=args.head,
        include=args.include,
        exclude=args.exclude,
        app_config=app_config,
    )
    fail_threshold = args.fail_above if args.fail_above is not None else app_config.fail_above

    if output_format == "json":
        print(
            json.dumps(
                _build_json_payload(
                    score_ctx.result,
                    input_source=score_ctx.input_source,
                    base=args.base,
                    head=args.head,
                    plugin_runs=score_ctx.plugin_runs,
                ),
                sort_keys=True,
            )
        )
    else:
        print(_render_human(score_ctx.result))

    if fail_threshold is not None and score_ctx.result.overall_score > fail_threshold:
        return 1
    return 0


def _cmd_prompt(args: argparse.Namespace) -> int:
    app_config = _load_config_or_raise(args.repo, args.config_file)
    llm_defaults = app_config.llm
    _validate_diff_selection(args)

    resolved_style = _choice_or_default(
        value=args.style,
        default=llm_defaults.style,
        allowed={"concise", "thorough", "paranoid"},
        field_name="--style",
    )
    resolved_persona = _choice_or_default(
        value=args.persona,
        default=llm_defaults.persona,
        allowed={"reviewer", "security", "sre", "maintainer"},
        field_name="--persona",
    )
    resolved_include_diff = _choice_or_default(
        value=args.include_diff,
        default=llm_defaults.include_diff,
        allowed={"full", "risky-only", "top-hunks"},
        field_name="--include-diff",
    )
    resolved_target_score = (
        args.target_score if args.target_score is not None else llm_defaults.target_score
    )
    resolved_max_bytes = args.max_bytes if args.max_bytes is not None else llm_defaults.max_bytes
    resolved_redact = (
        args.redact_secrets if args.redact_secrets is not None else llm_defaults.redact_secrets
    )

    score_ctx = _prepare_score_context(
        diff_file=args.diff_file,
        stdin=args.stdin,
        repo=args.repo,
        base=args.base,
        head=args.head,
        include=args.include,
        exclude=args.exclude,
        app_config=app_config,
    )

    prompt_md = build_prompt_markdown(
        result=score_ctx.result,
        files=score_ctx.files,
        spec=PromptSpec(
            target_score=resolved_target_score,
            style=resolved_style,
            persona=resolved_persona,
            include_diff=resolved_include_diff,
            max_bytes=resolved_max_bytes,
            redact_secrets=resolved_redact,
            rubric=list(llm_defaults.rubric),
        ),
    )
    if resolved_redact:
        prompt_md = redact_text(prompt_md)

    if args.format == "markdown":
        print(prompt_md)
        return 0

    payload = {
        "prompt_markdown": prompt_md,
        "overall_score": score_ctx.result.overall_score,
        "target_score": resolved_target_score,
        "meta": {
            "style": resolved_style,
            "persona": resolved_persona,
            "include_diff": resolved_include_diff,
            "max_bytes": resolved_max_bytes,
            "redact_secrets": resolved_redact,
            "input_source": score_ctx.input_source,
            "base": args.base,
            "head": args.head,
        },
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


def _cmd_bundle(args: argparse.Namespace) -> int:
    app_config = _load_config_or_raise(args.repo, args.config_file)
    llm_defaults = app_config.llm
    _validate_diff_selection(args)

    resolved_style = _choice_or_default(
        value=args.style,
        default=llm_defaults.style,
        allowed={"concise", "thorough", "paranoid"},
        field_name="--style",
    )
    resolved_persona = _choice_or_default(
        value=args.persona,
        default=llm_defaults.persona,
        allowed={"reviewer", "security", "sre", "maintainer"},
        field_name="--persona",
    )
    resolved_include_diff = _choice_or_default(
        value=args.include_diff,
        default=llm_defaults.include_diff,
        allowed={"full", "risky-only", "top-hunks"},
        field_name="--include-diff",
    )
    resolved_include_snippets = _choice_or_default(
        value=args.include_snippets,
        default=llm_defaults.include_snippets,
        allowed={"none", "minimal", "risky-only"},
        field_name="--include-snippets",
    )
    resolved_target_score = (
        args.target_score if args.target_score is not None else llm_defaults.target_score
    )
    resolved_max_bytes = args.max_bytes if args.max_bytes is not None else llm_defaults.max_bytes
    resolved_redact = (
        args.redact_secrets if args.redact_secrets is not None else llm_defaults.redact_secrets
    )

    score_ctx = _prepare_score_context(
        diff_file=args.diff_file,
        stdin=args.stdin,
        repo=args.repo,
        base=args.base,
        head=args.head,
        include=args.include,
        exclude=args.exclude,
        app_config=app_config,
    )

    selected_diff = select_diff_for_handoff(
        files=score_ctx.files,
        result=score_ctx.result,
        include_diff=resolved_include_diff,
    )
    selected_diff, _ = truncate_text_to_bytes(
        selected_diff,
        max_bytes=resolved_max_bytes,
        marker="\n... [patch truncated to max-bytes] ...\n",
    )
    snippets_markdown = build_snippets_markdown(
        repo=args.repo,
        revision=args.head or "HEAD",
        files=score_ctx.files,
        result=score_ctx.result,
        include_snippets=resolved_include_snippets,
        max_bytes=resolved_max_bytes,
    )

    prompt_md = build_prompt_markdown(
        result=score_ctx.result,
        files=score_ctx.files,
        spec=PromptSpec(
            target_score=resolved_target_score,
            style=resolved_style,
            persona=resolved_persona,
            include_diff=resolved_include_diff,
            include_snippets=resolved_include_snippets,
            max_bytes=resolved_max_bytes,
            redact_secrets=resolved_redact,
            rubric=list(llm_defaults.rubric),
        ),
        snippets_markdown=snippets_markdown if resolved_include_snippets != "none" else None,
    )
    findings_md = build_findings_markdown(score_ctx.result)
    findings_payload = _build_json_payload(
        score_ctx.result,
        input_source=score_ctx.input_source,
        base=args.base,
        head=args.head,
        plugin_runs=score_ctx.plugin_runs,
    )

    if resolved_redact:
        prompt_md = redact_text(prompt_md)
        findings_md = redact_text(findings_md)
        selected_diff = redact_text(selected_diff)
        findings_payload = redact_payload_strings(findings_payload)

    bundle_dir, archive_path = _prepare_bundle_destination(args.out, args.zip)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    findings_json_path = bundle_dir / "findings.json"
    findings_md_path = bundle_dir / "findings.md"
    patch_path = bundle_dir / "patch.diff"
    prompt_path = bundle_dir / "prompt.md"

    findings_json_path.write_text(json.dumps(findings_payload, sort_keys=True), encoding="utf-8")
    findings_md_path.write_text(findings_md, encoding="utf-8")
    patch_content = selected_diff if selected_diff.endswith("\n") else f"{selected_diff}\n"
    patch_path.write_text(patch_content, encoding="utf-8")
    prompt_path.write_text(prompt_md, encoding="utf-8")

    output_path = str(bundle_dir)
    if args.zip and archive_path is not None:
        with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item in ("findings.json", "findings.md", "patch.diff", "prompt.md"):
                zf.write(bundle_dir / item, arcname=item)
        shutil.rmtree(bundle_dir)
        output_path = str(archive_path)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "output": output_path,
                    "overall_score": score_ctx.result.overall_score,
                    "target_score": resolved_target_score,
                },
                sort_keys=True,
            )
        )
    else:
        print(f"Bundle written to: {output_path}")
    return 0


def _cmd_rules(args: argparse.Namespace) -> int:
    output_format = (args.format or "human").lower()
    _validate_choice(output_format, {"human", "json"}, "--format")

    app_config = _load_config_or_raise(args.repo, args.config_file)
    active_rules = _build_configured_rules_or_raise(app_config)
    active_ids = {rule.rule_id for rule in active_rules}
    rule_info = list_rule_info(
        objective_name=app_config.objective.name,
        enabled_packs=app_config.objective.enable_packs,
        disabled_packs=app_config.objective.disable_packs,
    )

    if output_format == "json":
        payload = {
            "rules": [
                {
                    "rule_id": item.rule_id,
                    "name": item.name,
                    "description": item.description,
                    "category": item.category,
                    "packs": list(item.packs),
                    "default_enabled": item.default_enabled,
                    "enabled": item.rule_id in active_ids,
                }
                for item in rule_info
            ],
            "meta": {"config_source": app_config.source},
        }
        print(json.dumps(payload, sort_keys=True))
        return 0

    lines = ["Available rules:"]
    for item in rule_info:
        status = "enabled" if item.rule_id in active_ids else "disabled"
        lines.append(
            f"- {item.rule_id} [{status}] category={item.category} packs={list(item.packs)} "
            f"- {item.description}"
        )
    print("\n".join(lines))
    return 0


def _cmd_plugins(args: argparse.Namespace) -> int:
    output_format = (args.format or "human").lower()
    _validate_choice(output_format, {"human", "json"}, "--format")

    app_config = _load_config_or_raise(args.repo, args.config_file)
    plugin_info = list_plugin_info(include_builtin=app_config.plugins.include_builtin)

    active_packs: list[str] | None = None
    schedule_runs: list[PluginRun] = []
    if args.dry_run:
        resolved_active_packs = _resolve_active_packs_or_raise(app_config)
        _, schedule_runs = _schedule_plugins_or_raise(
            app_config,
            active_packs=resolved_active_packs,
        )
        active_packs = sorted(resolved_active_packs)

    runs_by_id = {run.plugin_id: run for run in schedule_runs}
    if output_format == "json":
        payload = {
            "plugins": [
                {
                    "plugin_id": item.plugin_id,
                    "rule_id": item.rule_id,
                    "description": item.description,
                    "category": item.category,
                    "packs": list(item.packs),
                    "estimated_cost_seconds": item.estimated_cost_seconds,
                    "modes": list(item.modes),
                    "priority": item.priority,
                    "schedule": runs_by_id[item.plugin_id].to_dict()
                    if item.plugin_id in runs_by_id
                    else None,
                }
                for item in plugin_info
            ],
            "meta": {
                "config_source": app_config.source,
                "dry_run": args.dry_run,
                "objective_mode": app_config.objective.mode,
                "objective_budget_seconds": app_config.objective.budget_seconds,
                "active_packs": active_packs,
            },
        }
        print(json.dumps(payload, sort_keys=True))
        return 0

    lines = ["Available plugins:"]
    if not plugin_info:
        lines.append("- none")
    for item in plugin_info:
        run = runs_by_id.get(item.plugin_id)
        schedule_text = f"{run.status} ({run.reason})" if run is not None else "not-previewed"
        lines.append(
            f"- {item.plugin_id} rule={item.rule_id} category={item.category} "
            f"packs={list(item.packs)} cost={item.estimated_cost_seconds:.1f}s "
            f"modes={list(item.modes)} priority={item.priority} schedule={schedule_text}"
        )

    if args.dry_run and active_packs is not None:
        lines.append(f"active_packs={active_packs}")
        lines.append(f"objective_mode={app_config.objective.mode}")
        lines.append(f"objective_budget_seconds={app_config.objective.budget_seconds}")
    print("\n".join(lines))
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    output_format = (args.format or "human").lower()
    _validate_choice(output_format, {"human", "json"}, "--format")

    app_config = _load_config_or_raise(args.repo, args.config_file)
    active_rules = _build_configured_rules_or_raise(app_config)
    payload = app_config.to_dict()
    payload["active_rule_ids"] = [rule.rule_id for rule in active_rules]

    if output_format == "json":
        print(json.dumps(payload, sort_keys=True))
        return 0

    lines = [
        "Resolved configuration:",
        f"- source: {payload['source'] or 'defaults'}",
        f"- format: {payload['format']}",
        f"- fail_above: {payload['fail_above']}",
        f"- include: {payload['include']}",
        f"- exclude: {payload['exclude']}",
        f"- rules.enable: {payload['rules']['enable']}",
        f"- rules.disable: {payload['rules']['disable']}",
        f"- objective.name: {payload['objective']['name']}",
        f"- objective.mode: {payload['objective']['mode']}",
        f"- objective.budget_seconds: {payload['objective']['budget_seconds']}",
        f"- objective.packs.enable: {payload['objective']['packs']['enable']}",
        f"- objective.packs.disable: {payload['objective']['packs']['disable']}",
        f"- objective.weights: {payload['objective']['weights']}",
        f"- plugins.include_builtin: {payload['plugins']['include_builtin']}",
        f"- plugins.enable: {payload['plugins']['enable']}",
        f"- plugins.disable: {payload['plugins']['disable']}",
        f"- active_rule_ids: {payload['active_rule_ids']}",
    ]
    print("\n".join(lines))
    return 0


def _cmd_config_init(args: argparse.Namespace) -> int:
    out_path = args.out.resolve()
    if out_path.exists() and not args.force:
        raise CliUsageError(f"refusing to overwrite existing file: {out_path} (use --force)")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(default_config_template(), encoding="utf-8")
    print(f"Wrote starter config: {out_path}")
    return 0


def _cmd_config_validate(args: argparse.Namespace) -> int:
    output_format = (args.format or "human").lower()
    _validate_choice(output_format, {"human", "json"}, "--format")

    app_config = _load_config_or_raise(args.repo, args.config_file)
    active_rules = _build_configured_rules_or_raise(app_config)
    payload = {
        "ok": True,
        "source": app_config.source,
        "active_rule_ids": [rule.rule_id for rule in active_rules],
    }
    if output_format == "json":
        print(json.dumps(payload, sort_keys=True))
        return 0

    print(
        "\n".join(
            [
                "Config is valid.",
                f"- source: {payload['source']}",
                f"- active_rule_ids: {payload['active_rule_ids']}",
            ]
        )
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diff-ai",
        description="Analyze git diffs and produce deterministic risk scores.",
    )
    parser.add_argument("--version", action="store_true", help="Show version and exit.")
    subparsers = parser.add_subparsers(dest="command")

    score = subparsers.add_parser("score", help="Score a diff and output risk summary.")
    _add_diff_input_args(score)
    _add_config_arg(score)
    score.add_argument("--format", default=None, help="Output format: human|json.")
    score.add_argument(
        "--fail-above",
        type=int,
        default=None,
        help="Exit nonzero if overall score is above this value.",
    )

    explain = subparsers.add_parser("explain", help="Explain score details in depth.")
    explain.set_defaults(command="explain")

    prompt = subparsers.add_parser("prompt", help="Generate a paste-ready LLM prompt.")
    _add_diff_input_args(prompt)
    _add_config_arg(prompt)
    prompt.add_argument("--target-score", type=int, default=None)
    prompt.add_argument("--style", default=None, help="concise|thorough|paranoid")
    prompt.add_argument("--persona", default=None, help="reviewer|security|sre|maintainer")
    prompt.add_argument("--include-diff", default=None, help="full|risky-only|top-hunks")
    prompt.add_argument("--max-bytes", type=int, default=None)
    redact_prompt = prompt.add_mutually_exclusive_group()
    redact_prompt.add_argument("--redact-secrets", dest="redact_secrets", action="store_true")
    redact_prompt.add_argument("--no-redact-secrets", dest="redact_secrets", action="store_false")
    prompt.set_defaults(redact_secrets=None)
    prompt.add_argument("--format", default="markdown", choices=["markdown", "json"])

    bundle = subparsers.add_parser("bundle", help="Create an offline LLM handoff bundle.")
    _add_diff_input_args(bundle)
    _add_config_arg(bundle)
    bundle.add_argument("--target-score", type=int, default=None)
    bundle.add_argument("--style", default=None, help="concise|thorough|paranoid")
    bundle.add_argument("--persona", default=None, help="reviewer|security|sre|maintainer")
    bundle.add_argument("--include-diff", default=None, help="full|risky-only|top-hunks")
    bundle.add_argument("--include-snippets", default=None, help="none|minimal|risky-only")
    bundle.add_argument("--max-bytes", type=int, default=None)
    redact_bundle = bundle.add_mutually_exclusive_group()
    redact_bundle.add_argument("--redact-secrets", dest="redact_secrets", action="store_true")
    redact_bundle.add_argument("--no-redact-secrets", dest="redact_secrets", action="store_false")
    bundle.set_defaults(redact_secrets=None)
    bundle.add_argument("--format", default="markdown", choices=["markdown", "json"])
    bundle.add_argument(
        "--out",
        type=Path,
        default=Path("diff-ai-bundle"),
        help="Output directory path (or zip path if --zip).",
    )
    bundle.add_argument("--zip", action="store_true", help="Write bundle as zip file.")

    rules = subparsers.add_parser("rules", help="List available scoring rules.")
    _add_repo_arg(rules)
    _add_config_arg(rules)
    rules.add_argument("--format", default="human", help="Output format: human|json.")

    plugins = subparsers.add_parser("plugins", help="List plugins and scheduling decisions.")
    _add_repo_arg(plugins)
    _add_config_arg(plugins)
    plugins.add_argument("--format", default="human", help="Output format: human|json.")
    dry_run_group = plugins.add_mutually_exclusive_group()
    dry_run_group.add_argument("--dry-run", dest="dry_run", action="store_true")
    dry_run_group.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    plugins.set_defaults(dry_run=True)

    config = subparsers.add_parser("config", help="Show resolved configuration.")
    _add_repo_arg(config)
    _add_config_arg(config)
    config.add_argument("--format", default="human", help="Output format: human|json.")

    config_init = subparsers.add_parser("config-init", help="Create starter config TOML.")
    config_init.add_argument(
        "--out",
        type=Path,
        default=Path(".diff-ai.toml"),
        help="Output path for starter config TOML.",
    )
    config_init.add_argument("--force", action="store_true", help="Overwrite if file exists.")

    config_validate = subparsers.add_parser(
        "config-validate", help="Validate config file and report active rules."
    )
    _add_repo_arg(config_validate)
    config_validate.add_argument(
        "--config",
        dest="config_file",
        type=Path,
        default=Path(".diff-ai.toml"),
        help="Path to config TOML file to validate.",
    )
    config_validate.add_argument("--format", default="human", help="Output format: human|json.")

    return parser


def _add_repo_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=Path, default=Path("."), help="Repository path.")


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", dest="config_file", type=Path, default=None)


def _add_diff_input_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--diff-file", type=Path, default=None, help="Path to unified diff file.")
    parser.add_argument("--stdin", action="store_true", help="Read unified diff from stdin.")
    _add_repo_arg(parser)
    parser.add_argument("--base", default=None, help="Base git revision.")
    parser.add_argument("--head", default=None, help="Head git revision.")
    parser.add_argument("--include", action="append", default=None, help="Include glob pattern.")
    parser.add_argument("--exclude", action="append", default=None, help="Exclude glob pattern.")


def _validate_diff_selection(args: argparse.Namespace) -> None:
    if args.diff_file is not None and args.stdin:
        raise CliUsageError("use either --diff-file or --stdin, not both")
    if (args.base is None) ^ (args.head is None):
        raise CliUsageError("provide both --base and --head together")


def _validate_choice(value: str, allowed: set[str], field_name: str) -> None:
    if value not in allowed:
        raise CliUsageError(f"{field_name} must be one of: {', '.join(sorted(allowed))}")


def _choice_or_default(
    *,
    value: str | None,
    default: str,
    allowed: set[str],
    field_name: str,
) -> str:
    resolved = (value or default).lower()
    _validate_choice(resolved, allowed, field_name)
    return resolved


def _load_config_or_raise(repo: Path, config_file: Path | None = None) -> AppConfig:
    try:
        return load_app_config(repo, config_path=config_file)
    except ValueError as exc:
        raise CliUsageError(str(exc)) from exc


def _build_configured_rules_or_raise(app_config: AppConfig) -> list[Rule]:
    try:
        return build_rules(
            enabled_rule_ids=app_config.rule_enable,
            disabled_rule_ids=app_config.rule_disable,
            profile=app_config.profile,
            objective_name=app_config.objective.name,
            enabled_packs=app_config.objective.enable_packs,
            disabled_packs=app_config.objective.disable_packs,
            category_weights=app_config.objective.category_weights,
        )
    except ValueError as exc:
        raise CliUsageError(str(exc)) from exc


def _resolve_active_packs_or_raise(app_config: AppConfig) -> set[str]:
    try:
        return resolve_active_packs(
            objective_name=app_config.objective.name,
            enabled_packs=app_config.objective.enable_packs,
            disabled_packs=app_config.objective.disable_packs,
        )
    except ValueError as exc:
        raise CliUsageError(str(exc)) from exc


def _schedule_plugins_or_raise(
    app_config: AppConfig, *, active_packs: set[str]
) -> tuple[list[Rule], list[PluginRun]]:
    try:
        return schedule_plugin_rules(
            include_builtin=app_config.plugins.include_builtin,
            active_packs=active_packs,
            mode=app_config.objective.mode,
            budget_seconds=app_config.objective.budget_seconds,
            enabled_plugin_ids=app_config.plugins.enable,
            disabled_plugin_ids=app_config.plugins.disable,
        )
    except ValueError as exc:
        raise CliUsageError(str(exc)) from exc


def _prepare_score_context(
    *,
    diff_file: Path | None,
    stdin: bool,
    repo: Path,
    base: str | None,
    head: str | None,
    include: list[str] | None,
    exclude: list[str] | None,
    app_config: AppConfig,
) -> ScoreContext:
    try:
        diff_text, input_source = _resolve_diff_input(
            diff_file=diff_file,
            stdin=stdin,
            repo=repo,
            base=base,
            head=head,
        )
    except GitError as exc:
        raise CliUsageError(str(exc)) from exc

    include_patterns = include if include is not None else app_config.include
    exclude_patterns = exclude if exclude is not None else app_config.exclude
    rules = _build_configured_rules_or_raise(app_config)
    active_packs = _resolve_active_packs_or_raise(app_config)
    plugin_rules, plugin_runs = _schedule_plugins_or_raise(app_config, active_packs=active_packs)

    files = parse_unified_diff(diff_text)
    filtered_files = _filter_files(files, includes=include_patterns, excludes=exclude_patterns)
    result = score_files(filtered_files, rules=[*rules, *plugin_rules])
    return ScoreContext(
        result=result,
        files=filtered_files,
        diff_text=diff_text,
        input_source=input_source,
        plugin_runs=plugin_runs,
    )


def _resolve_diff_input(
    *,
    diff_file: Path | None,
    stdin: bool,
    repo: Path,
    base: str | None,
    head: str | None,
) -> tuple[str, str]:
    if diff_file is not None:
        return diff_file.read_text(encoding="utf-8"), f"diff_file:{diff_file}"
    if stdin:
        return sys.stdin.read(), "stdin"
    if base is not None and head is not None:
        return get_diff_between(repo, base, head), "git_range"
    return get_working_tree_diff(repo), "git_working_tree"


def _filter_files(
    files: list[FileDiff], *, includes: list[str], excludes: list[str]
) -> list[FileDiff]:
    filtered: list[FileDiff] = []
    for file_diff in files:
        path = file_diff.path
        if includes and not any(fnmatch.fnmatch(path, pattern) for pattern in includes):
            continue
        if excludes and any(fnmatch.fnmatch(path, pattern) for pattern in excludes):
            continue
        filtered.append(file_diff)
    return filtered


def _prepare_bundle_destination(out: Path, zip_requested: bool) -> tuple[Path, Path | None]:
    out_path = out.resolve()
    if not zip_requested:
        return out_path, None
    zip_path = out_path if out_path.suffix == ".zip" else out_path.with_suffix(".zip")
    temp_root = Path(tempfile.mkdtemp(prefix="diff-ai-bundle-"))
    return temp_root, zip_path


def _build_json_payload(
    result: ScoreResult,
    *,
    input_source: str,
    base: str | None,
    head: str | None,
    plugin_runs: list[PluginRun] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "generated_at": datetime.now(tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "base": base,
        "head": head,
        "input_source": input_source,
        "version": __version__,
    }
    if plugin_runs is not None:
        meta["plugins"] = [run.to_dict() for run in plugin_runs]

    return {
        "overall_score": result.overall_score,
        "files": [_serialize_file(item) for item in result.files],
        "findings": [_serialize_finding(item) for item in result.findings],
        "meta": meta,
    }


def _serialize_file(file_score: FileScore) -> dict[str, Any]:
    return {
        "path": file_score.path,
        "score": file_score.score,
        "hunks": [
            {
                "header": hunk.header,
                "score": hunk.score,
                "findings": [_serialize_finding(item) for item in hunk.findings],
            }
            for hunk in file_score.hunks
        ],
        "findings": [_serialize_finding(item) for item in file_score.findings],
    }


def _serialize_finding(finding: Finding) -> dict[str, Any]:
    return {
        "rule_id": finding.rule_id,
        "points": finding.points,
        "message": finding.message,
        "evidence": finding.evidence,
        "scope": finding.scope,
        "suggestion": finding.suggestion,
    }


def _render_human(result: ScoreResult) -> str:
    severity_label = _score_severity(result.overall_score)
    lines = [f"Overall risk score: {result.overall_score}/100 ({severity_label})"]
    top_findings = _top_risk_findings(result.findings, limit=5)

    if top_findings:
        lines.append("Top reasons:")
        for index, finding in enumerate(top_findings, start=1):
            points = f"+{finding.points}" if finding.points >= 0 else str(finding.points)
            lines.append(f"{index}. [{finding.rule_id}] {points} {finding.message}")
            lines.append(f"   evidence: {finding.evidence}")
            lines.append(f"   follow-up: {finding.suggestion}")

    if result.files:
        lines.append("Per-file summary:")
        for file_score in sorted(result.files, key=lambda item: item.score, reverse=True):
            lines.append(
                f"- {file_score.path}: {file_score.score}/100, "
                f"{len(file_score.hunks)} hunks, {len(file_score.findings)} findings"
            )
    return "\n".join(lines)


def _top_risk_findings(findings: list[Finding], limit: int) -> list[Finding]:
    positive = [finding for finding in findings if finding.points > 0]
    ranked = sorted(positive if positive else findings, key=lambda item: item.points, reverse=True)
    return ranked[:limit]


def _score_severity(score: int) -> str:
    if score >= 75:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


if __name__ == "__main__":
    raise SystemExit(main())
