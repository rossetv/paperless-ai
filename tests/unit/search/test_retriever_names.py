"""Name matching of planner filter guesses against taxonomy entries."""

from __future__ import annotations

from search.retriever import _match_name
from store.models import TaxonomyEntry


def _entries(*names: str) -> list[TaxonomyEntry]:
    return [
        TaxonomyEntry(kind="correspondent", id=i, name=n)
        for i, n in enumerate(names, 1)
    ]


def test_non_latin_name_resolves_to_itself_not_the_first_non_latin_entry():
    entries = _entries("Сбербанк", "Газпром", "Ελληνικά")
    assert _match_name("Газпром", entries).id == 2


def test_non_latin_case_difference_still_matches():
    assert _match_name("газпром-", _entries("Сбербанк", "Газпром")).id == 2


def test_unknown_non_latin_name_does_not_match_another_non_latin_name():
    assert _match_name("Лукойл", _entries("Сбербанк", "Газпром")).id is None


def test_symbol_only_guess_matches_nothing():
    assert _match_name("---", _entries("***", "Acme")).id is None


def test_accented_latin_keeps_its_letters():
    entries = _entries("Mller", "Müller")
    assert _match_name("Müller", entries).id == 2
    assert _match_name("muller", entries).id == 2


def test_ascii_names_still_match_loosely():
    assert _match_name("gas bill", _entries("Gas-Bill.")).method == "normalised"
