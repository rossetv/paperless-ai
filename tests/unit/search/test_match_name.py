"""Tests for search.retriever._match_name — taxonomy name resolution (spec §B1).

Verifies the resolution passes: exact, punctuation/case-normalised, then
content-word-set equality (order- and connective-independent). A loose match
resolves only when an entry has EXACTLY the candidate's meaningful words — never
broader, never more specific. Guesses that overlap real names but are not equal
are reported as near-misses (diagnostic only, never applied); genuinely
word-identical duplicate types are ambiguous.
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


def test_word_set_equality_resolves_ignoring_order_and_stopwords() -> None:
    # The reported bug: "Employment Contract" must resolve to "Contract of
    # Employment" (same words, reordered, connective "of" ignored) and NOT to
    # the broader "Contract".
    match = _match_name(
        "Employment Contract", _entries("Contract", "Contract of Employment")
    )
    assert match == NameMatch(id=2, method="loose")


def test_word_set_equality_is_symmetric_across_stopwords() -> None:
    # The reverse phrasing resolves too — here the candidate carries the
    # connective and the taxonomy name omits it.
    match = _match_name("Contract of Employment", _entries("Employment Contract"))
    assert match.id == 1
    assert match.method == "loose"


def test_broader_index_type_does_not_resolve() -> None:
    # "Contract" drops "employment": a filter broader than asked is refused and
    # surfaced as a near-miss, never applied.
    match = _match_name("Employment Contract", _entries("Contract"))
    assert match.id is None
    assert match.method == "near_miss"
    assert match.candidates == ("Contract",)


def test_more_specific_index_type_does_not_resolve() -> None:
    # An addendum is a different document — a more specific type is refused.
    match = _match_name("Employment Contract", _entries("Employment Contract Addendum"))
    assert match.id is None
    assert match.method == "near_miss"
    assert match.candidates == ("Employment Contract Addendum",)


def test_near_miss_candidates_rank_by_shared_word_count() -> None:
    match = _match_name(
        "Annual Tax Return",
        _entries("Tax Return Schedule", "Tax Notice", "Council Letter"),
    )
    assert match.method == "near_miss"
    # "Tax Return Schedule" shares 2 words, "Tax Notice" shares 1, "Council
    # Letter" shares none — ranked by overlap, the zero-overlap entry excluded.
    assert match.candidates == ("Tax Return Schedule", "Tax Notice")


def test_near_miss_caps_candidates_at_five() -> None:
    entries = _entries("Tax A", "Tax B", "Tax C", "Tax D", "Tax E", "Tax F", "Tax G")
    match = _match_name("Tax Return", entries)
    assert match.method == "near_miss"
    assert len(match.candidates) == 5


def test_word_identical_types_are_ambiguous() -> None:
    # Two taxonomy names with the same word set and neither an exact/normalised
    # string match of the guess — genuinely ambiguous, dropped with candidates.
    match = _match_name(
        "Contract Employment",
        _entries("Employment Contract", "Contract of Employment"),
    )
    assert match.id is None
    assert match.method == "ambiguous"
    assert set(match.candidates) == {"Employment Contract", "Contract of Employment"}


def test_stopword_only_candidate_matches_nothing() -> None:
    # A guess that is only connectives has no content tokens and must not match
    # every entry by virtue of an empty set.
    match = _match_name("the", _entries("The Deed", "The Contract"))
    assert match == NameMatch(id=None, method="none")


def test_zero_word_overlap_is_plain_no_match() -> None:
    match = _match_name("Invoice", _entries("Receipt", "Statement"))
    assert match == NameMatch(id=None, method="none")


def test_rejects_partial_token() -> None:
    # "id" is not a whole token in "Video"; raw substring would wrongly match.
    assert _match_name("ID", _entries("Video")) == NameMatch(id=None, method="none")


def test_no_match_on_empty_taxonomy() -> None:
    assert _match_name("Deed", []) == NameMatch(id=None, method="none")


def test_exact_beats_an_otherwise_ambiguous_loose_set() -> None:
    # "Deed" exact-matches the literal "Deed" entry and never reaches the loose
    # pass, so the two "… Deed" entries do not make it ambiguous.
    match = _match_name("Deed", _entries("Property Deed", "Deed", "Trust Deed"))
    assert match == NameMatch(id=2, method="exact")
