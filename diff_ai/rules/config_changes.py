"""Configuration change risk rule."""

from __future__ import annotations

from pathlib import PurePosixPath

from diff_ai.diff_parser import FileDiff
from diff_ai.rules.base import Finding

RISKY_CONFIG_TOKENS = ("debug=true", "allow_all", "allow-unauthenticated", "0.0.0.0")


class ConfigChangesRule:
    """Raises risk when runtime/infrastructure config is modified."""

    rule_id = "config_changes"

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        findings: list[Finding] = []
        for file_diff in files:
            path = file_diff.path
            if not _is_config_path(path):
                continue

            changed_lines = 0
            risky_hits = 0
            for hunk in file_diff.hunks:
                for line in hunk.lines:
                    if line.kind in {"add", "delete"}:
                        changed_lines += 1
                    if line.kind == "add":
                        lowered = line.content.lower()
                        if any(token in lowered for token in RISKY_CONFIG_TOKENS):
                            risky_hits += 1

            if changed_lines == 0:
                continue

            points = 7 + min(4, risky_hits * 2)
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    points=points,
                    message="Configuration surface changed.",
                    evidence=f"{path} has {changed_lines} changed config lines.",
                    scope=f"file:{path}",
                    suggestion="Validate config behavior in staging before production rollout.",
                )
            )
        return findings


def _is_config_path(path: str) -> bool:
    lowered = path.lower()
    filename = PurePosixPath(lowered).name
    return (
        filename.startswith(".env")
        or "config/" in lowered
        or "settings/" in lowered
        or "docker-compose" in lowered
        or "k8s/" in lowered
        or "helm/" in lowered
        or filename in {"nginx.conf", "gunicorn.conf.py", "application.yml", "application.yaml"}
    )
