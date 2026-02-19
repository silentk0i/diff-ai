"""Tests for capped, weighted, diminishing-returns scoring backend."""

from __future__ import annotations

from diff_ai.scoring_backend import RuleHit, score_rule_hits


def test_saturation_prevention_with_diminishing_returns() -> None:
    small_hits = _round_robin_hits(count=6, points=2)
    medium_hits = _round_robin_hits(count=24, points=2)
    large_hits = _round_robin_hits(count=120, points=2)

    small = score_rule_hits(small_hits)
    medium = score_rule_hits(medium_hits)
    large = score_rule_hits(large_hits)

    assert 0 <= small.final_score_0_100 < medium.final_score_0_100 < large.final_score_0_100 < 100
    assert (medium.final_score_0_100 - small.final_score_0_100) > (
        large.final_score_0_100 - medium.final_score_0_100
    )


def test_category_caps_limit_accumulation() -> None:
    hits = [
        RuleHit(
            id=f"security_{idx}",
            category="security",
            points=10,
            scope="global",
            message="security hit",
        )
        for idx in range(5)
    ]

    breakdown = score_rule_hits(hits)
    assert breakdown.raw_points_by_category["security"] == 50
    assert breakdown.capped_points_by_category["security"] == 35


def test_weight_effects_security_outweighs_style() -> None:
    security = score_rule_hits(
        [RuleHit(id="sec", category="security", points=12, scope="global", message="sec risk")]
    )
    style = score_rule_hits(
        [RuleHit(id="sty", category="style", points=12, scope="global", message="style risk")]
    )

    assert security.transformed_score > style.transformed_score
    assert security.final_score_0_100 > style.final_score_0_100


def test_deterministic_same_hits_same_result() -> None:
    hits = _round_robin_hits(count=18, points=3)
    baseline = score_rule_hits(hits)
    repeated = score_rule_hits(list(reversed(hits)))

    assert baseline == repeated


def test_magnitude_rule_cap_reduces_multi_scope_accumulation() -> None:
    hits = [
        RuleHit(
            id="magnitude",
            category="integration",
            points=16,
            scope="global",
            message="Moderately large diff size.",
        ),
        RuleHit(
            id="magnitude",
            category="integration",
            points=14,
            scope="file",
            file_path="game/ui.py",
            message="File has substantial code churn.",
        ),
        RuleHit(
            id="api_surface",
            category="logic",
            points=19,
            scope="file",
            file_path="game/ui.py",
            message="API or signature surface changed.",
        ),
        RuleHit(
            id="test_signals",
            category="test_adequacy",
            points=-11,
            scope="global",
            message="Test updates accompany code changes.",
        ),
    ]

    uncapped = score_rule_hits(hits, rule_caps={})
    capped = score_rule_hits(hits)

    assert uncapped.final_score_0_100 > capped.final_score_0_100
    assert uncapped.capped_points_by_category["integration"] == 30
    assert capped.capped_points_by_category["integration"] == 20
    assert 50 <= capped.final_score_0_100 <= 65


def _round_robin_hits(*, count: int, points: int) -> list[RuleHit]:
    categories = ["logic", "security", "integration", "test_adequacy", "style"]
    hits: list[RuleHit] = []
    for idx in range(count):
        category = categories[idx % len(categories)]
        hits.append(
            RuleHit(
                id=f"rule_{idx}",
                category=category,
                points=points,
                scope="file",
                file_path=f"src/file_{idx % 4}.py",
                message=f"{category} signal",
            )
        )
    return hits
