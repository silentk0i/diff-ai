"""Review-mode diff resolution and AI-task state tracking."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from diff_ai.git import (
    EMPTY_TREE_HASH,
    GitError,
    build_worktree_tree,
    get_diff_between,
    get_diff_between_trees,
    get_head_revision,
    get_tree_for_revision,
    get_working_tree_diff,
)

REVIEW_MODE_MILESTONE = "milestone"
REVIEW_MODE_AI_TASK = "ai-task"
REVIEW_MODES = {REVIEW_MODE_MILESTONE, REVIEW_MODE_AI_TASK}


@dataclass(slots=True)
class ResolvedDiffInput:
    """Resolved diff source and optional AI-task checkpoint details."""

    diff_text: str
    input_source: str
    base: str | None
    head: str | None
    review_mode: str
    state_path: Path | None = None
    checkpoint_tree: str | None = None


def normalize_review_mode(raw: str | None, default: str = REVIEW_MODE_MILESTONE) -> str:
    """Normalize review mode labels."""
    value = (raw or default).strip().lower().replace("_", "-")
    if value not in REVIEW_MODES:
        allowed = ", ".join(sorted(REVIEW_MODES))
        raise ValueError(f"review mode must be one of: {allowed}")
    return value


def resolve_diff_input(
    *,
    repo: Path,
    diff_file: Path | None,
    stdin: bool,
    base: str | None,
    head: str | None,
    review_mode: str,
    state_file: Path,
) -> ResolvedDiffInput:
    """Resolve diff input based on explicit source and review mode."""
    if diff_file is not None:
        return ResolvedDiffInput(
            diff_text=diff_file.read_text(encoding="utf-8"),
            input_source=f"diff_file:{diff_file}",
            base=base,
            head=head,
            review_mode=review_mode,
        )
    if stdin:
        import sys

        return ResolvedDiffInput(
            diff_text=sys.stdin.read(),
            input_source="stdin",
            base=base,
            head=head,
            review_mode=review_mode,
        )
    if review_mode == REVIEW_MODE_MILESTONE:
        if base is not None and head is not None:
            return ResolvedDiffInput(
                diff_text=get_diff_between(repo, base, head),
                input_source="git_range",
                base=base,
                head=head,
                review_mode=review_mode,
            )
        return ResolvedDiffInput(
            diff_text=get_working_tree_diff(repo),
            input_source="git_working_tree",
            base=base,
            head=head,
            review_mode=review_mode,
        )
    return _resolve_ai_task_diff(repo=repo, state_file=state_file)


def save_ai_task_checkpoint(state_path: Path, tree_hash: str) -> None:
    """Persist AI-task checkpoint after a successful run."""
    updated_at = datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {
        "version": 1,
        "last_tree": tree_hash,
        "updated_at": updated_at,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _resolve_ai_task_diff(*, repo: Path, state_file: Path) -> ResolvedDiffInput:
    state_path = state_file if state_file.is_absolute() else (repo / state_file)
    excluded_paths: list[str] = []
    try:
        excluded_paths.append(state_path.relative_to(repo).as_posix())
    except ValueError:
        pass
    current_tree = build_worktree_tree(repo, exclude_paths=excluded_paths)
    previous_tree = _resolve_previous_ai_task_tree(repo=repo, state_path=state_path)

    diff_text = get_diff_between_trees(repo, previous_tree, current_tree)
    return ResolvedDiffInput(
        diff_text=diff_text,
        input_source="review_mode:ai-task",
        base=previous_tree,
        head=current_tree,
        review_mode=REVIEW_MODE_AI_TASK,
        state_path=state_path,
        checkpoint_tree=current_tree,
    )


def _resolve_previous_ai_task_tree(*, repo: Path, state_path: Path) -> str:
    state = _load_state(state_path)
    saved_tree = state.get("last_tree")
    if isinstance(saved_tree, str) and saved_tree:
        try:
            get_diff_between_trees(repo, saved_tree, saved_tree)
            return saved_tree
        except GitError:
            pass

    head = get_head_revision(repo)
    if head is not None:
        return get_tree_for_revision(repo, head)
    return EMPTY_TREE_HASH


def _load_state(state_path: Path) -> dict[str, object]:
    if not state_path.exists():
        return {}
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw
