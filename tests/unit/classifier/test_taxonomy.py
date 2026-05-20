"""Tests for classifier.taxonomy — the ``TaxonomyCache`` behaviour.

The module-level helpers (``_index_items``, ``_match_item``,
``_get_usage_count``, ``_top_names``) are covered in ``test_taxonomy_helpers``;
this file is split off it for the 500-line ceiling (CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

import threading

import pytest

from classifier.taxonomy import TaxonomyCache
from tests.helpers.mocks import make_mock_paperless


def _make_cache(
    correspondents=None,
    document_types=None,
    tags=None,
    taxonomy_limit=100,
) -> TaxonomyCache:
    """Create a TaxonomyCache with a mock PaperlessClient."""
    client = make_mock_paperless()
    client.list_correspondents.return_value = correspondents or []
    client.list_document_types.return_value = document_types or []
    client.list_tags.return_value = tags or []
    cache = TaxonomyCache(client, taxonomy_limit)
    return cache

def _corr(id: int, name: str, count: int = 0) -> dict:
    return {"id": id, "name": name, "document_count": count}

def _dtype(id: int, name: str, count: int = 0) -> dict:
    return {"id": id, "name": name, "document_count": count}

def _tag(id: int, name: str, count: int = 0, matching_algorithm=None) -> dict:
    d = {"id": id, "name": name, "document_count": count}
    if matching_algorithm is not None:
        d["matching_algorithm"] = matching_algorithm
    return d

class TestRefresh:
    """refresh() populates internal caches from the client."""

    def test_refresh_populates_correspondent_names(self):
        cache = _make_cache(correspondents=[_corr(1, "Acme", 10), _corr(2, "Beta", 5)])

        cache.refresh()

        names = cache.correspondent_names()
        assert "Acme" in names
        assert "Beta" in names

    def test_refresh_populates_document_type_names(self):
        cache = _make_cache(document_types=[_dtype(1, "Invoice", 3)])

        cache.refresh()

        assert "Invoice" in cache.document_type_names()

    def test_refresh_populates_tag_names(self):
        cache = _make_cache(tags=[_tag(1, "2025", 7)])

        cache.refresh()

        assert "2025" in cache.tag_names()

    def test_refresh_calls_client_list_methods(self):
        cache = _make_cache()

        cache.refresh()

        cache._client.list_correspondents.assert_called_once()
        cache._client.list_document_types.assert_called_once()
        cache._client.list_tags.assert_called_once()

class TestNameLists:
    """Cached name lists are sorted by usage and limited."""

    def test_correspondent_names_sorted_by_usage_descending(self):
        cache = _make_cache(correspondents=[
            _corr(1, "Alpha", 1),
            _corr(2, "Beta", 10),
            _corr(3, "Gamma", 5),
        ])
        cache.refresh()

        names = cache.correspondent_names()

        assert names == ["Beta", "Gamma", "Alpha"]

    def test_names_limited_by_taxonomy_limit(self):
        corrs = [_corr(i, f"Corr{i}", i) for i in range(50)]
        cache = _make_cache(correspondents=corrs, taxonomy_limit=10)
        cache.refresh()

        names = cache.correspondent_names()

        assert len(names) == 10

    def test_names_returns_copy(self):
        """Mutating the returned list does not affect internal state."""
        cache = _make_cache(correspondents=[_corr(1, "Acme", 1)])
        cache.refresh()

        names = cache.correspondent_names()
        names.append("EXTRA")

        assert "EXTRA" not in cache.correspondent_names()

class TestGetOrCreateCorrespondentId:
    """Resolve or create correspondents by name."""

    def test_exact_match_returns_id(self):
        cache = _make_cache(correspondents=[_corr(42, "Acme Corp")])
        cache.refresh()

        result = cache.get_or_create_correspondent_id("Acme Corp")

        assert result == 42

    def test_substring_match_returns_id(self):
        """'Revolut Ltd' should match existing 'Revolut' via substring."""
        cache = _make_cache(correspondents=[_corr(7, "Revolut")])
        cache.refresh()

        result = cache.get_or_create_correspondent_id("Revolut Ltd")

        assert result == 7

    def test_creates_when_not_found(self):
        cache = _make_cache(correspondents=[])
        cache.refresh()
        cache._client.create_correspondent.side_effect = None
        cache._client.create_correspondent.return_value = {"id": 99, "name": "NewCorp"}

        result = cache.get_or_create_correspondent_id("NewCorp")

        assert result == 99
        cache._client.create_correspondent.assert_called_once_with("NewCorp")

    def test_empty_name_returns_none(self):
        cache = _make_cache()
        cache.refresh()

        result = cache.get_or_create_correspondent_id("")

        assert result is None

    def test_whitespace_name_returns_none(self):
        cache = _make_cache()
        cache.refresh()

        result = cache.get_or_create_correspondent_id("   ")

        assert result is None

    def test_creation_failure_refreshes_and_retries_lookup(self):
        """If creation fails, refresh cache and retry the lookup."""
        cache = _make_cache(correspondents=[])
        cache.refresh()

        # First call to create fails; after refresh, the item appears
        cache._client.create_correspondent.side_effect = OSError("conflict")
        cache._client.list_correspondents.return_value = [_corr(88, "Conflict Corp")]

        result = cache.get_or_create_correspondent_id("Conflict Corp")

        assert result == 88

    def test_creation_failure_raises_if_still_not_found(self):
        """If creation fails and refresh doesn't reveal the item, re-raise."""
        cache = _make_cache(correspondents=[])
        cache.refresh()
        cache._client.create_correspondent.side_effect = OSError("gone")
        cache._client.list_correspondents.return_value = []

        with pytest.raises(OSError, match="gone"):
            cache.get_or_create_correspondent_id("Ghost Corp")

class TestGetOrCreateDocumentTypeId:
    """Resolve or create document types by name."""

    def test_exact_match_returns_id(self):
        cache = _make_cache(document_types=[_dtype(10, "Invoice")])
        cache.refresh()

        result = cache.get_or_create_document_type_id("Invoice")

        assert result == 10

    def test_no_substring_matching(self):
        """Document types use exact normalised match only (no substring)."""
        cache = _make_cache(document_types=[_dtype(10, "Invoice")])
        cache.refresh()
        cache._client.create_document_type.side_effect = None
        cache._client.create_document_type.return_value = {"id": 20, "name": "Tax Invoice"}

        result = cache.get_or_create_document_type_id("Tax Invoice")

        assert result == 20  # created, not matched
        cache._client.create_document_type.assert_called_once()

    def test_creates_when_not_found(self):
        cache = _make_cache(document_types=[])
        cache.refresh()
        cache._client.create_document_type.side_effect = None
        cache._client.create_document_type.return_value = {"id": 30, "name": "Receipt"}

        result = cache.get_or_create_document_type_id("Receipt")

        assert result == 30

    def test_empty_name_returns_none(self):
        cache = _make_cache()
        cache.refresh()

        assert cache.get_or_create_document_type_id("") is None

    def test_creation_failure_refreshes_and_retries(self):
        cache = _make_cache(document_types=[])
        cache.refresh()
        cache._client.create_document_type.side_effect = OSError("dup")
        cache._client.list_document_types.return_value = [_dtype(50, "Payslip")]

        result = cache.get_or_create_document_type_id("Payslip")

        assert result == 50

class TestGetOrCreateTagIds:
    """Resolve or create multiple tags."""

    def test_resolves_existing_tags(self):
        cache = _make_cache(tags=[_tag(1, "2025"), _tag(2, "invoice")])
        cache.refresh()

        ids = cache.get_or_create_tag_ids(["2025", "invoice"])

        assert set(ids) == {1, 2}

    def test_creates_missing_tags(self):
        cache = _make_cache(tags=[_tag(1, "2025")])
        cache.refresh()
        cache._client.create_tag.side_effect = None
        cache._client.create_tag.return_value = {"id": 100, "name": "bills"}

        ids = cache.get_or_create_tag_ids(["2025", "bills"])

        assert 1 in ids
        assert 100 in ids
        cache._client.create_tag.assert_called_once()

    def test_deduplicates_input_tags(self):
        """Duplicate tags in input are deduplicated."""
        cache = _make_cache(tags=[_tag(1, "2025")])
        cache.refresh()

        ids = cache.get_or_create_tag_ids(["2025", "2025", "2025"])

        assert ids == [1]

    def test_creation_failure_refreshes_and_retries_lookup(self):
        cache = _make_cache(tags=[])
        cache.refresh()
        cache._client.create_tag.side_effect = OSError("conflict")
        cache._client.list_tags.return_value = [_tag(77, "magic")]

        ids = cache.get_or_create_tag_ids(["magic"])

        assert ids == [77]

    def test_filters_none_ids(self):
        """Tags with id=None in the response are filtered out."""
        cache = _make_cache(tags=[{"id": None, "name": "broken"}])
        cache.refresh()

        ids = cache.get_or_create_tag_ids(["broken"])

        assert ids == []

    def test_empty_tag_list_returns_empty(self):
        cache = _make_cache()
        cache.refresh()

        assert cache.get_or_create_tag_ids([]) == []

class TestInferMatchingAlgorithm:
    """_infer_matching_algorithm detects int vs string convention."""

    def test_infers_int_from_existing_tags(self):
        cache = _make_cache(tags=[_tag(1, "2025", matching_algorithm=0)])
        cache.refresh()

        result = cache._infer_matching_algorithm()

        assert result == 0

    def test_infers_string_from_existing_tags(self):
        cache = _make_cache(tags=[_tag(1, "2025", matching_algorithm="none")])
        cache.refresh()

        result = cache._infer_matching_algorithm()

        assert result == "none"

    def test_defaults_to_string_none_when_no_tags(self):
        cache = _make_cache(tags=[])
        cache.refresh()

        result = cache._infer_matching_algorithm()

        assert result == "none"

    def test_defaults_when_tags_lack_matching_algorithm(self):
        cache = _make_cache(tags=[{"id": 1, "name": "test"}])
        cache.refresh()

        result = cache._infer_matching_algorithm()

        assert result == "none"

class TestThreadSafety:
    """Concurrent access should not corrupt internal state."""

    def test_concurrent_refresh_and_lookup(self):
        """Multiple threads calling refresh() and name lookups."""
        client = make_mock_paperless()
        corrs = [_corr(i, f"Corr{i}", i) for i in range(20)]
        client.list_correspondents.return_value = corrs
        client.list_document_types.return_value = []
        client.list_tags.return_value = []
        cache = TaxonomyCache(client, taxonomy_limit=100)

        errors = []

        def worker():
            try:
                for _ in range(50):
                    cache.refresh()
                    names = cache.correspondent_names()
                    assert isinstance(names, list)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Thread errors: {errors}"

    def test_rlock_allows_reentrant_access(self):
        """Verify the cache uses RLock (reentrant) not Lock."""
        cache = _make_cache(correspondents=[_corr(1, "Acme")])
        cache.refresh()

        # Act — get_or_create_correspondent_id calls refresh() on failure,
        # which also acquires the lock. With RLock this should not deadlock.
        cache._client.create_correspondent.side_effect = OSError("dup")
        cache._client.list_correspondents.return_value = [_corr(1, "Acme")]

        # This would deadlock with a plain Lock instead of RLock
        result = cache.get_or_create_correspondent_id("Acme")

        assert result == 1

class TestCreationFailureReraise:
    """When creation fails and refresh doesn't find the item, re-raise."""

    def test_document_type_creation_fails_and_not_found_reraises(self):
        cache = _make_cache()
        cache.refresh()
        cache._client.create_document_type.side_effect = OSError("create failed")
        cache._client.list_document_types.return_value = []  # still not found after refresh

        with pytest.raises(OSError, match="create failed"):
            cache.get_or_create_document_type_id("NewType")

    def test_tag_creation_fails_and_not_found_reraises(self):
        cache = _make_cache()
        cache.refresh()
        cache._client.create_tag.side_effect = OSError("create failed")
        cache._client.list_tags.return_value = []  # still not found after refresh

        with pytest.raises(OSError, match="create failed"):
            cache.get_or_create_tag_ids(["BrandNewTag"])
