"""Tests for classifier.normalizers."""

from __future__ import annotations

from classifier.normalizers import COMPANY_SUFFIXES, normalize_name, normalize_simple

class TestNormalizeSimple:
    """Tests for normalize_simple(value)."""

    def test_lowercases_and_collapses_whitespace(self):
        assert normalize_simple("  Bank  Statement ") == "bank statement"

    def test_handles_empty_string(self):
        assert normalize_simple("") == ""

    def test_multiple_spaces_become_single_space(self):
        assert normalize_simple("a   b   c") == "a b c"

    def test_tabs_and_newlines_collapsed(self):
        assert normalize_simple("hello\t\nworld") == "hello world"

    def test_already_normalized(self):
        assert normalize_simple("already clean") == "already clean"

    def test_single_word(self):
        assert normalize_simple("HELLO") == "hello"

class TestNormalizeName:
    """Tests for normalize_name(value)."""

    def test_strips_punctuation(self):
        assert normalize_name("Acme, Inc.") == "acme"

    def test_strips_ltd_suffix(self):
        assert normalize_name("Revolut Ltd") == "revolut"

    def test_strips_gmbh_suffix(self):
        assert normalize_name("Siemens GmbH") == "siemens"

    def test_strips_inc_suffix(self):
        assert normalize_name("Apple Inc") == "apple"

    def test_strips_llc_suffix(self):
        assert normalize_name("Widgets LLC") == "widgets"

    def test_strips_multiple_trailing_suffixes(self):
        # "Co Ltd" -> strips "ltd" then "co"
        assert normalize_name("Acme Co Ltd") == "acme"

    def test_handles_empty_string(self):
        assert normalize_name("") == ""

    def test_preserves_core_name_parts(self):
        # "ag" is not a recognized company suffix, so it stays
        assert normalize_name("Deutsche Bank AG") == "deutsche bank ag"

    def test_strips_corporation(self):
        assert normalize_name("Microsoft Corporation") == "microsoft"

    def test_strips_limited(self):
        assert normalize_name("Tesco Limited") == "tesco"

    def test_strips_plc(self):
        assert normalize_name("BP PLC") == "bp"

    def test_name_with_dots_in_suffix(self):
        # Punctuation is stripped, then suffixes removed
        assert normalize_name("Acme Ltd.") == "acme"

    def test_all_suffixes_result_in_empty(self):
        # If the entire name is company suffixes
        assert normalize_name("Ltd Inc") == ""

class TestCompanySuffixes:
    """Tests for the COMPANY_SUFFIXES constant."""

    def test_is_frozenset(self):
        assert isinstance(COMPANY_SUFFIXES, frozenset)

    def test_contains_expected_entries(self):
        expected = {"ltd", "gmbh", "inc", "llc", "corp", "sa", "plc", "limited", "company"}
        assert expected.issubset(COMPANY_SUFFIXES)

    def test_all_entries_are_lowercase(self):
        for suffix in COMPANY_SUFFIXES:
            assert suffix == suffix.lower(), f"Suffix {suffix!r} is not lowercase"
