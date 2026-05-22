"""Tests for classifier.taxonomy — the module-level helper functions.

Covers ``_index_items``, ``_match_item``, ``_get_usage_count``, and
``_top_names``.  Split from ``test_taxonomy`` (the ``TaxonomyCache`` behaviour)
for the 500-line ceiling (CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

from classifier.normalisers import normalise_name, normalise_simple
from classifier.taxonomy import (
    _get_usage_count,
    _index_items,
    _match_item,
    _top_names,
)


class TestIndexItems:
    """_index_items builds a normalised-name -> item lookup."""

    def test_indexes_by_normaliser(self):
        items = [{"name": "Acme Corp"}, {"name": "Beta LLC"}]

        mapping = _index_items(items, normalise_simple)

        assert "acme corp" in mapping
        assert "beta llc" in mapping

    def test_skips_blank_names(self):
        items = [{"name": ""}, {"name": "  "}, {"name": "Valid"}]

        mapping = _index_items(items, normalise_simple)

        assert len(mapping) == 1
        assert "valid" in mapping

    def test_skips_items_without_name(self):
        items = [{"id": 1}, {"name": "Has Name"}]

        mapping = _index_items(items, normalise_simple)

        assert len(mapping) == 1

    def test_with_normalise_name_strips_suffixes(self):
        items = [{"name": "Revolut Ltd"}]

        mapping = _index_items(items, normalise_name)

        assert "revolut" in mapping


class TestMatchItem:
    """_match_item with exact and substring matching."""

    def test_exact_match(self):
        mapping = {"acme": {"id": 1, "name": "Acme"}}

        result = _match_item("Acme", mapping, normalise_simple, allow_substring=False)

        assert result == {"id": 1, "name": "Acme"}

    def test_exact_match_not_found(self):
        mapping = {"acme": {"id": 1, "name": "Acme"}}

        result = _match_item("Beta", mapping, normalise_simple, allow_substring=False)

        assert result is None

    def test_substring_match_key_in_normalised(self):
        """Existing key 'revolut' found inside query 'revolut ltd'."""
        mapping = {"revolut": {"id": 7, "name": "Revolut"}}

        result = _match_item(
            "Revolut Ltd", mapping, normalise_name, allow_substring=True
        )

        assert result == {"id": 7, "name": "Revolut"}

    def test_substring_match_normalised_in_key(self):
        """Query 'acme' found inside existing key 'acme holdings'."""
        mapping = {"acme holdings": {"id": 8, "name": "Acme Holdings"}}

        result = _match_item("Acme", mapping, normalise_name, allow_substring=True)

        assert result == {"id": 8, "name": "Acme Holdings"}

    def test_substring_not_allowed(self):
        mapping = {"revolut": {"id": 7, "name": "Revolut"}}

        result = _match_item(
            "Revolut Ltd", mapping, normalise_simple, allow_substring=False
        )

        assert result is None

    def test_empty_name_returns_none(self):
        mapping = {"acme": {"id": 1, "name": "Acme"}}

        result = _match_item("", mapping, normalise_simple, allow_substring=True)

        assert result is None


class TestGetUsageCount:
    """_get_usage_count handles different Paperless field name variants."""

    def test_document_count_int(self):
        assert _get_usage_count({"document_count": 42}) == 42

    def test_documents_count_int(self):
        assert _get_usage_count({"documents_count": 7}) == 7

    def test_documents_list(self):
        assert _get_usage_count({"documents": [1, 2, 3]}) == 3

    def test_documents_string_digit(self):
        assert _get_usage_count({"document_count": "15"}) == 15

    def test_no_known_field_returns_zero(self):
        assert _get_usage_count({"id": 1, "name": "Test"}) == 0

    def test_empty_dict_returns_zero(self):
        assert _get_usage_count({}) == 0

    def test_priority_document_count_over_documents(self):
        """document_count is checked first."""
        assert _get_usage_count({"document_count": 10, "documents": [1, 2]}) == 10


class TestTopNames:
    """_top_names returns sorted, limited, deduplicated names."""

    def test_sorted_by_usage_descending(self):
        items = [
            {"name": "Alpha", "document_count": 1},
            {"name": "Beta", "document_count": 10},
            {"name": "Gamma", "document_count": 5},
        ]
        assert _top_names(items, limit=10) == ["Beta", "Gamma", "Alpha"]

    def test_limited_to_n(self):
        items = [{"name": f"Item{i}", "document_count": i} for i in range(20)]
        assert len(_top_names(items, limit=5)) == 5

    def test_deduplication_case_insensitive(self):
        items = [
            {"name": "Acme", "document_count": 5},
            {"name": "acme", "document_count": 3},
            {"name": "ACME", "document_count": 1},
        ]
        result = _top_names(items, limit=10)
        assert len(result) == 1
        # The first occurrence's name is kept; max count is used
        assert result[0] == "Acme"

    def test_limit_zero_returns_all(self):
        items = [{"name": f"X{i}", "document_count": 0} for i in range(5)]
        assert len(_top_names(items, limit=0)) == 5

    def test_empty_names_skipped(self):
        items = [
            {"name": "", "document_count": 5},
            {"name": "Valid", "document_count": 1},
        ]
        assert _top_names(items, limit=10) == ["Valid"]

    def test_tiebreaker_is_alphabetical(self):
        items = [
            {"name": "Zeta", "document_count": 5},
            {"name": "Alpha", "document_count": 5},
        ]
        result = _top_names(items, limit=10)
        assert result == ["Alpha", "Zeta"]
