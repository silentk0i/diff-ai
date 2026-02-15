"""LLM handoff document and bundle helpers (offline only)."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from diff_ai.diff_parser import FileDiff, Hunk, Line
from diff_ai.git import get_file_at_revision
from diff_ai.rules.base import Finding
from diff_ai.scoring import ScoreResult


@dataclass(slots=True)
class PromptSpec:
    """Prompt-generation options."""

    target_score: int = 30
    style: str = "thorough"
    persona: str = "reviewer"
    include_diff: str = "full"
    include_snippets: str = "none"
    max_bytes: int = 200000
    redact_secrets: bool = False
    rubric: list[str] = field(default_factory=list)


def build_prompt_markdown(
    *,
    result: ScoreResult,
    files: list[FileDiff],
    spec: PromptSpec,
    snippets_markdown: str | None = None,
) -> str:
    """Build a single markdown prompt document for LLM handoff."""
    top_findings = _top_findings(result.findings, 5)
    diff_text = select_diff_for_handoff(files=files, result=result, include_diff=spec.include_diff)
    diff_text, was_truncated = truncate_text_to_bytes(
        diff_text,
        max_bytes=spec.max_bytes,
        marker="\n... [diff truncated to max-bytes] ...\n",
    )

    lines: list[str] = [
        "# Diff AI LLM Handoff",
        "",
        "## Summary",
        f"- Overall risk score: **{result.overall_score}/100**",
        f"- Target score: **{spec.target_score}/100**",
        f"- Persona: **{spec.persona}**",
        f"- Style: **{spec.style}**",
        "- Top 5 findings:",
    ]
    for finding in top_findings:
        lines.append(
            f"  - `{finding.rule_id}` ({finding.points:+d}) {finding.message}"
        )
    if not top_findings:
        lines.append("  - No findings were produced.")

    if spec.rubric:
        lines.append("- Project rubric:")
        for item in spec.rubric:
            lines.append(f"  - {item}")

    lines.extend(
        [
            "",
            "## Findings",
        ]
    )
    for finding in result.findings:
        lines.extend(
            [
                f"- rule_id: `{finding.rule_id}`",
                f"  - points: {finding.points:+d}",
                f"  - scope: `{finding.scope}`",
                f"  - evidence: {finding.evidence}",
                f"  - suggestion: {finding.suggestion}",
            ]
        )
    if not result.findings:
        lines.append("- No findings.")

    lines.extend(
        [
            "",
            "## Diff",
            "```diff",
            diff_text or "# (empty diff after filtering)",
            "```",
        ]
    )
    if was_truncated:
        lines.append("")
        lines.append(f"_Diff was truncated to {spec.max_bytes} bytes._")

    if snippets_markdown:
        lines.extend(
            [
                "",
                "## Snippets",
                snippets_markdown,
            ]
        )

    lines.extend(
        [
            "",
            "## Instructions",
            (
                "revise patch to reduce risk below target-score; add tests; keep changes "
                "minimal; explain what you changed"
            ),
            (
                f"Act as a {spec.persona} and respond in a {spec.style} review style."
            ),
            "",
            "## Checklist",
            "- Run repository test command(s) and include failing/passing evidence.",
            "- Run the repo's lint/static analysis commands and fix violations.",
            "- Validate changed contracts/interfaces and failure-path behavior.",
            "- Verify changed files with focused manual checks for risky paths.",
            "- Summarize why final risk is below target and what remains risky.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def build_findings_markdown(result: ScoreResult) -> str:
    """Build markdown summary for bundle artifacts."""
    lines = [
        "# Diff AI Findings",
        "",
        "## Summary",
        f"- Overall risk score: **{result.overall_score}/100**",
        f"- Total findings: **{len(result.findings)}**",
        "",
        "## Findings",
    ]
    for finding in result.findings:
        lines.append(
            f"- `{finding.rule_id}` {finding.points:+d} {finding.message} "
            f"(scope: `{finding.scope}`)"
        )
        lines.append(f"  - evidence: {finding.evidence}")
        lines.append(f"  - suggestion: {finding.suggestion}")
    if not result.findings:
        lines.append("- No findings.")
    return "\n".join(lines).strip() + "\n"


def select_diff_for_handoff(
    *,
    files: list[FileDiff],
    result: ScoreResult,
    include_diff: str,
) -> str:
    """Select diff text according to include-diff mode."""
    include_mode = include_diff.lower()
    if include_mode == "full":
        return render_file_diffs(files)

    if include_mode == "risky-only":
        risky_paths = _risky_paths(result)
        selected_files = [file_diff for file_diff in files if file_diff.path in risky_paths]
        if not selected_files:
            selected_files = _top_scored_files(files, result, limit=3)
        return render_file_diffs(selected_files)

    if include_mode == "top-hunks":
        top_hunks = _top_hunk_refs(result, limit=8)
        if not top_hunks:
            return render_file_diffs(_top_scored_files(files, result, limit=3))
        per_file: dict[str, set[int]] = defaultdict(set)
        for path, hunk_index in top_hunks:
            per_file[path].add(hunk_index)
        return render_file_diffs(files, selected_hunks=per_file)

    raise ValueError(f"Unknown include-diff mode: {include_diff}")


def build_snippets_markdown(
    *,
    repo: Path,
    revision: str,
    files: list[FileDiff],
    result: ScoreResult,
    include_snippets: str,
    max_bytes: int,
) -> str:
    """Build bounded context snippets for risky hunks (best effort)."""
    mode = include_snippets.lower()
    if mode == "none":
        return ""

    refs: list[tuple[str, int]]
    if mode == "minimal":
        refs = []
        for file_diff in files:
            if file_diff.hunks:
                refs.append((file_diff.path, 0))
            if len(refs) >= 3:
                break
    elif mode == "risky-only":
        refs = _top_hunk_refs(result, limit=6)
        if not refs:
            refs = []
            for file_diff in _top_scored_files(files, result, limit=3):
                if file_diff.hunks:
                    refs.append((file_diff.path, 0))
    else:
        raise ValueError(f"Unknown include-snippets mode: {include_snippets}")

    path_to_file = {file_diff.path: file_diff for file_diff in files}
    blocks: list[str] = []
    for path, hunk_index in refs:
        matched_file = path_to_file.get(path)
        if matched_file is None or hunk_index >= len(matched_file.hunks):
            continue
        raw_target_path = (
            matched_file.new_path
            if matched_file.new_path not in {None, "/dev/null"}
            else matched_file.old_path
        )
        if raw_target_path is None or raw_target_path == "/dev/null":
            continue
        target_path: str = raw_target_path
        content = get_file_at_revision(repo, revision, target_path)
        if content is None:
            continue
        block = _snippet_for_hunk(
            path=target_path,
            hunk=matched_file.hunks[hunk_index],
            file_text=content,
        )
        if block:
            blocks.append(block)

    snippets = "\n\n".join(blocks)
    snippets, was_truncated = truncate_text_to_bytes(
        snippets,
        max_bytes=max(1024, max_bytes // 2),
        marker="\n... [snippets truncated] ...\n",
    )
    if was_truncated:
        snippets += "\n\n_Snippets were truncated due to max-bytes._"
    return snippets


def redact_text(text: str) -> str:
    """Redact common secret-like tokens from text outputs."""
    redacted = text
    redacted = _PRIVATE_KEY_BLOCK_RE.sub("<redacted-private-key>", redacted)
    redacted = _BEARER_TOKEN_RE.sub("Bearer <redacted-token>", redacted)
    redacted = _ASSIGNMENT_SECRET_RE.sub(r"\1\2<redacted>", redacted)
    redacted = _AWS_ACCESS_KEY_RE.sub("AKIA<redacted>", redacted)
    redacted = _GITHUB_TOKEN_RE.sub("ghp_<redacted>", redacted)
    return redacted


def redact_payload_strings(data: Any) -> Any:
    """Recursively redact secret-like patterns in payload string values."""
    if isinstance(data, str):
        return redact_text(data)
    if isinstance(data, list):
        return [redact_payload_strings(item) for item in data]
    if isinstance(data, dict):
        return {key: redact_payload_strings(value) for key, value in data.items()}
    return data


def truncate_text_to_bytes(text: str, *, max_bytes: int, marker: str) -> tuple[str, bool]:
    """Truncate utf-8 text to max bytes with deterministic marker."""
    if max_bytes <= 0:
        return ("", True)
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return (text, False)

    marker_bytes = marker.encode("utf-8")
    if len(marker_bytes) >= max_bytes:
        clipped = marker_bytes[:max_bytes].decode("utf-8", errors="ignore")
        return (clipped, True)

    keep = max_bytes - len(marker_bytes)
    clipped = encoded[:keep].decode("utf-8", errors="ignore")
    return (clipped + marker, True)


def render_file_diffs(
    files: list[FileDiff],
    selected_hunks: dict[str, set[int]] | None = None,
) -> str:
    """Render parsed file diffs back to unified-diff text."""
    chunks: list[str] = []
    for file_diff in files:
        selected = selected_hunks.get(file_diff.path) if selected_hunks else None
        chunk = _render_file_diff(file_diff, selected)
        if chunk:
            chunks.append(chunk)
    return "\n".join(chunks).strip()


def _render_file_diff(file_diff: FileDiff, selected_hunks: set[int] | None) -> str:
    lines: list[str] = []
    if file_diff.metadata:
        lines.extend(file_diff.metadata)
    else:
        old_path = file_diff.old_path or file_diff.path
        new_path = file_diff.new_path or file_diff.path
        lines.extend(
            [
                f"diff --git a/{old_path} b/{new_path}",
                f"--- a/{old_path}",
                f"+++ b/{new_path}",
            ]
        )

    for index, hunk in enumerate(file_diff.hunks):
        if selected_hunks is not None and index not in selected_hunks:
            continue
        lines.append(hunk.header)
        for line in hunk.lines:
            lines.append(_render_line(line))

    if selected_hunks is not None and not any(
        index in selected_hunks for index in range(len(file_diff.hunks))
    ):
        return ""

    return "\n".join(lines).strip()


def _render_line(line: Line) -> str:
    if line.kind == "context":
        return f" {line.content}"
    if line.kind == "add":
        return f"+{line.content}"
    if line.kind == "delete":
        return f"-{line.content}"
    return f"\\ {line.content}"


def _top_findings(findings: list[Finding], limit: int) -> list[Finding]:
    positives = [finding for finding in findings if finding.points > 0]
    ranked = sorted(
        positives if positives else findings,
        key=lambda item: item.points,
        reverse=True,
    )
    return ranked[:limit]


def _risky_paths(result: ScoreResult) -> set[str]:
    risky: set[str] = set()
    for finding in result.findings:
        if finding.points <= 0:
            continue
        scope_kind, path, _hunk = _parse_scope(finding.scope)
        if scope_kind in {"file", "hunk"} and path:
            risky.add(path)
    return risky


def _top_scored_files(files: list[FileDiff], result: ScoreResult, limit: int) -> list[FileDiff]:
    by_path = {file_diff.path: file_diff for file_diff in files}
    ordered = sorted(result.files, key=lambda item: item.score, reverse=True)
    selected: list[FileDiff] = []
    for file_score in ordered:
        file_diff = by_path.get(file_score.path)
        if file_diff is None:
            continue
        selected.append(file_diff)
        if len(selected) >= limit:
            break
    return selected


def _top_hunk_refs(result: ScoreResult, limit: int) -> list[tuple[str, int]]:
    scored: list[tuple[str, int, int]] = []
    for file_score in result.files:
        for index, hunk in enumerate(file_score.hunks):
            scored.append((file_score.path, index, hunk.score))
    scored.sort(key=lambda item: item[2], reverse=True)
    positives = [(path, index) for path, index, score in scored if score > 0]
    if positives:
        return positives[:limit]
    return [(path, index) for path, index, _score in scored[:limit]]


def _parse_scope(scope: str) -> tuple[str, str, int | None]:
    if scope == "overall":
        return ("overall", "", None)
    if scope.startswith("file:"):
        return ("file", scope[len("file:") :], None)
    if scope.startswith("hunk:"):
        remainder = scope[len("hunk:") :]
        path, sep, index_text = remainder.rpartition(":")
        if not sep:
            return ("file", remainder, None)
        try:
            return ("hunk", path, int(index_text))
        except ValueError:
            return ("file", path or remainder, None)
    return ("overall", "", None)


def _snippet_for_hunk(*, path: str, hunk: Hunk, file_text: str) -> str:
    lines = file_text.splitlines()
    if not lines:
        return ""
    start = hunk.new_start if hunk.new_start > 0 else hunk.old_start
    start = max(1, start)
    radius = 2
    lo = max(1, start - radius)
    hi = min(len(lines), start + max(1, hunk.new_count) + radius)
    block_lines = [f"{line_no:>6}: {lines[line_no - 1]}" for line_no in range(lo, hi + 1)]
    if not block_lines:
        return ""
    return "\n".join(
        [
            f"### {path}:{start}",
            "```text",
            *block_lines,
            "```",
        ]
    )


_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
_BEARER_TOKEN_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{10,}")
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password)\b(\s*[:=]\s*)(['\"]?)[^\s'\"`]{6,}\3"
)
_AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_GITHUB_TOKEN_RE = re.compile(r"\bghp_[A-Za-z0-9]{20,}\b")
