"""Extended tests for classifier.taxonomy — edge cases and helpers."""

from unittest.mock import MagicMock

from classifier.taxonomy import (
    TaxonomyCache,
    _get_usage_count,
    _index_items,
    _match_item,
    _top_names,
)
from classifier.normalizers import normalize_name, normalize_simple


# ---------------------------------------------------------------------------
# _index_items
# ---------------------------------------------------------------------------


def test_index_items_basic():
    items = [{"name": "Bills", "id": 1}, {"name": "Invoice", "id": 2}]
    mapping = _index_items(items, normalize_simple)
    assert "bills" in mapping
    assert "invoice" in mapping


def test_index_items_skips_empty_names():
    items = [{"name": "", "id": 1}, {"name": "  ", "id": 2}, {"id": 3}]
    mapping = _index_items(items, normalize_simple)
    assert len(mapping) == 0


# ---------------------------------------------------------------------------
# _match_item
# ---------------------------------------------------------------------------


def test_match_item_exact():
    mapping = {"bills": {"id": 1, "name": "Bills"}}
    result = _match_item("Bills", mapping, normalize_simple, False)
    assert result["id"] == 1


def test_match_item_substring():
    mapping = {"revolut": {"id": 1, "name": "Revolut"}}
    result = _match_item("Revolut Ltd", mapping, normalize_name, True)
    assert result["id"] == 1


def test_match_item_empty_name_returns_none():
    mapping = {"bills": {"id": 1}}
    result = _match_item("", mapping, normalize_simple, False)
    assert result is None


def test_match_item_no_match():
    mapping = {"bills": {"id": 1}}
    result = _match_item("Invoice", mapping, normalize_simple, False)
    assert result is None


# ---------------------------------------------------------------------------
# _get_usage_count
# ---------------------------------------------------------------------------


def test_get_usage_count_document_count():
    assert _get_usage_count({"document_count": 10}) == 10


def test_get_usage_count_documents_count():
    assert _get_usage_count({"documents_count": 5}) == 5


def test_get_usage_count_documents_list():
    assert _get_usage_count({"documents": [1, 2, 3]}) == 3


def test_get_usage_count_string_value():
    assert _get_usage_count({"document_count": "7"}) == 7


def test_get_usage_count_missing():
    assert _get_usage_count({}) == 0


def test_get_usage_count_non_numeric():
    assert _get_usage_count({"document_count": "abc"}) == 0


# ---------------------------------------------------------------------------
# _top_names
# ---------------------------------------------------------------------------


def test_top_names_sorted_by_count():
    items = [
        {"name": "Low", "document_count": 1},
        {"name": "High", "document_count": 100},
        {"name": "Mid", "document_count": 50},
    ]
    result = _top_names(items, 10)
    assert result == ["High", "Mid", "Low"]


def test_top_names_with_limit():
    items = [
        {"name": "A", "document_count": 3},
        {"name": "B", "document_count": 2},
        {"name": "C", "document_count": 1},
    ]
    result = _top_names(items, 2)
    assert result == ["A", "B"]


def test_top_names_deduplicates():
    items = [
        {"name": "bills", "document_count": 10},
        {"name": "Bills", "document_count": 20},
    ]
    result = _top_names(items, 10)
    assert len(result) == 1
    assert result[0].lower() == "bills"


def test_top_names_zero_limit_returns_all():
    items = [{"name": "A", "document_count": 1}, {"name": "B", "document_count": 2}]
    result = _top_names(items, 0)
    assert len(result) == 2


def test_top_names_skips_empty_names():
    items = [{"name": "", "document_count": 100}, {"name": "Good", "document_count": 1}]
    result = _top_names(items, 10)
    assert result == ["Good"]


# ---------------------------------------------------------------------------
# TaxonomyCache — creation failure fallback
# ---------------------------------------------------------------------------


def test_taxonomy_cache_correspondent_creation_failure_refreshes():
    client = MagicMock()
    client.list_correspondents.return_value = []
    client.list_document_types.return_value = []
    client.list_tags.return_value = []

    # First create fails; after refresh, the item appears in cache
    client.create_correspondent.side_effect = Exception("duplicate")
    client.list_correspondents.side_effect = [
        [],  # Initial refresh
        [{"id": 5, "name": "ACME", "document_count": 0}],  # Post-failure refresh
    ]

    cache = TaxonomyCache(client, taxonomy_limit=100)
    cache.refresh()

    result = cache.get_or_create_correspondent_id("ACME")
    assert result == 5


def test_taxonomy_cache_document_type_creation_failure_refreshes():
    client = MagicMock()
    client.list_correspondents.return_value = []
    client.list_document_types.return_value = []
    client.list_tags.return_value = []

    client.create_document_type.side_effect = Exception("duplicate")
    client.list_document_types.side_effect = [
        [],
        [{"id": 7, "name": "Invoice", "documents_count": 0}],
    ]

    cache = TaxonomyCache(client, taxonomy_limit=100)
    cache.refresh()

    result = cache.get_or_create_document_type_id("Invoice")
    assert result == 7


def test_taxonomy_cache_tag_creation_failure_refreshes():
    client = MagicMock()
    client.list_correspondents.return_value = []
    client.list_document_types.return_value = []
    client.list_tags.return_value = []

    client.create_tag.side_effect = Exception("duplicate")
    client.list_tags.side_effect = [
        [],
        [{"id": 9, "name": "Bills", "matching_algorithm": "none"}],
    ]

    cache = TaxonomyCache(client, taxonomy_limit=100)
    cache.refresh()

    result = cache.get_or_create_tag_ids(["Bills"])
    assert result == [9]


def test_taxonomy_cache_empty_name_returns_none():
    client = MagicMock()
    client.list_correspondents.return_value = []
    client.list_document_types.return_value = []
    client.list_tags.return_value = []

    cache = TaxonomyCache(client, taxonomy_limit=100)
    cache.refresh()

    assert cache.get_or_create_correspondent_id("  ") is None
    assert cache.get_or_create_document_type_id("  ") is None


def test_taxonomy_cache_infer_matching_algorithm_string():
    client = MagicMock()
    client.list_correspondents.return_value = []
    client.list_document_types.return_value = []
    client.list_tags.return_value = [{"id": 1, "name": "A", "matching_algorithm": "none"}]

    cache = TaxonomyCache(client, taxonomy_limit=100)
    cache.refresh()

    assert cache._infer_matching_algorithm() == "none"


def test_taxonomy_cache_infer_matching_algorithm_default():
    client = MagicMock()
    client.list_correspondents.return_value = []
    client.list_document_types.return_value = []
    client.list_tags.return_value = []

    cache = TaxonomyCache(client, taxonomy_limit=100)
    cache.refresh()

    assert cache._infer_matching_algorithm() == "none"


# ---------------------------------------------------------------------------
# Lines 72-73: _match_item substring matching where key in normalized
# ---------------------------------------------------------------------------


def test_match_item_substring_reverse_direction():
    """Test `key in normalized` path — existing key is substring of the lookup name.

    The mapping has "revolut intl" and we look up "revolut", so
    `normalized in key` matches. But here we test the reverse: mapping
    has "revolut" and we look up "rev" — `key in normalized` does NOT
    match because "revolut" is not in "rev". Instead we need the lookup
    to be longer than the key: mapping has "rev" and we look up "revolut".
    """
    # mapping key "rev" is a substring of the normalized lookup "revolut"
    mapping = {"rev": {"id": 10, "name": "Rev"}}
    result = _match_item("Revolut", mapping, normalize_name, True)
    assert result is not None
    assert result["id"] == 10


def test_match_item_substring_key_in_normalized():
    """When the mapping key is a substring of the normalized query (key in normalized)."""
    # normalized("Global Corp") = "global" (after stripping "corp")
    # mapping has "glob" which is a substring of "global" → match
    mapping = {"glob": {"id": 20, "name": "Glob"}}
    result = _match_item("Global Corp", mapping, normalize_name, True)
    assert result is not None
    assert result["id"] == 20


# ---------------------------------------------------------------------------
# Lines 204, 229, 261: Creation failure + refresh also failing → re-raise
# ---------------------------------------------------------------------------


def test_correspondent_creation_failure_refresh_also_fails_reraises():
    """When create fails AND refresh doesn't find the item, re-raise (line 204)."""
    client = MagicMock()
    client.list_correspondents.return_value = []
    client.list_document_types.return_value = []
    client.list_tags.return_value = []

    client.create_correspondent.side_effect = Exception("API error")
    # After failure, refresh still returns empty → item not found → re-raise
    client.list_correspondents.side_effect = [
        [],  # initial refresh
        [],  # post-failure refresh (still empty)
    ]

    cache = TaxonomyCache(client, taxonomy_limit=100)
    cache.refresh()

    import pytest
    with pytest.raises(Exception, match="API error"):
        cache.get_or_create_correspondent_id("NewCorp")


def test_document_type_creation_failure_refresh_also_fails_reraises():
    """When create fails AND refresh doesn't find the item, re-raise (line 229)."""
    client = MagicMock()
    client.list_correspondents.return_value = []
    client.list_document_types.return_value = []
    client.list_tags.return_value = []

    client.create_document_type.side_effect = Exception("API error")
    client.list_document_types.side_effect = [
        [],  # initial refresh
        [],  # post-failure refresh (still empty)
    ]

    cache = TaxonomyCache(client, taxonomy_limit=100)
    cache.refresh()

    import pytest
    with pytest.raises(Exception, match="API error"):
        cache.get_or_create_document_type_id("NewType")


def test_tag_creation_failure_refresh_also_fails_reraises():
    """When create fails AND refresh doesn't find the tag, re-raise (line 261)."""
    client = MagicMock()
    client.list_correspondents.return_value = []
    client.list_document_types.return_value = []
    client.list_tags.return_value = []

    client.create_tag.side_effect = Exception("API error")
    client.list_tags.side_effect = [
        [],  # initial refresh
        [],  # post-failure refresh (still empty)
    ]

    cache = TaxonomyCache(client, taxonomy_limit=100)
    cache.refresh()

    import pytest
    with pytest.raises(Exception, match="API error"):
        cache.get_or_create_tag_ids(["NewTag"])
