"""Helpers for invoking the standalone CLI in tests."""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass

from diff_ai.standalone import main


@dataclass(slots=True)
class CliResult:
    """Captured standalone CLI invocation result."""

    exit_code: int
    stdout: str
    stderr: str


def invoke_cli(args: list[str], input_text: str = "") -> CliResult:
    """Run standalone CLI main() with captured stdio."""
    original_stdin = sys.stdin
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    sys.stdin = io.StringIO(input_text)
    sys.stdout = stdout_buffer
    sys.stderr = stderr_buffer
    try:
        try:
            exit_code = main(args)
        except SystemExit as exc:
            raw_code = exc.code
            exit_code = raw_code if isinstance(raw_code, int) else 1
    finally:
        sys.stdin = original_stdin
        sys.stdout = original_stdout
        sys.stderr = original_stderr

    return CliResult(
        exit_code=exit_code,
        stdout=stdout_buffer.getvalue(),
        stderr=stderr_buffer.getvalue(),
    )
