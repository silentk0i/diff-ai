"""Rules package."""

from collections.abc import Callable
from dataclasses import dataclass, field

from diff_ai.config import ProfileConfig
from diff_ai.diff_parser import FileDiff
from diff_ai.rules.api_surface import ApiSurfaceRule
from diff_ai.rules.base import Finding, Rule
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

KNOWN_CATEGORIES = {
    "logic",
    "integration",
    "test_adequacy",
    "security",
    "quality",
    "profile",
}


@dataclass(frozen=True, slots=True)
class RuleInfo:
    """Rule metadata for listing and selection."""

    rule_id: str
    name: str
    description: str
    category: str
    packs: tuple[str, ...]
    default_enabled: bool


@dataclass(frozen=True, slots=True)
class _RuleSpec:
    rule_id: str
    factory: Callable[[], Rule]
    name: str
    description: str
    category: str
    packs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ObjectivePreset:
    default_packs: tuple[str, ...]
    category_weights: dict[str, float]


OBJECTIVE_PRESETS: dict[str, _ObjectivePreset] = {
    "feature_oneshot": _ObjectivePreset(
        default_packs=("logic", "integration", "test_adequacy", "quality", "profile"),
        category_weights={
            "logic": 1.35,
            "integration": 1.15,
            "test_adequacy": 1.35,
            "security": 0.60,
            "quality": 1.00,
            "profile": 1.00,
        },
    ),
    "security_strict": _ObjectivePreset(
        default_packs=(
            "logic",
            "integration",
            "test_adequacy",
            "quality",
            "profile",
            "security",
        ),
        category_weights={
            "logic": 1.00,
            "integration": 1.05,
            "test_adequacy": 1.00,
            "security": 1.40,
            "quality": 1.00,
            "profile": 1.10,
        },
    ),
}


@dataclass(slots=True)
class _WeightedRule:
    _rule: Rule
    _weight: float
    rule_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.rule_id = self._rule.rule_id

    def evaluate(self, files: list[FileDiff]) -> list[Finding]:
        findings = self._rule.evaluate(files)
        if abs(self._weight - 1.0) <= 1e-9:
            return findings

        weighted: list[Finding] = []
        for finding in findings:
            weighted_points = _scale_points(finding.points, self._weight)
            weighted.append(
                Finding(
                    rule_id=finding.rule_id,
                    points=weighted_points,
                    message=finding.message,
                    evidence=finding.evidence,
                    scope=finding.scope,
                    suggestion=finding.suggestion,
                )
            )
        return weighted


def default_rules() -> list[Rule]:
    """Return default deterministic rule set."""
    return build_rules(objective_name="feature_oneshot")


def build_rules(
    *,
    enabled_rule_ids: list[str] | None = None,
    disabled_rule_ids: list[str] | None = None,
    profile: ProfileConfig | None = None,
    objective_name: str = "feature_oneshot",
    enabled_packs: list[str] | None = None,
    disabled_packs: list[str] | None = None,
    category_weights: dict[str, float] | None = None,
) -> list[Rule]:
    """Build rule instances applying objective, pack, and enable/disable filters."""
    effective_profile = profile or ProfileConfig()
    specs = _ordered_rule_specs(effective_profile)
    registry = {spec.rule_id: spec for spec in specs}
    ordered_ids = [spec.rule_id for spec in specs]
    disabled_set = set(disabled_rule_ids or [])
    requested_ids = set(enabled_rule_ids or []) | set(disabled_rule_ids or [])

    unknown = [rule_id for rule_id in requested_ids if rule_id not in registry]
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown rule ids: {joined}")

    candidate_ids = _candidate_rule_ids(
        specs=specs,
        active_packs=resolve_active_packs(
            objective_name=objective_name,
            enabled_packs=enabled_packs,
            disabled_packs=disabled_packs,
        ),
    )
    candidate_set = set(candidate_ids)
    if enabled_rule_ids is None:
        selected_ids = [
            rule_id
            for rule_id in ordered_ids
            if rule_id in candidate_set and rule_id not in disabled_set
        ]
    else:
        selected_ids = [
            rule_id
            for rule_id in _dedupe(enabled_rule_ids)
            if rule_id in registry and rule_id not in disabled_set
        ]

    weights = _build_category_weights(objective_name=objective_name, overrides=category_weights)
    built: list[Rule] = []
    for rule_id in selected_ids:
        spec = registry[rule_id]
        weight = weights.get(spec.category, 1.0)
        if weight < 0:
            raise ValueError(
                f"Category weight for '{spec.category}' must be non-negative, got {weight}."
            )
        if abs(weight) <= 1e-9:
            continue
        rule = spec.factory()
        if abs(weight - 1.0) <= 1e-9:
            built.append(rule)
        else:
            built.append(_WeightedRule(rule, weight))
    return built


def list_rule_info(
    *,
    objective_name: str = "feature_oneshot",
    enabled_packs: list[str] | None = None,
    disabled_packs: list[str] | None = None,
) -> list[RuleInfo]:
    """Return metadata for all known default rules."""
    specs = _ordered_rule_specs(ProfileConfig())
    default_enabled = set(
        _candidate_rule_ids(
            specs=specs,
            active_packs=resolve_active_packs(
                objective_name=objective_name,
                enabled_packs=enabled_packs,
                disabled_packs=disabled_packs,
            ),
        )
    )
    info: list[RuleInfo] = []
    for spec in specs:
        info.append(
            RuleInfo(
                rule_id=spec.rule_id,
                name=spec.name,
                description=spec.description,
                category=spec.category,
                packs=spec.packs,
                default_enabled=spec.rule_id in default_enabled,
            )
        )
    return info


def _candidate_rule_ids(
    *,
    specs: list[_RuleSpec],
    active_packs: set[str],
) -> list[str]:
    return [spec.rule_id for spec in specs if active_packs.intersection(spec.packs)]


def _build_category_weights(
    *,
    objective_name: str,
    overrides: dict[str, float] | None,
) -> dict[str, float]:
    preset = _resolve_objective_preset(objective_name)
    weights = dict(preset.category_weights)
    for category in KNOWN_CATEGORIES:
        weights.setdefault(category, 1.0)

    if overrides:
        unknown_categories = [item for item in overrides if item not in KNOWN_CATEGORIES]
        if unknown_categories:
            joined = ", ".join(sorted(unknown_categories))
            raise ValueError(f"Unknown objective weight categories: {joined}")
        weights.update(overrides)
    return weights


def resolve_active_packs(
    *,
    objective_name: str,
    enabled_packs: list[str] | None,
    disabled_packs: list[str] | None,
) -> set[str]:
    """Resolve active packs from objective preset plus explicit pack overrides."""
    preset = _resolve_objective_preset(objective_name)
    known_packs = _known_packs(_ordered_rule_specs(ProfileConfig()))
    _validate_packs(enabled_packs or [], known_packs)
    _validate_packs(disabled_packs or [], known_packs)

    active_packs = set(preset.default_packs)
    active_packs.update(enabled_packs or [])
    active_packs.difference_update(disabled_packs or [])
    return active_packs


def _resolve_objective_preset(name: str) -> _ObjectivePreset:
    objective = name.lower()
    preset = OBJECTIVE_PRESETS.get(objective)
    if preset is None:
        choices = ", ".join(sorted(OBJECTIVE_PRESETS))
        raise ValueError(f"Unknown objective '{name}'. Expected one of: {choices}")
    return preset


def _validate_packs(packs: list[str], known_packs: set[str]) -> None:
    unknown_packs = [pack for pack in packs if pack not in known_packs]
    if unknown_packs:
        joined = ", ".join(sorted(set(unknown_packs)))
        raise ValueError(f"Unknown rule packs: {joined}")


def _known_packs(specs: list[_RuleSpec]) -> set[str]:
    known: set[str] = set()
    for spec in specs:
        known.update(spec.packs)
    return known


def _ordered_rule_specs(profile: ProfileConfig) -> list[_RuleSpec]:
    return [
        _spec(
            MagnitudeRule,
            category="integration",
            packs=("integration",),
        ),
        _spec(
            CriticalPathsRule,
            category="security",
            packs=("security",),
        ),
        _spec(
            TestSignalsRule,
            category="test_adequacy",
            packs=("test_adequacy",),
        ),
        _spec(
            DependencyChangesRule,
            category="integration",
            packs=("integration",),
        ),
        _spec(
            ConfigChangesRule,
            category="integration",
            packs=("integration",),
        ),
        _spec(
            DangerousPatternsRule,
            category="security",
            packs=("security",),
        ),
        _spec(
            ErrorHandlingRule,
            category="logic",
            packs=("logic",),
        ),
        _spec(
            ApiSurfaceRule,
            category="logic",
            packs=("logic",),
        ),
        _spec(
            DocsOnlyRule,
            category="quality",
            packs=("quality",),
        ),
        _spec(
            DestructiveChangesRule,
            category="integration",
            packs=("integration",),
        ),
        _RuleSpec(
            rule_id="profile_signals",
            factory=lambda: ProfileSignalsRule(profile),
            name="ProfileSignalsRule",
            description=(ProfileSignalsRule.__doc__ or "").strip(),
            category="profile",
            packs=("profile",),
        ),
    ]


def _spec(rule_cls: type[Rule], *, category: str, packs: tuple[str, ...]) -> _RuleSpec:
    instance = rule_cls()
    return _RuleSpec(
        rule_id=instance.rule_id,
        factory=rule_cls,
        name=rule_cls.__name__,
        description=(rule_cls.__doc__ or "").strip(),
        category=category,
        packs=packs,
    )


def _scale_points(points: int, weight: float) -> int:
    scaled = int(round(points * weight))
    if points != 0 and scaled == 0:
        return 1 if points > 0 else -1
    return scaled


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output
