"""Risk-score aggregation backend with category caps and diminishing returns.

This module intentionally keeps rule detection unchanged. It only transforms
rule hits into a calibrated score that is less prone to sum-then-clamp
saturation and category overscoring.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

# Tuning note:
# - Increase caps to let a category contribute more before flattening.
# - Increase weights to make a category more influential.
# - Add/adjust rule caps to prevent one rule family from dominating via
#   multi-scope accumulation (for example, overall + per-file).
# - Increase scale to make the curve less aggressive (lower scores overall).
# Quick reference for scale=36:
# raw=18 -> 39.3, raw=36 -> 63.2, raw=72 -> 86.5, raw=108 -> 95.0
DEFAULT_CATEGORY_CAPS: dict[str, int] = {
    "logic": 30,
    "security": 35,
    "integration": 35,
    "test_adequacy": 25,
    "style": 15,
    "performance": 25,
    "unknown": 20,
}

DEFAULT_CATEGORY_WEIGHTS: dict[str, float] = {
    "logic": 1.2,
    "security": 1.4,
    "integration": 1.15,
    "test_adequacy": 1.2,
    "style": 0.65,
    "performance": 1.0,
    "unknown": 0.85,
}

# Optional per-rule pre-cap to reduce accumulation bias within one rule family.
# This is applied before category caps/weights.
DEFAULT_RULE_CAPS: dict[str, float] = {
    "magnitude": 20.0,
}

CATEGORY_ALIASES: dict[str, str] = {
    "quality": "style",
    "profile": "integration",
}

DEFAULT_SCALE = 36.0


@dataclass(frozen=True, slots=True)
class RuleHit:
    """Normalized signal emitted by rule evaluation."""

    id: str
    category: str
    points: int
    scope: Literal["global", "file", "hunk"]
    file_path: str | None = None
    hunk_id: int | None = None
    message: str = ""
    evidence: str | None = None


@dataclass(slots=True)
class ScoreBreakdown:
    """Traceable score aggregation output."""

    raw_points_total: int
    raw_points_by_category: dict[str, int]
    capped_points_by_category: dict[str, float]
    transformed_score: float
    final_score_0_100: int
    reasons_topN: list[str]


def score_rule_hits(
    hits: list[RuleHit],
    *,
    caps: dict[str, int] | None = None,
    weights: dict[str, float] | None = None,
    rule_caps: dict[str, float] | None = None,
    scale: float = DEFAULT_SCALE,
    top_n: int = 5,
) -> ScoreBreakdown:
    """Aggregate RuleHit signals into a calibrated score breakdown."""
    if scale <= 0:
        raise ValueError(f"scale must be positive, got {scale}")

    active_caps = dict(DEFAULT_CATEGORY_CAPS if caps is None else caps)
    active_weights = dict(DEFAULT_CATEGORY_WEIGHTS if weights is None else weights)
    active_rule_caps = dict(DEFAULT_RULE_CAPS if rule_caps is None else rule_caps)
    if "unknown" not in active_caps:
        active_caps["unknown"] = DEFAULT_CATEGORY_CAPS["unknown"]
    if "unknown" not in active_weights:
        active_weights["unknown"] = DEFAULT_CATEGORY_WEIGHTS["unknown"]

    ordered_categories = list(active_caps.keys())
    raw_points_by_category = {category: 0 for category in ordered_categories}
    raw_points_total = 0

    normalized_hits: list[tuple[RuleHit, str]] = []
    for hit in hits:
        normalized_category = normalize_category(hit.category, categories=active_caps)
        normalized_hits.append((hit, normalized_category))
        raw_points_total += hit.points
        raw_points_by_category[normalized_category] += hit.points

    adjusted_points_by_hit_index = _adjusted_points_by_hit(
        normalized_hits=normalized_hits,
        rule_caps=active_rule_caps,
    )

    scored_points_by_category = {category: 0.0 for category in ordered_categories}
    for index, (_, category) in enumerate(normalized_hits):
        scored_points_by_category[category] += adjusted_points_by_hit_index[index]

    capped_points_by_category = {
        category: min(scored_points_by_category[category], float(active_caps[category]))
        for category in ordered_categories
    }

    overall_raw = 0.0
    for category in ordered_categories:
        weight = active_weights.get(category, active_weights["unknown"])
        overall_raw += weight * capped_points_by_category[category]

    transformed_score = 100.0 * (1.0 - math.exp(-overall_raw / scale))
    final_score = int(round(_clamp(transformed_score, lower=0.0, upper=100.0)))

    reasons_top_n = _build_top_reasons(
        normalized_hits=normalized_hits,
        adjusted_points_by_hit_index=adjusted_points_by_hit_index,
        weights=active_weights,
        top_n=top_n,
    )

    return ScoreBreakdown(
        raw_points_total=raw_points_total,
        raw_points_by_category=raw_points_by_category,
        capped_points_by_category=capped_points_by_category,
        transformed_score=transformed_score,
        final_score_0_100=final_score,
        reasons_topN=reasons_top_n,
    )


def normalize_category(category: str, *, categories: dict[str, int] | None = None) -> str:
    """Map arbitrary category labels into configured categories."""
    allowed_categories = categories or DEFAULT_CATEGORY_CAPS
    normalized = category.strip().lower() if category else ""
    normalized = CATEGORY_ALIASES.get(normalized, normalized)
    if normalized in allowed_categories:
        return normalized
    return "unknown"


def _build_top_reasons(
    *,
    normalized_hits: list[tuple[RuleHit, str]],
    adjusted_points_by_hit_index: dict[int, float],
    weights: dict[str, float],
    top_n: int,
) -> list[str]:
    if top_n <= 0:
        return []

    ranked: list[tuple[float, float, RuleHit, str]] = []
    for index, (hit, category) in enumerate(normalized_hits):
        adjusted_points = adjusted_points_by_hit_index.get(index, float(hit.points))
        contribution = weights.get(category, weights["unknown"]) * adjusted_points
        ranked.append((contribution, adjusted_points, hit, category))

    positives = [item for item in ranked if item[0] > 0]
    source = positives if positives else ranked
    source.sort(
        key=lambda item: (
            item[0],
            abs(item[1]),
            item[2].id,
            item[2].file_path or "",
            item[2].hunk_id if item[2].hunk_id is not None else -1,
        ),
        reverse=True,
    )

    reasons: list[str] = []
    for _, adjusted_points, hit, category in source[:top_n]:
        scope_bits: list[str] = []
        if hit.file_path:
            scope_bits.append(hit.file_path)
        if hit.hunk_id is not None:
            scope_bits.append(f"hunk {hit.hunk_id}")
        scope_text = f" ({', '.join(scope_bits)})" if scope_bits else ""
        rounded_points = int(round(adjusted_points))
        signed_points = f"+{rounded_points}" if rounded_points >= 0 else str(rounded_points)
        reasons.append(f"[{hit.id}] {signed_points} [{category}] {hit.message}{scope_text}")
    return reasons


def _clamp(value: float, *, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _adjusted_points_by_hit(
    *,
    normalized_hits: list[tuple[RuleHit, str]],
    rule_caps: dict[str, float],
) -> dict[int, float]:
    if not normalized_hits:
        return {}

    hits_by_rule: dict[str, list[tuple[int, RuleHit]]] = {}
    for index, (hit, _) in enumerate(normalized_hits):
        hits_by_rule.setdefault(hit.id, []).append((index, hit))

    adjusted: dict[int, float] = {}
    for rule_id, entries in hits_by_rule.items():
        cap = rule_caps.get(rule_id)
        points_total = sum(entry.points for _, entry in entries)
        factor = _rule_scale_factor(points_total=points_total, cap=cap)
        for index, hit in entries:
            adjusted[index] = hit.points * factor
    return adjusted


def _rule_scale_factor(*, points_total: int, cap: float | None) -> float:
    if cap is None or cap <= 0 or points_total == 0:
        return 1.0
    total = float(points_total)
    magnitude_total = abs(total)
    if magnitude_total <= cap:
        return 1.0
    return cap / magnitude_total
