"""Tests for classifier.normalisers."""

from __future__ import annotations

from classifier.normalisers import COMPANY_SUFFIXES, normalise_name, normalise_simple


class TestNormaliseSimple:
    """Tests for normalise_simple(value)."""

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
    """Tests for normalise_name(value)."""

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
        # "Co Ltd" -> strips "ltd" then "co"
        assert normalise_name("Acme Co Ltd") == "acme"

    def test_handles_empty_string(self):
        assert normalise_name("") == ""

    def test_preserves_core_name_parts(self):
        # "ag" is not a recognized company suffix, so it stays
        assert normalise_name("Deutsche Bank AG") == "deutsche bank ag"

    def test_strips_corporation(self):
        assert normalise_name("Microsoft Corporation") == "microsoft"

    def test_strips_limited(self):
        assert normalise_name("Tesco Limited") == "tesco"

    def test_strips_plc(self):
        assert normalise_name("BP PLC") == "bp"

    def test_name_with_dots_in_suffix(self):
        # Punctuation is stripped, then suffixes removed
        assert normalise_name("Acme Ltd.") == "acme"

    def test_all_suffixes_result_in_empty(self):
        # If the entire name is company suffixes
        assert normalise_name("Ltd Inc") == ""


class TestCompanySuffixes:
    """Tests for the COMPANY_SUFFIXES constant."""

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
