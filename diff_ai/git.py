"""Git subprocess helpers."""

from __future__ import annotations

from pathlib import Path
from subprocess import CalledProcessError, run


class GitError(RuntimeError):
    """Raised when git command execution fails."""


def get_working_tree_diff(repo: Path) -> str:
    """Return working tree diff for a repository."""
    return _run_git(repo, ["diff", "--no-color"])


def get_diff_between(repo: Path, base: str, head: str) -> str:
    """Return diff between two revisions."""
    return _run_git(repo, ["diff", "--no-color", f"{base}..{head}"])


def get_file_at_revision(repo: Path, revision: str, path: str) -> str | None:
    """Return file contents from a specific git revision (best effort)."""
    try:
        return _run_git(repo, ["show", f"{revision}:{path}"])
    except GitError:
        return None


def _run_git(repo: Path, args: list[str]) -> str:
    try:
        completed = run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
    except CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise GitError(stderr or f"git {' '.join(args)} failed") from exc

    return completed.stdout
