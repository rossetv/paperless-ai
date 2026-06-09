"""Map an absolute vector similarity to a qualitative relevance tier.

The search UI shows a qualitative badge ("Strong / Good / Partial / Weak match")
rather than a raw fused score, because the RRF score is rank-based and reads as
a misleading near-zero number even for a perfect hit. The honest signal is the
**absolute vector similarity** (``1 / (1 + cosine_distance)``) the retriever
already computes; this module buckets it into four tiers.

The cut-points are operator-tunable: they arrive as a
:class:`RelevanceThresholds` built from the ``SEARCH_RELEVANCE_TIER_*`` config
keys (defaults 0.70 / 0.66 / 0.60, calibrated against the live
``text-embedding-3-large`` @ 3072-dim index — off-topic / vague queries cluster
at ~0.54–0.58, broad matches at ~0.65, good matches at ~0.69–0.71, and strong /
exact matches at ~0.70–0.74). This module owns no defaults of its own; the
config layer is the single source of truth and validates the ordering, so a
caller always passes a well-formed triple.

The cut-points are deliberately **standalone**, not tied to
``SEARCH_RELEVANCE_MIN_SIMILARITY`` (the Layer-2 gate floor). The gate decides
what to *show*; the badge describes how *good* a shown result is — different
jobs that want different cut-offs. A lenient gate floor (e.g. 0.5, to reject
almost nothing and rely on the synthesiser) must not drag the "weak" badge down
onto genuinely off-topic results.

Allowed deps: dataclasses, typing (leaf module). Forbidden: common.config,
fastapi, sqlite3.
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

    Precondition: ``0 <= partial <= good <= strong <= 1``. The values originate
    from the ``SEARCH_RELEVANCE_TIER_*`` config keys, which the config layer
    validates at build time (:func:`common.config._parsers._resolve_relevance_tiers`),
    so by the time a triple reaches this module the invariant already holds —
    this dumb data holder does not re-validate.
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

    Args:
        similarity: The document's best vector similarity in (0, 1], or None
            when it was retrieved by keyword search alone.
        thresholds: The operator-configured cut-points (config-validated to be
            ordered ``partial <= good <= strong``).

    Returns:
        One of ``"strong"``, ``"good"``, ``"partial"``, ``"weak"``.
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
