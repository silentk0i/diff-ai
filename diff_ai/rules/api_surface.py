"""API surface change risk rule."""

from __future__ import annotations

from pathlib import PurePosixPath

from diff_ai.diff_parser import FileDiff
from diff_ai.rules.base import Finding

API_PATH_MARKERS = ("/api/", "/routes/", "/route/", "/controllers/", "/endpoints/")
SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".go", ".java", ".rb"}
SIGNATURE_MARKERS = (
    "def ",
    "async def ",
    "class ",
    "function ",
    "export function ",
    "interface ",
    "type ",
    "func ",
)


class ApiSurfaceRule:
    """Scores risk from public surface and signature churn."""

    rule_id = "api_surface"

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        findings: list[Finding] = []
        for file_diff in files:
            path = file_diff.path
            if _is_test_path(path) or not _is_source_path(path):
                continue

            signature_changes = 0
            for hunk in file_diff.hunks:
                for line in hunk.lines:
                    if line.kind not in {"add", "delete"}:
                        continue
                    if _looks_like_signature(line.content):
                        signature_changes += 1

            if signature_changes == 0:
                continue

            points = min(14, signature_changes * 2)
            lowered = path.lower()
            if any(marker in lowered for marker in API_PATH_MARKERS):
                points += 4

            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=min(18, points),
                    message="API or signature surface changed.",
                    evidence=f"{path} has {signature_changes} signature-level line changes.",
                    scope=f"file:{path}",
                    suggestion="Confirm backward compatibility and update contract tests.",
                )
            )

        return findings


def _is_source_path(path: str) -> bool:
    return PurePosixPath(path.lower()).suffix in SOURCE_SUFFIXES


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    return (
        lowered.startswith("tests/")
        or "/tests/" in lowered
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _looks_like_signature(content: str) -> bool:
    stripped = content.lstrip()
    return any(stripped.startswith(marker) for marker in SIGNATURE_MARKERS)
