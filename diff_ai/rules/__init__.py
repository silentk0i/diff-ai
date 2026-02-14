"""Rules package."""

from collections.abc import Callable
from dataclasses import dataclass

from diff_ai.config import ProfileConfig
from diff_ai.rules.api_surface import ApiSurfaceRule
from diff_ai.rules.base import Rule
from diff_ai.rules.config_changes import ConfigChangesRule
from diff_ai.rules.critical_paths import CriticalPathsRule
from diff_ai.rules.dangerous_patterns import DangerousPatternsRule
from diff_ai.rules.dependency_changes import DependencyChangesRule
from diff_ai.rules.destructive_changes import DestructiveChangesRule
from diff_ai.rules.docs_only import DocsOnlyRule
from diff_ai.rules.error_handling import ErrorHandlingRule
from diff_ai.rules.magnitude import MagnitudeRule
from diff_ai.rules.profile_signals import ProfileSignalsRule
from diff_ai.rules.test_signals import TestSignalsRule


@dataclass(frozen=True, slots=True)
class RuleInfo:
    """Rule metadata for listing and selection."""

    rule_id: str
    name: str
    description: str
    default_enabled: bool


def default_rules() -> list[Rule]:
    """Return default deterministic rule set."""
    return [factory() for factory in _default_rule_factories(ProfileConfig())]


def build_rules(
    *,
    enabled_rule_ids: list[str] | None = None,
    disabled_rule_ids: list[str] | None = None,
    profile: ProfileConfig | None = None,
) -> list[Rule]:
    """Build rule instances applying optional enable/disable filters."""
    effective_profile = profile or ProfileConfig()
    registry = _rule_registry(effective_profile)
    ordered_ids = [rule.rule_id for rule in default_rules()]
    disabled_set = set(disabled_rule_ids or [])
    requested_ids = set(enabled_rule_ids or []) | set(disabled_rule_ids or [])

    unknown = [rule_id for rule_id in requested_ids if rule_id not in registry]
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown rule ids: {joined}")

    if enabled_rule_ids is None:
        selected_ids = [rule_id for rule_id in ordered_ids if rule_id not in disabled_set]
    else:
        selected_ids = [
            rule_id
            for rule_id in _dedupe(enabled_rule_ids)
            if rule_id in registry and rule_id not in disabled_set
        ]

    return [registry[rule_id]() for rule_id in selected_ids]


def list_rule_info() -> list[RuleInfo]:
    """Return metadata for all known default rules."""
    info: list[RuleInfo] = []
    for rule in default_rules():
        info.append(
            RuleInfo(
                rule_id=rule.rule_id,
                name=rule.__class__.__name__,
                description=(rule.__class__.__doc__ or "").strip(),
                default_enabled=True,
            )
        )
    return info


def _default_rule_factories(profile: ProfileConfig) -> list[Callable[[], Rule]]:
    return [
        MagnitudeRule,
        CriticalPathsRule,
        TestSignalsRule,
        DependencyChangesRule,
        ConfigChangesRule,
        DangerousPatternsRule,
        ErrorHandlingRule,
        ApiSurfaceRule,
        DocsOnlyRule,
        DestructiveChangesRule,
        lambda: ProfileSignalsRule(profile),
    ]


def _rule_registry(profile: ProfileConfig) -> dict[str, Callable[[], Rule]]:
    registry: dict[str, Callable[[], Rule]] = {}
    for factory in _default_rule_factories(profile):
        instance = factory()
        registry[instance.rule_id] = factory
    return registry


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output
