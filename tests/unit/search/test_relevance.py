"""Tests for search.relevance.relevance_tier — the similarity→tier mapping."""

from __future__ import annotations

import pytest

from search.relevance import relevance_tier


@pytest.mark.parametrize(
    ("similarity", "expected"),
    [
        (0.90, "strong"),
        (0.74, "strong"),  # the property-deeds query
        (0.70, "strong"),  # exactly the strong cut-point
        (0.69, "good"),
        (0.66, "good"),  # exactly the good cut-point
        (0.65, "partial"),
        (0.60, "partial"),  # exactly the partial cut-point
        (0.59, "weak"),
        (0.30, "weak"),
    ],
)
def test_tier_bands(similarity: float, expected: str) -> None:
    assert relevance_tier(similarity) == expected


def test_keyword_only_none_defaults_to_good() -> None:
    """A keyword-only hit (no vector similarity) is "good", not "weak"."""
    assert relevance_tier(None) == "good"


def test_tiers_are_independent_of_the_gate_floor() -> None:
    """The cut-points are standalone, so a lenient gate floor (e.g. 0.50) does
    not drag a genuinely off-topic result (~0.55) out of the "weak" band."""
    assert relevance_tier(0.55) == "weak"
