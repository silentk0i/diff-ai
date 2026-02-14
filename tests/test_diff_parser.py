"""Tests for unified diff parsing."""

from pathlib import Path

import pytest

from diff_ai.diff_parser import parse_unified_diff

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "diffs"


def _load_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_parse_simple_diff() -> None:
    parsed = parse_unified_diff(_load_fixture("simple.diff"))
    assert len(parsed) == 1

    file_diff = parsed[0]
    assert file_diff.path == "src/app.py"
    assert file_diff.is_new_file is False
    assert file_diff.is_deleted_file is False
    assert len(file_diff.hunks) == 1

    hunk = file_diff.hunks[0]
    assert (hunk.old_start, hunk.old_count, hunk.new_start, hunk.new_count) == (1, 3, 1, 4)
    assert [line.kind for line in hunk.lines] == ["context", "delete", "add", "add", "context"]

    deleted = hunk.lines[1]
    assert deleted.content == 'print("old")'
    assert deleted.old_lineno == 2
    assert deleted.new_lineno is None

    added = hunk.lines[2]
    assert added.content == 'print("new")'
    assert added.old_lineno is None
    assert added.new_lineno == 2


def test_parse_new_and_deleted_files() -> None:
    parsed = parse_unified_diff(_load_fixture("new_and_deleted.diff"))
    assert len(parsed) == 2

    deleted_file = parsed[0]
    assert deleted_file.path == "tests/legacy.txt"
    assert deleted_file.is_deleted_file is True
    assert deleted_file.is_new_file is False
    assert len(deleted_file.hunks) == 1
    assert [line.kind for line in deleted_file.hunks[0].lines] == ["delete", "delete"]

    new_file = parsed[1]
    assert new_file.path == "docs/new.md"
    assert new_file.is_new_file is True
    assert new_file.is_deleted_file is False
    assert len(new_file.hunks) == 1
    assert [line.kind for line in new_file.hunks[0].lines] == ["add", "add"]
    assert [line.new_lineno for line in new_file.hunks[0].lines] == [1, 2]


def test_parse_no_newline_marker() -> None:
    parsed = parse_unified_diff(_load_fixture("no_newline_marker.diff"))
    assert len(parsed) == 1
    hunk = parsed[0].hunks[0]
    assert [line.kind for line in hunk.lines] == ["delete", "add", "meta"]
    assert hunk.lines[2].content == "No newline at end of file"


def test_parse_unified_without_diff_git_header() -> None:
    diff_text = "\n".join(
        [
            "--- a/foo.txt",
            "+++ b/foo.txt",
            "@@ -5 +5 @@",
            "-old",
            "+new",
        ]
    )
    parsed = parse_unified_diff(diff_text)
    assert len(parsed) == 1

    file_diff = parsed[0]
    assert file_diff.path == "foo.txt"
    assert len(file_diff.hunks) == 1
    hunk = file_diff.hunks[0]
    assert (hunk.old_start, hunk.old_count, hunk.new_start, hunk.new_count) == (5, 1, 5, 1)


def test_invalid_hunk_header_raises() -> None:
    with pytest.raises(ValueError, match="Invalid hunk header"):
        parse_unified_diff(
            "\n".join(["--- a/foo.txt", "+++ b/foo.txt", "@@ -x +1 @@", "-old", "+new"])
        )
