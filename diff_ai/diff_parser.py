"""Unified diff parser primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from re import Match, compile
from typing import Literal

HUNK_HEADER_RE = compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?P<section>.*)$"
)


@dataclass(slots=True)
class Line:
    """A single line within a diff hunk."""

    kind: Literal["context", "add", "delete", "meta"]
    content: str
    old_lineno: int | None
    new_lineno: int | None


@dataclass(slots=True)
class Hunk:
    """A diff hunk."""

    header: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    section: str
    lines: list[Line] = field(default_factory=list)


@dataclass(slots=True)
class HunkHeader:
    """Parsed hunk header values."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    section: str


@dataclass(slots=True)
class FileDiff:
    """A parsed file-level diff."""

    old_path: str | None
    new_path: str | None
    hunks: list[Hunk] = field(default_factory=list)
    metadata: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        """Best-effort canonical path for reporting."""
        if self.new_path and self.new_path != "/dev/null":
            return self.new_path
        if self.old_path and self.old_path != "/dev/null":
            return self.old_path
        return "<unknown>"

    @property
    def is_new_file(self) -> bool:
        return self.old_path == "/dev/null" and self.new_path not in {None, "/dev/null"}

    @property
    def is_deleted_file(self) -> bool:
        return self.new_path == "/dev/null" and self.old_path not in {None, "/dev/null"}


def parse_unified_diff(diff_text: str) -> list[FileDiff]:
    """Parse unified diff text into file/hunk/line models."""
    files: list[FileDiff] = []
    current_file: FileDiff | None = None
    current_hunk: Hunk | None = None
    old_lineno: int | None = None
    new_lineno: int | None = None

    def flush_hunk() -> None:
        nonlocal current_hunk, current_file
        if current_file is not None and current_hunk is not None:
            current_file.hunks.append(current_hunk)
        current_hunk = None

    def flush_file() -> None:
        nonlocal current_file
        flush_hunk()
        if current_file is not None:
            files.append(current_file)
        current_file = None

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            flush_file()
            current_file = _start_file_from_diff_header(raw_line)
            continue

        if raw_line.startswith("--- "):
            if current_file is None:
                current_file = FileDiff(old_path=None, new_path=None)
            current_file.old_path = _parse_path(raw_line[4:])
            if current_hunk is None:
                current_file.metadata.append(raw_line)
            continue

        if raw_line.startswith("+++ "):
            if current_file is None:
                current_file = FileDiff(old_path=None, new_path=None)
            current_file.new_path = _parse_path(raw_line[4:])
            if current_hunk is None:
                current_file.metadata.append(raw_line)
            continue

        if raw_line.startswith("@@ "):
            if current_file is None:
                current_file = FileDiff(old_path=None, new_path=None)
            flush_hunk()
            parsed = _parse_hunk_header(raw_line)
            current_hunk = Hunk(
                header=raw_line,
                old_start=parsed.old_start,
                old_count=parsed.old_count,
                new_start=parsed.new_start,
                new_count=parsed.new_count,
                section=parsed.section,
            )
            old_lineno = current_hunk.old_start
            new_lineno = current_hunk.new_start
            continue

        if current_hunk is not None:
            if raw_line.startswith(" "):
                current_hunk.lines.append(
                    Line(
                        kind="context",
                        content=raw_line[1:],
                        old_lineno=old_lineno,
                        new_lineno=new_lineno,
                    )
                )
                old_lineno = _inc(old_lineno)
                new_lineno = _inc(new_lineno)
            elif raw_line.startswith("+"):
                current_hunk.lines.append(
                    Line(kind="add", content=raw_line[1:], old_lineno=None, new_lineno=new_lineno)
                )
                new_lineno = _inc(new_lineno)
            elif raw_line.startswith("-"):
                current_hunk.lines.append(
                    Line(
                        kind="delete",
                        content=raw_line[1:],
                        old_lineno=old_lineno,
                        new_lineno=None,
                    )
                )
                old_lineno = _inc(old_lineno)
            elif raw_line.startswith("\\ "):
                current_hunk.lines.append(
                    Line(kind="meta", content=raw_line[2:], old_lineno=None, new_lineno=None)
                )
            else:
                current_hunk.lines.append(
                    Line(kind="meta", content=raw_line, old_lineno=None, new_lineno=None)
                )
            continue

        if current_file is not None:
            current_file.metadata.append(raw_line)

    flush_file()
    return files


def _start_file_from_diff_header(line: str) -> FileDiff:
    parts = line.split(maxsplit=3)
    old_path = _strip_ab_prefix(parts[2]) if len(parts) > 2 else None
    new_path = _strip_ab_prefix(parts[3]) if len(parts) > 3 else None
    file_diff = FileDiff(old_path=old_path, new_path=new_path)
    file_diff.metadata.append(line)
    return file_diff


def _parse_path(value: str) -> str:
    token = value.strip().split("\t", 1)[0]
    return _strip_ab_prefix(token)


def _strip_ab_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _parse_hunk_header(header: str) -> HunkHeader:
    match: Match[str] | None = HUNK_HEADER_RE.match(header)
    if match is None:
        raise ValueError(f"Invalid hunk header: {header}")

    old_count = int(match.group("old_count")) if match.group("old_count") else 1
    new_count = int(match.group("new_count")) if match.group("new_count") else 1
    section = match.group("section").strip()

    return HunkHeader(
        old_start=int(match.group("old_start")),
        old_count=old_count,
        new_start=int(match.group("new_start")),
        new_count=new_count,
        section=section,
    )


def _inc(value: int | None) -> int | None:
    if value is None:
        return None
    return value + 1
