"""Tests for search.retriever._match_name — taxonomy name resolution (spec §B1).

Verifies the three-pass resolution: exact, punctuation/case-normalised, then
whole-word containment, plus the ambiguous-drop and no-match outcomes. Whole-word
matching is what lets "Deed" resolve to "Property Deed" while refusing to match
"ID" to "Video" (no whole token "id").
"""

from __future__ import annotations

from search.retriever import NameMatch, _match_name
from store.models import TaxonomyEntry


def _entries(*names: str) -> list[TaxonomyEntry]:
    return [
        TaxonomyEntry(kind="document_type", id=i + 1, name=name)
        for i, name in enumerate(names)
    ]


def test_exact_match_wins_first() -> None:
    match = _match_name("Property Deed", _entries("Property Deed", "Deed"))
    assert match == NameMatch(id=1, method="exact")


def test_normalised_match_on_punctuation_and_case() -> None:
    match = _match_name("gas-bill", _entries("Gas Bill"))
    assert match.id == 1
    assert match.method == "normalised"


def test_loose_match_whole_word_subset() -> None:
    match = _match_name("Deed", _entries("Property Deed"))
    assert match.id == 1
    assert match.method == "loose"


def test_loose_match_is_bidirectional() -> None:
    # A verbose planner guess still matches the shorter taxonomy name.
    match = _match_name("Spanish Property Deed", _entries("Property Deed"))
    assert match.id == 1
    assert match.method == "loose"


def test_loose_match_rejects_partial_token() -> None:
    # "id" is not a whole token in "Video"; raw substring would wrongly match.
    assert _match_name("ID", _entries("Video")) == NameMatch(id=None, method="none")


def test_ambiguous_loose_match_drops_with_candidates() -> None:
    match = _match_name("Deed", _entries("Property Deed", "Trust Deed"))
    assert match.id is None
    assert match.method == "ambiguous"
    assert set(match.candidates) == {"Property Deed", "Trust Deed"}


def test_no_match_on_empty_taxonomy() -> None:
    assert _match_name("Deed", []) == NameMatch(id=None, method="none")


def test_exact_beats_an_otherwise_ambiguous_loose_set() -> None:
    # "Deed" exact-matches the literal "Deed" entry and never reaches the loose
    # pass, so the two "… Deed" entries do not make it ambiguous.
    match = _match_name("Deed", _entries("Property Deed", "Deed", "Trust Deed"))
    assert match == NameMatch(id=2, method="exact")
