"""Git subprocess helpers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from subprocess import CalledProcessError, run


class GitError(RuntimeError):
    """Raised when git command execution fails."""


EMPTY_TREE_HASH = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def get_working_tree_diff(repo: Path) -> str:
    """Return working tree diff for a repository."""
    return _run_git(repo, ["diff", "--no-color"])


def get_diff_between(repo: Path, base: str, head: str) -> str:
    """Return diff between two revisions."""
    return _run_git(repo, ["diff", "--no-color", f"{base}..{head}"])


def get_diff_between_trees(repo: Path, base_tree: str, head_tree: str) -> str:
    """Return diff between two tree-ish objects."""
    return _run_git(repo, ["diff", "--no-color", base_tree, head_tree])


def get_head_revision(repo: Path) -> str | None:
    """Return HEAD revision if present."""
    try:
        return _run_git(repo, ["rev-parse", "--verify", "HEAD"]).strip()
    except GitError:
        return None


def get_tree_for_revision(repo: Path, revision: str) -> str:
    """Return tree hash for a revision."""
    return _run_git(repo, ["rev-parse", "--verify", f"{revision}^{{tree}}"]).strip()


def build_worktree_tree(repo: Path, *, exclude_paths: list[str] | None = None) -> str:
    """Build a tree object for the current working tree without changing index state."""
    with tempfile.NamedTemporaryFile(prefix="diff-ai-index-", delete=False) as temp_file:
        temp_index_path = Path(temp_file.name)

    try:
        env = {"GIT_INDEX_FILE": str(temp_index_path)}
        _run_git(repo, ["read-tree", "--empty"], env=env)
        _run_git(repo, ["add", "-A"], env=env)
        for excluded in exclude_paths or []:
            _run_git(repo, ["rm", "-q", "--cached", "--ignore-unmatch", "--", excluded], env=env)
        tree_hash = _run_git(repo, ["write-tree"], env=env).strip()
    finally:
        temp_index_path.unlink(missing_ok=True)

    if not tree_hash:
        raise GitError("failed to build working-tree snapshot")
    return tree_hash


def get_file_at_revision(repo: Path, revision: str, path: str) -> str | None:
    """Return file contents from a specific git revision (best effort)."""
    try:
        return _run_git(repo, ["show", f"{revision}:{path}"])
    except GitError:
        return None


def _run_git(repo: Path, args: list[str], env: dict[str, str] | None = None) -> str:
    merged_env: dict[str, str] | None = None
    if env:
        merged_env = os.environ.copy()
        merged_env.update(env)

    try:
        completed = run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=merged_env,
        )
    except CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise GitError(stderr or f"git {' '.join(args)} failed") from exc

    return completed.stdout
