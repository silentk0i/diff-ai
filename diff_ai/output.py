"""Output rendering."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import click

from diff_ai import __version__
from diff_ai.plugins import PluginRun
from diff_ai.rules.base import Finding
from diff_ai.scoring import FileScore, ScoreResult


def render_human(result: ScoreResult) -> str:
    """Render a compact colorized summary."""
    severity_label, color = _score_severity(result.overall_score)
    lines: list[str] = [
        click.style(
            f"Overall risk score: {result.overall_score}/100 ({severity_label})",
            fg=color,
            bold=True,
        )
    ]

    top_findings = _top_risk_findings(result.findings, limit=5)
    if top_findings:
        lines.append(click.style("Top reasons:", bold=True))
        for index, finding in enumerate(top_findings, start=1):
            points = f"+{finding.points}" if finding.points >= 0 else str(finding.points)
            lines.append(f"{index}. [{finding.rule_id}] {points} {finding.message}")
            lines.append(f"   evidence: {finding.evidence}")
            lines.append(f"   follow-up: {finding.suggestion}")

    if result.files:
        lines.append(click.style("Per-file summary:", bold=True))
        for file_score in sorted(result.files, key=lambda item: item.score, reverse=True):
            lines.append(
                f"- {file_score.path}: {file_score.score}/100, "
                f"{len(file_score.hunks)} hunks, {len(file_score.findings)} findings"
            )
    return "\n".join(lines)


def render_json(
    result: ScoreResult,
    *,
    input_source: str,
    base: str | None,
    head: str | None,
    plugin_runs: list[PluginRun] | None = None,
) -> str:
    """Render stable JSON output for CI and automation."""
    payload = build_json_payload(
        result,
        input_source=input_source,
        base=base,
        head=head,
        plugin_runs=plugin_runs,
    )
    return json.dumps(payload, sort_keys=True)


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


def build_json_payload(
    result: ScoreResult,
    *,
    input_source: str,
    base: str | None,
    head: str | None,
    plugin_runs: list[PluginRun] | None = None,
) -> dict[str, Any]:
    """Build stable JSON payload for CI and automation."""
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


def _top_risk_findings(findings: list[Finding], limit: int) -> list[Finding]:
    positive = [finding for finding in findings if finding.points > 0]
    ranked = sorted(positive if positive else findings, key=lambda item: item.points, reverse=True)
    return ranked[:limit]


def _score_severity(score: int) -> tuple[str, str]:
    if score >= 75:
        return ("HIGH", "red")
    if score >= 40:
        return ("MEDIUM", "yellow")
    return ("LOW", "green")
