"""Critical-path risk rule."""

from __future__ import annotations

from diff_ai.diff_parser import FileDiff
from diff_ai.rules.base import Finding


class CriticalPathsRule:
    """Raises risk when sensitive system areas are changed."""

    rule_id = "critical_paths"

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        findings: list[Finding] = []
        for file_diff in files:
            path = file_diff.path
            categories = _matching_categories(path)
            for category, points, reason, suggestion in categories:
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        points=points,
                        message=reason,
                        evidence=f"Matched critical path category '{category}' in {path}.",
                        scope=f"file:{path}",
                        suggestion=suggestion,
                    )
                )
        return findings


def _matching_categories(path: str) -> list[tuple[str, int, str, str]]:
    lowered = path.lower()
    matches: list[tuple[str, int, str, str]] = []

    if _contains_any(lowered, ("auth", "permission", "token", "secret", "oauth", "crypto")):
        matches.append(
            (
                "security",
                16,
                "Security-sensitive code path modified.",
                "Validate authentication, authorization, and secret-handling edge cases.",
            )
        )

    if _contains_any(lowered, ("payment", "billing", "invoice", "checkout", "ledger")):
        matches.append(
            (
                "money",
                14,
                "Financial transaction path modified.",
                "Add/confirm idempotency, rollback, and reconciliation checks.",
            )
        )

    if _contains_any(lowered, ("migrations/", "alembic/", "schema", ".sql")):
        matches.append(
            (
                "data_migration",
                13,
                "Schema or migration surface modified.",
                "Test migration/rollback paths against representative production data.",
            )
        )

    if _contains_any(
        lowered,
        (
            ".github/workflows/",
            "dockerfile",
            "terraform",
            "helm",
            "k8s",
            "deploy",
            "infra",
        ),
    ):
        matches.append(
            (
                "deployment",
                10,
                "CI/CD or deployment surface modified.",
                "Validate pipeline and deployment behavior in a non-prod environment.",
            )
        )

    return matches


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)
