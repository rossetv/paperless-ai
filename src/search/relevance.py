"""Map an absolute vector similarity to a qualitative relevance tier.

The search UI shows a qualitative badge ("Strong / Good / Partial / Weak match")
rather than a raw fused score, because the RRF score is rank-based and reads as
a misleading near-zero number even for a perfect hit. The honest signal is the
**absolute vector similarity** (``1 / (1 + cosine_distance)``) the retriever
already computes; this module buckets it into four tiers.

The cut-points were calibrated against the live ``text-embedding-3-large`` @
3072-dim index (2026-06-09): off-topic / vague queries cluster at ~0.54–0.58,
broad matches at ~0.65, good matches at ~0.69–0.71, and strong / exact matches
at ~0.70–0.74.

They are deliberately **standalone**, not tied to
``SEARCH_RELEVANCE_MIN_SIMILARITY`` (the Layer-2 gate floor). The gate decides
what to *show*; the badge describes how *good* a shown result is — different
jobs that want different cut-offs. A lenient gate floor (e.g. 0.5, to reject
almost nothing and rely on the synthesiser) must not drag the "weak" badge down
onto genuinely off-topic results.

Allowed deps: typing (leaf module). Forbidden: common.config, fastapi, sqlite3.
"""

from __future__ import annotations

from typing import Literal

#: The four qualitative tiers, strongest first.
RelevanceTier = Literal["strong", "good", "partial", "weak"]

# Calibrated similarity cut-points (see module docstring). A document's tier is
# the highest band its best vector similarity clears. Retune here if the
# embedding model changes its similarity range.
_STRONG_AT = 0.70
_GOOD_AT = 0.66
_PARTIAL_AT = 0.60


def relevance_tier(similarity: float | None) -> RelevanceTier:
    """Bucket an absolute vector *similarity* into a qualitative tier.

    A document with no vector similarity (``None`` — a keyword-only hit, where
    the literal term matched but no chunk was a semantic neighbour) is treated
    as "good": an exact-term match is a deliberate, solid signal even without a
    semantic score, and ranking it "weak" would understate it.

    Args:
        similarity: The document's best vector similarity in (0, 1], or None
            when it was retrieved by keyword search alone.

    Returns:
        One of ``"strong"``, ``"good"``, ``"partial"``, ``"weak"``.
    """
    if similarity is None:
        return "good"
    if similarity >= _STRONG_AT:
        return "strong"
    if similarity >= _GOOD_AT:
        return "good"
    if similarity >= _PARTIAL_AT:
        return "partial"
    return "weak"
