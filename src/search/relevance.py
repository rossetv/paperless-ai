"""Map an absolute vector similarity to a qualitative relevance tier.

The UI shows a badge rather than the fused RRF score, which is rank-based and
reads as a near-zero number even for a perfect hit. The tier comes from the
absolute vector similarity (``1 / (1 + cosine_distance)``) instead.

The cut-points come from the ``SEARCH_RELEVANCE_TIER_*`` config keys (defaults
0.70 / 0.66 / 0.60, calibrated on ``text-embedding-3-large`` at 3072 dims:
off-topic queries cluster at ~0.54–0.58, broad matches ~0.65, good ~0.69–0.71,
strong ~0.70–0.74). They are independent of ``SEARCH_RELEVANCE_MIN_SIMILARITY``:
the gate decides what to show, the badge how good a shown result is, so a
lenient gate floor must not drag the "weak" badge onto off-topic results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: The four qualitative tiers, strongest first.
RelevanceTier = Literal["strong", "good", "partial", "weak"]


@dataclass(frozen=True, slots=True)
class RelevanceThresholds:
    """The three similarity cut-points for the qualitative relevance badge.

    A document's tier is the highest band its best vector similarity clears:
    ``>= strong`` → "strong", ``>= good`` → "good", ``>= partial`` → "partial",
    below ``partial`` → "weak".

    Precondition: ``0 <= partial <= good <= strong <= 1``, validated by the
    config layer, so it is not re-checked here.
    """

    strong: float
    good: float
    partial: float


def relevance_tier(
    similarity: float | None, thresholds: RelevanceThresholds
) -> RelevanceTier:
    """Bucket an absolute vector *similarity* into a qualitative tier.

    A document with no vector similarity (``None`` — a keyword-only hit, where
    the literal term matched but no chunk was a semantic neighbour) is treated
    as "good": an exact-term match is a deliberate, solid signal even without a
    semantic score, and ranking it "weak" would understate it.
    """
    if similarity is None:
        return "good"
    if similarity >= thresholds.strong:
        return "strong"
    if similarity >= thresholds.good:
        return "good"
    if similarity >= thresholds.partial:
        return "partial"
    return "weak"
