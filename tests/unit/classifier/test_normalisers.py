"""Tests for classifier.normalisers."""

from __future__ import annotations

import pytest

from classifier.normalisers import COMPANY_SUFFIXES, normalise_name, normalise_simple


class TestNormaliseSimple:
    def test_lowercases_and_collapses_whitespace(self):
        assert normalise_simple("  Bank  Statement ") == "bank statement"

    def test_handles_empty_string(self):
        assert normalise_simple("") == ""

    def test_multiple_spaces_become_single_space(self):
        assert normalise_simple("a   b   c") == "a b c"

    def test_tabs_and_newlines_collapsed(self):
        assert normalise_simple("hello\t\nworld") == "hello world"

    def test_already_normalised(self):
        assert normalise_simple("already clean") == "already clean"

    def test_single_word(self):
        assert normalise_simple("HELLO") == "hello"


class TestNormaliseName:
    def test_strips_punctuation(self):
        assert normalise_name("Acme, Inc.") == "acme"

    def test_strips_ltd_suffix(self):
        assert normalise_name("Revolut Ltd") == "revolut"

    def test_strips_gmbh_suffix(self):
        assert normalise_name("Siemens GmbH") == "siemens"

    def test_strips_inc_suffix(self):
        assert normalise_name("Apple Inc") == "apple"

    def test_strips_llc_suffix(self):
        assert normalise_name("Widgets LLC") == "widgets"

    def test_strips_multiple_trailing_suffixes(self):
        assert normalise_name("Acme Co Ltd") == "acme"

    def test_handles_empty_string(self):
        assert normalise_name("") == ""

    def test_preserves_core_name_parts(self):
        # "ag" is not a recognised company suffix.
        assert normalise_name("Deutsche Bank AG") == "deutsche bank ag"

    def test_strips_corporation(self):
        assert normalise_name("Microsoft Corporation") == "microsoft"

    def test_strips_limited(self):
        assert normalise_name("Tesco Limited") == "tesco"

    def test_strips_plc(self):
        assert normalise_name("BP PLC") == "bp"

    def test_name_with_dots_in_suffix(self):
        # Punctuation is stripped before suffixes are removed.
        assert normalise_name("Acme Ltd.") == "acme"

    def test_all_suffixes_result_in_empty(self):
        assert normalise_name("Ltd Inc") == ""

    def test_folds_accents_to_base_letters(self):
        assert normalise_name("Müller GmbH") == "muller"

    def test_keeps_non_latin_letters(self):
        assert normalise_name("東京電力 Co") == "東京電力"

    def test_names_differing_only_in_indic_vowel_signs_stay_distinct(self):
        assert normalise_name("किरण") != normalise_name("करण")

    def test_keeps_marks_in_scripts_that_write_vowels_as_marks(self):
        assert normalise_name("दिल्ली") == "दिल्ली"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Acme™", "acme"),
            ("Acme℠ Ltd", "acme"),
            ("Office²", "office"),
            ("½ Price", "price"),
        ],
    )
    def test_symbols_and_superscripts_do_not_become_letters(self, value, expected):
        assert normalise_name(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("İstanbul", "istanbul"),
            ("Straße", "strasse"),
            ("ﬁnance", "finance"),
            ("ＡＣＭＥ", "acme"),
            ("ℌilbert", "hilbert"),
            ("Αθήνα", "αθηνα"),
            ("Москва", "москва"),
        ],
    )
    def test_folds_case_and_compatibility_forms(self, value, expected):
        assert normalise_name(value) == expected


class TestCompanySuffixes:
    def test_is_frozenset(self):
        assert isinstance(COMPANY_SUFFIXES, frozenset)

    def test_contains_expected_entries(self):
        expected = {
            "ltd",
            "gmbh",
            "inc",
            "llc",
            "corp",
            "sa",
            "plc",
            "limited",
            "company",
        }
        assert expected.issubset(COMPANY_SUFFIXES)

    def test_all_entries_are_lowercase(self):
        for suffix in COMPANY_SUFFIXES:
            assert suffix == suffix.lower(), f"Suffix {suffix!r} is not lowercase"
