"""CLI entrypoint for diff-ai."""

from __future__ import annotations

import fnmatch
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated, Literal

import typer

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
from diff_ai.output import build_json_payload, render_human, render_json
from diff_ai.rules import build_rules, list_rule_info
from diff_ai.rules.base import Rule
from diff_ai.scoring import ScoreResult, score_files

app = typer.Typer(
    name="diff-ai",
    no_args_is_help=True,
    help="Analyze git diffs and produce deterministic risk scores.",
)


def version_callback(value: bool) -> None:
    """Print version and exit when --version is provided."""
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Annotated[
        bool,
        typer.Option("--version", help="Show version and exit.", callback=version_callback),
    ] = False,
) -> None:
    """Root command callback."""
    _ = version


@app.command("score")
def score_command(
    diff_file: Annotated[Path | None, typer.Option(help="Path to unified diff file.")] = None,
    stdin: Annotated[bool, typer.Option(help="Read unified diff from stdin.")] = False,
    repo: Annotated[Path, typer.Option(help="Repository path.")] = Path("."),
    base: Annotated[str | None, typer.Option(help="Base git revision.")] = None,
    head: Annotated[str | None, typer.Option(help="Head git revision.")] = None,
    format: Annotated[
        str | None, typer.Option(help="Output format: human|json.", show_default="human")
    ] = None,
    fail_above: Annotated[
        int | None, typer.Option(help="Exit nonzero if overall score is above this value.")
    ] = None,
    include: Annotated[list[str] | None, typer.Option(help="Include glob pattern.")] = None,
    exclude: Annotated[list[str] | None, typer.Option(help="Exclude glob pattern.")] = None,
    config_file: Annotated[
        Path | None,
        typer.Option("--config", help="Path to config TOML file."),
    ] = None,
) -> None:
    """Score a diff and output risk summary."""
    app_config = _load_config_or_raise(repo, config_file)
    output_format = (format or app_config.format).lower()
    if output_format not in {"human", "json"}:
        raise typer.BadParameter("format must be one of: human, json", param_hint="--format")

    if diff_file and stdin:
        raise typer.BadParameter("Use either --diff-file or --stdin, not both.")

    if (base is None) ^ (head is None):
        raise typer.BadParameter("Provide both --base and --head together.")

    score_ctx = _prepare_score_context(
        diff_file=diff_file,
        stdin=stdin,
        repo=repo,
        base=base,
        head=head,
        include=include,
        exclude=exclude,
        app_config=app_config,
    )
    fail_threshold = fail_above if fail_above is not None else app_config.fail_above

    if output_format == "json":
        typer.echo(
            render_json(
                score_ctx.result,
                input_source=score_ctx.input_source,
                base=base,
                head=head,
            )
        )
    else:
        typer.echo(render_human(score_ctx.result))

    if fail_threshold is not None and score_ctx.result.overall_score > fail_threshold:
        raise typer.Exit(code=1)


@app.command("explain")
def explain_command() -> None:
    """Explain score details in depth."""
    typer.echo("Not implemented yet. Step 1 scaffold complete.")
    raise typer.Exit(code=0)


@app.command("prompt")
def prompt_command(
    diff_file: Annotated[Path | None, typer.Option(help="Path to unified diff file.")] = None,
    stdin: Annotated[bool, typer.Option(help="Read unified diff from stdin.")] = False,
    repo: Annotated[Path, typer.Option(help="Repository path.")] = Path("."),
    base: Annotated[str | None, typer.Option(help="Base git revision.")] = None,
    head: Annotated[str | None, typer.Option(help="Head git revision.")] = None,
    include: Annotated[list[str] | None, typer.Option(help="Include glob pattern.")] = None,
    exclude: Annotated[list[str] | None, typer.Option(help="Exclude glob pattern.")] = None,
    target_score: Annotated[int | None, typer.Option("--target-score")] = None,
    style: Annotated[str | None, typer.Option(help="concise|thorough|paranoid")] = None,
    persona: Annotated[str | None, typer.Option(help="reviewer|security|sre|maintainer")] = None,
    include_diff: Annotated[str | None, typer.Option(help="full|risky-only|top-hunks")] = None,
    max_bytes: Annotated[int | None, typer.Option("--max-bytes")] = None,
    redact_secrets: Annotated[
        bool | None,
        typer.Option("--redact-secrets/--no-redact-secrets", help="Redact secret-like values."),
    ] = None,
    format: Annotated[
        Literal["markdown", "json"],
        typer.Option(help="Output format."),
    ] = "markdown",
    config_file: Annotated[
        Path | None,
        typer.Option("--config", help="Path to config TOML file."),
    ] = None,
) -> None:
    """Generate a paste-ready LLM prompt (no API calls)."""
    app_config = _load_config_or_raise(repo, config_file)
    llm_defaults = app_config.llm

    resolved_style = _choice_or_default(
        value=style,
        default=llm_defaults.style,
        allowed={"concise", "thorough", "paranoid"},
        field_name="--style",
    )
    resolved_persona = _choice_or_default(
        value=persona,
        default=llm_defaults.persona,
        allowed={"reviewer", "security", "sre", "maintainer"},
        field_name="--persona",
    )
    resolved_include_diff = _choice_or_default(
        value=include_diff,
        default=llm_defaults.include_diff,
        allowed={"full", "risky-only", "top-hunks"},
        field_name="--include-diff",
    )
    resolved_target_score = target_score if target_score is not None else llm_defaults.target_score
    resolved_max_bytes = max_bytes if max_bytes is not None else llm_defaults.max_bytes
    resolved_redact = redact_secrets if redact_secrets is not None else llm_defaults.redact_secrets

    score_ctx = _prepare_score_context(
        diff_file=diff_file,
        stdin=stdin,
        repo=repo,
        base=base,
        head=head,
        include=include,
        exclude=exclude,
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

    if format == "markdown":
        typer.echo(prompt_md)
        return

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
            "base": base,
            "head": head,
        },
    }
    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("bundle")
def bundle_command(
    diff_file: Annotated[Path | None, typer.Option(help="Path to unified diff file.")] = None,
    stdin: Annotated[bool, typer.Option(help="Read unified diff from stdin.")] = False,
    repo: Annotated[Path, typer.Option(help="Repository path.")] = Path("."),
    base: Annotated[str | None, typer.Option(help="Base git revision.")] = None,
    head: Annotated[str | None, typer.Option(help="Head git revision.")] = None,
    include: Annotated[list[str] | None, typer.Option(help="Include glob pattern.")] = None,
    exclude: Annotated[list[str] | None, typer.Option(help="Exclude glob pattern.")] = None,
    target_score: Annotated[int | None, typer.Option("--target-score")] = None,
    style: Annotated[str | None, typer.Option(help="concise|thorough|paranoid")] = None,
    persona: Annotated[str | None, typer.Option(help="reviewer|security|sre|maintainer")] = None,
    include_diff: Annotated[str | None, typer.Option(help="full|risky-only|top-hunks")] = None,
    include_snippets: Annotated[str | None, typer.Option(help="none|minimal|risky-only")] = None,
    max_bytes: Annotated[int | None, typer.Option("--max-bytes")] = None,
    redact_secrets: Annotated[
        bool | None,
        typer.Option("--redact-secrets/--no-redact-secrets", help="Redact secret-like values."),
    ] = None,
    format: Annotated[
        Literal["markdown", "json"],
        typer.Option(help="Command output format."),
    ] = "markdown",
    out: Annotated[Path, typer.Option(help="Output directory path (or zip path if --zip).")] = Path(
        "diff-ai-bundle"
    ),
    zip: Annotated[bool, typer.Option("--zip", help="Write bundle as zip file.")] = False,
    config_file: Annotated[
        Path | None,
        typer.Option("--config", help="Path to config TOML file."),
    ] = None,
) -> None:
    """Create an offline LLM handoff bundle."""
    app_config = _load_config_or_raise(repo, config_file)
    llm_defaults = app_config.llm
    resolved_style = _choice_or_default(
        value=style,
        default=llm_defaults.style,
        allowed={"concise", "thorough", "paranoid"},
        field_name="--style",
    )
    resolved_persona = _choice_or_default(
        value=persona,
        default=llm_defaults.persona,
        allowed={"reviewer", "security", "sre", "maintainer"},
        field_name="--persona",
    )
    resolved_include_diff = _choice_or_default(
        value=include_diff,
        default=llm_defaults.include_diff,
        allowed={"full", "risky-only", "top-hunks"},
        field_name="--include-diff",
    )
    resolved_include_snippets = _choice_or_default(
        value=include_snippets,
        default=llm_defaults.include_snippets,
        allowed={"none", "minimal", "risky-only"},
        field_name="--include-snippets",
    )
    resolved_target_score = target_score if target_score is not None else llm_defaults.target_score
    resolved_max_bytes = max_bytes if max_bytes is not None else llm_defaults.max_bytes
    resolved_redact = redact_secrets if redact_secrets is not None else llm_defaults.redact_secrets

    score_ctx = _prepare_score_context(
        diff_file=diff_file,
        stdin=stdin,
        repo=repo,
        base=base,
        head=head,
        include=include,
        exclude=exclude,
        app_config=app_config,
    )

    selected_diff = select_diff_for_handoff(
        files=score_ctx.files,
        result=score_ctx.result,
        include_diff=resolved_include_diff,
    )
    selected_diff, _patch_truncated = truncate_text_to_bytes(
        selected_diff,
        max_bytes=resolved_max_bytes,
        marker="\n... [patch truncated to max-bytes] ...\n",
    )
    snippets_markdown = build_snippets_markdown(
        repo=repo,
        revision=head or "HEAD",
        files=score_ctx.files,
        result=score_ctx.result,
        include_snippets=resolved_include_snippets,
        max_bytes=resolved_max_bytes,
    )

    spec = PromptSpec(
        target_score=resolved_target_score,
        style=resolved_style,
        persona=resolved_persona,
        include_diff=resolved_include_diff,
        include_snippets=resolved_include_snippets,
        max_bytes=resolved_max_bytes,
        redact_secrets=resolved_redact,
        rubric=list(llm_defaults.rubric),
    )
    prompt_md = build_prompt_markdown(
        result=score_ctx.result,
        files=score_ctx.files,
        spec=spec,
        snippets_markdown=snippets_markdown if resolved_include_snippets != "none" else None,
    )
    findings_md = build_findings_markdown(score_ctx.result)
    findings_payload = build_json_payload(
        score_ctx.result,
        input_source=score_ctx.input_source,
        base=base,
        head=head,
    )

    if resolved_redact:
        prompt_md = redact_text(prompt_md)
        findings_md = redact_text(findings_md)
        selected_diff = redact_text(selected_diff)
        findings_payload = redact_payload_strings(findings_payload)

    bundle_dir, archive_path = _prepare_bundle_destination(out, zip)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    findings_json_path = bundle_dir / "findings.json"
    findings_md_path = bundle_dir / "findings.md"
    patch_path = bundle_dir / "patch.diff"
    prompt_path = bundle_dir / "prompt.md"

    findings_json_path.write_text(json.dumps(findings_payload, sort_keys=True), encoding="utf-8")
    findings_md_path.write_text(findings_md, encoding="utf-8")
    patch_content = selected_diff
    if patch_content and not patch_content.endswith("\n"):
        patch_content += "\n"
    patch_path.write_text(patch_content, encoding="utf-8")
    prompt_path.write_text(prompt_md, encoding="utf-8")

    output_path = str(bundle_dir)
    if zip and archive_path is not None:
        with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item in ("findings.json", "findings.md", "patch.diff", "prompt.md"):
                zf.write(bundle_dir / item, arcname=item)
        shutil.rmtree(bundle_dir)
        output_path = str(archive_path)

    if format == "json":
        typer.echo(
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
        typer.echo(f"Bundle written to: {output_path}")


@app.command("rules")
def rules_command(
    repo: Annotated[Path, typer.Option(help="Repository path.")] = Path("."),
    format: Annotated[str, typer.Option(help="Output format: human|json.")] = "human",
    config_file: Annotated[
        Path | None,
        typer.Option("--config", help="Path to config TOML file."),
    ] = None,
) -> None:
    """List or inspect available scoring rules."""
    output_format = format.lower()
    if output_format not in {"human", "json"}:
        raise typer.BadParameter("format must be one of: human, json", param_hint="--format")

    app_config = _load_config_or_raise(repo, config_file)
    active_rules = _build_configured_rules_or_raise(app_config)
    active_ids = {rule.rule_id for rule in active_rules}
    rule_info = list_rule_info()

    if output_format == "json":
        payload = {
            "rules": [
                {
                    "rule_id": item.rule_id,
                    "name": item.name,
                    "description": item.description,
                    "default_enabled": item.default_enabled,
                    "enabled": item.rule_id in active_ids,
                }
                for item in rule_info
            ],
            "meta": {"config_source": app_config.source},
        }
        typer.echo(json.dumps(payload, sort_keys=True))
        return

    lines = ["Available rules:"]
    for item in rule_info:
        status = "enabled" if item.rule_id in active_ids else "disabled"
        lines.append(f"- {item.rule_id} [{status}] - {item.description}")
    typer.echo("\n".join(lines))


@app.command("config")
def config_command(
    repo: Annotated[Path, typer.Option(help="Repository path.")] = Path("."),
    format: Annotated[str, typer.Option(help="Output format: human|json.")] = "human",
    config_file: Annotated[
        Path | None,
        typer.Option("--config", help="Path to config TOML file."),
    ] = None,
) -> None:
    """Show resolved configuration."""
    output_format = format.lower()
    if output_format not in {"human", "json"}:
        raise typer.BadParameter("format must be one of: human, json", param_hint="--format")

    app_config = _load_config_or_raise(repo, config_file)
    active_rules = _build_configured_rules_or_raise(app_config)
    payload = app_config.to_dict()
    payload["active_rule_ids"] = [rule.rule_id for rule in active_rules]

    if output_format == "json":
        typer.echo(json.dumps(payload, sort_keys=True))
        return

    lines = [
        "Resolved configuration:",
        f"- source: {payload['source'] or 'defaults'}",
        f"- format: {payload['format']}",
        f"- fail_above: {payload['fail_above']}",
        f"- include: {payload['include']}",
        f"- exclude: {payload['exclude']}",
        f"- rules.enable: {payload['rules']['enable']}",
        f"- rules.disable: {payload['rules']['disable']}",
        f"- active_rule_ids: {payload['active_rule_ids']}",
    ]
    typer.echo("\n".join(lines))


@app.command("config-init")
def config_init_command(
    out: Annotated[Path, typer.Option(help="Output path for starter config TOML.")] = Path(
        ".diff-ai.toml"
    ),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite if file already exists."),
    ] = False,
) -> None:
    """Create a starter repository config file."""
    out_path = out.resolve()
    if out_path.exists() and not force:
        raise typer.BadParameter(
            f"Refusing to overwrite existing file: {out_path}. Use --force to overwrite."
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(default_config_template(), encoding="utf-8")
    typer.echo(f"Wrote starter config: {out_path}")


@app.command("config-validate")
def config_validate_command(
    repo: Annotated[Path, typer.Option(help="Repository path.")] = Path("."),
    config_file: Annotated[
        Path,
        typer.Option("--config", help="Path to config TOML file to validate."),
    ] = Path(".diff-ai.toml"),
    format: Annotated[str, typer.Option(help="Output format: human|json.")] = "human",
) -> None:
    """Validate a config file and report active rules."""
    output_format = format.lower()
    if output_format not in {"human", "json"}:
        raise typer.BadParameter("format must be one of: human, json", param_hint="--format")

    app_config = _load_config_or_raise(repo, config_file)
    active_rules = _build_configured_rules_or_raise(app_config)
    payload = {
        "ok": True,
        "source": app_config.source,
        "active_rule_ids": [rule.rule_id for rule in active_rules],
    }
    if output_format == "json":
        typer.echo(json.dumps(payload, sort_keys=True))
        return
    typer.echo(
        "\n".join(
            [
                "Config is valid.",
                f"- source: {payload['source']}",
                f"- active_rule_ids: {payload['active_rule_ids']}",
            ]
        )
    )


def main() -> None:
    """Console script entrypoint."""
    app()


def _resolve_diff_input(
    *,
    diff_file: Path | None,
    stdin: bool,
    repo: Path,
    base: str | None,
    head: str | None,
) -> tuple[str, str]:
    if diff_file is not None:
        return (diff_file.read_text(encoding="utf-8"), f"diff_file:{diff_file}")

    if stdin:
        return (sys.stdin.read(), "stdin")

    if base is not None and head is not None:
        return (get_diff_between(repo, base, head), "git_range")

    return (get_working_tree_diff(repo), "git_working_tree")


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


def _load_config_or_raise(repo: Path, config_file: Path | None = None) -> AppConfig:
    try:
        return load_app_config(repo, config_path=config_file)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="config") from exc


def _build_configured_rules_or_raise(app_config: AppConfig) -> list[Rule]:
    try:
        return build_rules(
            enabled_rule_ids=app_config.rule_enable,
            disabled_rule_ids=app_config.rule_disable,
            profile=app_config.profile,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="config.rules") from exc


def _choice_or_default(
    *,
    value: str | None,
    default: str,
    allowed: set[str],
    field_name: str,
) -> str:
    resolved = (value or default).lower()
    if resolved not in allowed:
        choices = ", ".join(sorted(allowed))
        raise typer.BadParameter(f"{field_name} must be one of: {choices}", param_hint=field_name)
    return resolved


def _prepare_bundle_destination(out: Path, zip_requested: bool) -> tuple[Path, Path | None]:
    out_path = out.resolve()
    if not zip_requested:
        return (out_path, None)

    if out_path.suffix == ".zip":
        zip_path = out_path
    else:
        zip_path = out_path.with_suffix(".zip")

    temp_root = Path(tempfile.mkdtemp(prefix="diff-ai-bundle-"))
    return (temp_root, zip_path)


class _ScoreContext:
    """Resolved score inputs and outputs for shared command flows."""

    def __init__(
        self,
        *,
        result: ScoreResult,
        files: list[FileDiff],
        diff_text: str,
        input_source: str,
    ) -> None:
        self.result = result
        self.files = files
        self.diff_text = diff_text
        self.input_source = input_source


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
) -> _ScoreContext:
    try:
        diff_text, input_source = _resolve_diff_input(
            diff_file=diff_file,
            stdin=stdin,
            repo=repo,
            base=base,
            head=head,
        )
    except GitError as exc:
        raise typer.BadParameter(str(exc)) from exc

    include_patterns = include if include is not None else app_config.include
    exclude_patterns = exclude if exclude is not None else app_config.exclude
    rules = _build_configured_rules_or_raise(app_config)

    files = parse_unified_diff(diff_text)
    filtered_files = _filter_files(files, includes=include_patterns, excludes=exclude_patterns)
    result = score_files(filtered_files, rules=rules)
    return _ScoreContext(
        result=result,
        files=filtered_files,
        diff_text=diff_text,
        input_source=input_source,
    )
