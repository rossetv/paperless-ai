"""Tests for search.relevance.relevance_tier — the similarity→tier mapping."""

from __future__ import annotations

import pytest

from search.relevance import RelevanceThresholds, relevance_tier
from tests.helpers.factories import make_relevance_thresholds

_DEFAULTS = make_relevance_thresholds()


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
    assert relevance_tier(similarity, _DEFAULTS) == expected


def test_keyword_only_none_defaults_to_good() -> None:
    """A keyword-only hit (no vector similarity) is "good", not "weak"."""
    assert relevance_tier(None, _DEFAULTS) == "good"


def test_tiers_are_independent_of_the_gate_floor() -> None:
    """The cut-points are standalone, so a lenient gate floor (e.g. 0.50) does
    not drag a genuinely off-topic result (~0.55) out of the "weak" band."""
    assert relevance_tier(0.55, _DEFAULTS) == "weak"


def test_custom_thresholds_shift_the_bands() -> None:
    """The bands track the supplied thresholds, not any module constant — a
    similarity that is "weak" under the defaults can be "strong" under a lower
    set of cut-points."""
    lenient = RelevanceThresholds(strong=0.50, good=0.40, partial=0.30)
    assert relevance_tier(0.55, lenient) == "strong"  # was "weak" by default
    assert relevance_tier(0.45, lenient) == "good"
    assert relevance_tier(0.35, lenient) == "partial"
    assert relevance_tier(0.25, lenient) == "weak"


def test_collapsed_band_is_unreachable_not_broken() -> None:
    """Equal adjacent cut-points (allowed by config validation) collapse a band:
    with good == strong, the "good" tier is simply unreachable — the function
    still returns a valid tier rather than misbehaving."""
    collapsed = RelevanceThresholds(strong=0.70, good=0.70, partial=0.60)
    assert relevance_tier(0.70, collapsed) == "strong"
    assert relevance_tier(0.68, collapsed) == "partial"  # skips the empty "good"
