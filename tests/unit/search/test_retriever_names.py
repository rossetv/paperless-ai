"""Name matching of planner filter guesses against taxonomy entries."""

from __future__ import annotations

import pytest

from search.retriever import _fold, _match_name, _normalise, _tokenise
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


def test_vowel_signs_keep_a_hindi_name_in_one_token_per_word():
    assert _tokenise("राजेश कुमार") == {"राजेश", "कुमार"}


def test_hindi_names_differing_only_in_vowel_signs_do_not_match_each_other():
    entries = _entries("सुनील", "सोनल")
    assert _match_name("सोनल.", entries).id == 2
    assert _match_name("सुनील.", entries).id == 1
    assert _match_name("सनल", entries).id is None


def test_accents_on_greek_and_cyrillic_letters_are_still_dropped():
    assert _tokenise("Ελλάδα Йод") == {"ελλαδα", "иод"}
    assert _tokenise("Café MÜLLER") == {"cafe", "muller"}


@pytest.mark.parametrize("apostrophe", ["\u02bc", "\u02bb", "\u2019"])
def test_modifier_apostrophes_fold_like_the_ascii_one(apostrophe):
    assert _normalise(f"O{apostrophe}Reilly Media") == _normalise("O'Reilly Media")
    assert _fold(f"O{apostrophe}Reilly") == _fold("O'Reilly")


def test_arabic_vowel_marks_are_optional():
    assert _fold("مُحَمَّد") == _fold("محمد")


def test_hebrew_vowel_points_are_optional():
    assert _fold("שָׁלוֹם") == _fold("שלום")
