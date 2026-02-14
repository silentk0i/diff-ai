"""Dangerous code-pattern risk rule."""

from __future__ import annotations

from diff_ai.diff_parser import FileDiff
from diff_ai.rules.base import Finding

PATTERNS = [
    ("eval(", 12, "Dynamic eval usage added.", "Avoid eval; use safer explicit parsing paths."),
    ("exec(", 10, "Dynamic exec usage added.", "Replace exec with explicit dispatch logic."),
    (
        "os.system(",
        8,
        "Shell execution path added.",
        "Use safer subprocess APIs with strict argument handling.",
    ),
    (
        "shell=true",
        10,
        "Subprocess shell execution enabled.",
        "Avoid shell=True unless strictly necessary and inputs are trusted.",
    ),
    ("yaml.load(", 8, "Potentially unsafe YAML load usage added.", "Prefer safe loaders."),
    (
        "pickle.loads(",
        9,
        "Unsafe deserialization path added.",
        "Avoid untrusted pickle deserialization.",
    ),
]


class DangerousPatternsRule:
    """Finds risky language/runtime patterns in added lines."""

    rule_id = "dangerous_patterns"

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        findings: list[Finding] = []
        seen: set[tuple[str, str]] = set()

        for file_diff in files:
            path = file_diff.path
            for hunk in file_diff.hunks:
                for line in hunk.lines:
                    if line.kind != "add":
                        continue

                    lowered = line.content.lower()
                    for token, points, message, suggestion in PATTERNS:
                        key = (path, token)
                        if token in lowered and key not in seen:
                            seen.add(key)
                            findings.append(
                                Finding(
                                    rule_id=self.rule_id,
                                    points=points,
                                    message=message,
                                    evidence=f"{path}: `{_clip_line(line.content)}`",
                                    scope=f"file:{path}",
                                    suggestion=suggestion,
                                )
                            )
        return findings


def _clip_line(content: str, max_len: int = 80) -> str:
    stripped = content.strip()
    if len(stripped) <= max_len:
        return stripped
    return stripped[: max_len - 3] + "..."
