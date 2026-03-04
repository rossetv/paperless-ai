"""
Taxonomy Cache
==============

Thread-safe, in-memory cache for the Paperless-ngx taxonomy — correspondents,
document types, and tags.

The classification daemon refreshes this cache once per polling batch so the
LLM prompt always includes up-to-date vocabulary.  When the classifier
suggests a new item that does not exist yet, the cache creates it in Paperless
via the API and updates its internal indices, avoiding a full refresh.

The cache is intentionally **read-biased**: lookups are O(1) dict reads, while
writes (creation) happen at most a few times per batch.
"""

from __future__ import annotations

import threading
from typing import Iterable

import structlog

from common.paperless import PaperlessClient
from .normalizers import normalize_name, normalize_simple
from .tag_filters import dedupe_tags

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Indexing and matching helpers
# ---------------------------------------------------------------------------

def _index_items(items: list[dict], normalizer) -> dict[str, dict]:
    """
    Build a ``{normalized_name: item_dict}`` lookup from a Paperless listing.

    *normalizer* is typically :func:`normalize_simple` (for tags and document
    types) or :func:`normalize_name` (for correspondents).
    """
    mapping: dict[str, dict] = {}
    for item in items:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        mapping[normalizer(name)] = item
    return mapping


def _match_item(
    name: str,
    mapping: dict[str, dict],
    normalizer,
    allow_substring: bool,
) -> dict | None:
    """
    Find a Paperless item by normalized name, optionally allowing substrings.

    Substring matching is enabled for correspondents so that *"Revolut Ltd"*
    finds an existing *"Revolut"* entry.  Document types and tags use exact
    normalized matching only.
    """
    normalized = normalizer(name)
    if not normalized:
        return None
    matched = mapping.get(normalized)
    if matched:
        return matched
    if allow_substring:
        for key, item in mapping.items():
            if normalized in key or key in normalized:
                return item
    return None


def _get_usage_count(item: dict) -> int:
    """
    Return how many documents reference this taxonomy item.

    Paperless-ngx has used different field names across versions
    (``document_count``, ``documents_count``, ``documents``).  We try all
    known variants and return ``0`` when none are present.
    """
    for key in ("document_count", "documents_count", "documents"):
        if key not in item:
            continue
        value = item.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        if isinstance(value, list):
            return len(value)
    return 0


def _top_names(items: list[dict], limit: int) -> list[str]:
    """
    Return up to *limit* unique names sorted by usage count (descending).

    Used to build the prompt context lists so the LLM sees the most-used
    correspondents / types / tags first.
    """
    deduped: dict[str, dict] = {}
    for item in items:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        key = name.lower()
        if key not in deduped:
            deduped[key] = {"name": name, "count": _get_usage_count(item)}
        else:
            deduped[key]["count"] = max(deduped[key]["count"], _get_usage_count(item))

    sorted_items = sorted(
        deduped.values(),
        key=lambda entry: (-entry["count"], entry["name"].lower()),
    )
    if limit <= 0:
        return [entry["name"] for entry in sorted_items]
    return [entry["name"] for entry in sorted_items[:limit]]


# ---------------------------------------------------------------------------
# TaxonomyCache
# ---------------------------------------------------------------------------

class TaxonomyCache:
    """
    Thread-safe cache for Paperless correspondents, document types, and tags.

    **Usage**::

        cache = TaxonomyCache(paperless_client, taxonomy_limit=100)
        cache.refresh()                # initial load
        cache.correspondent_names()    # for prompt context
        cache.get_or_create_tag_ids(["Bills", "2025"])  # resolve / create
    """

    def __init__(self, paperless_client: PaperlessClient, taxonomy_limit: int):
        self._client = paperless_client
        self._taxonomy_limit = max(0, taxonomy_limit)
        self._lock = threading.RLock()
        self._correspondents: list[dict] = []
        self._document_types: list[dict] = []
        self._tags: list[dict] = []
        self._correspondent_map: dict[str, dict] = {}
        self._document_type_map: dict[str, dict] = {}
        self._tag_map: dict[str, dict] = {}
        # Cached sorted name lists — rebuilt during refresh().
        # Note: get_or_create_*() updates _*_map for lookups but does NOT
        # invalidate these caches; newly created items only appear after the
        # next refresh() call (i.e. at the start of the next polling batch).
        # This is acceptable because the cache is only used for LLM prompt
        # context, and the actual taxonomy resolution uses _*_map directly.
        self._cached_correspondent_names: list[str] = []
        self._cached_document_type_names: list[str] = []
        self._cached_tag_names: list[str] = []

    # ----- refresh -----

    def refresh(self) -> None:
        """Fetch the latest taxonomy lists from Paperless and rebuild indices."""
        with self._lock:
            self._correspondents = self._client.list_correspondents()
            self._document_types = self._client.list_document_types()
            self._tags = self._client.list_tags()
            self._correspondent_map = _index_items(self._correspondents, normalize_name)
            self._document_type_map = _index_items(self._document_types, normalize_simple)
            self._tag_map = _index_items(self._tags, normalize_simple)
            self._cached_correspondent_names = _top_names(
                self._correspondents, self._taxonomy_limit
            )
            self._cached_document_type_names = _top_names(
                self._document_types, self._taxonomy_limit
            )
            self._cached_tag_names = _top_names(self._tags, self._taxonomy_limit)

    # ----- prompt context -----

    def correspondent_names(self) -> list[str]:
        """Return correspondent names for the classification prompt."""
        with self._lock:
            return list(self._cached_correspondent_names)

    def document_type_names(self) -> list[str]:
        """Return document-type names for the classification prompt."""
        with self._lock:
            return list(self._cached_document_type_names)

    def tag_names(self) -> list[str]:
        """Return tag names for the classification prompt."""
        with self._lock:
            return list(self._cached_tag_names)

    # ----- resolve or create -----

    def get_or_create_correspondent_id(self, name: str) -> int | None:
        """
        Resolve an existing correspondent by name or create a new one.

        Uses :func:`normalize_name` (which strips company suffixes) and allows
        substring matching so *"Revolut Ltd"* finds *"Revolut"*.
        """
        if not name.strip():
            return None
        with self._lock:
            matched = _match_item(name, self._correspondent_map, normalize_name, True)
            if matched:
                return matched.get("id")
            try:
                created = self._client.create_correspondent(name.strip())
            except Exception:
                log.warning("Failed to create correspondent; refreshing cache", name=name)
                self.refresh()
                matched = _match_item(name, self._correspondent_map, normalize_name, True)
                if matched:
                    return matched.get("id")
                raise
            self._correspondents.append(created)
            self._correspondent_map[normalize_name(created.get("name", name))] = created
            return created.get("id")

    def get_or_create_document_type_id(self, name: str) -> int | None:
        """
        Resolve an existing document type by name or create a new one.

        Uses exact :func:`normalize_simple` matching (no substring).
        """
        if not name.strip():
            return None
        with self._lock:
            matched = _match_item(name, self._document_type_map, normalize_simple, False)
            if matched:
                return matched.get("id")
            try:
                created = self._client.create_document_type(name.strip())
            except Exception:
                log.warning("Failed to create document type; refreshing cache", name=name)
                self.refresh()
                matched = _match_item(name, self._document_type_map, normalize_simple, False)
                if matched:
                    return matched.get("id")
                raise
            self._document_types.append(created)
            self._document_type_map[normalize_simple(created.get("name", name))] = created
            return created.get("id")

    def get_or_create_tag_ids(self, tags: Iterable[str]) -> list[int]:
        """
        Resolve or create multiple tags, returning a list of Paperless tag IDs.

        The ``matching_algorithm`` for new tags is inferred from existing tags
        (int ``0`` vs string ``"none"``) so the new tag uses the same format.
        """
        matching_algorithm = self._infer_matching_algorithm()
        ids: list[int] = []
        for tag in dedupe_tags(tags):
            with self._lock:
                matched = _match_item(tag, self._tag_map, normalize_simple, False)
                if matched:
                    ids.append(matched.get("id"))
                    continue
                try:
                    created = self._client.create_tag(
                        tag.strip(), matching_algorithm=matching_algorithm
                    )
                except Exception:
                    log.warning("Failed to create tag; refreshing cache", name=tag)
                    self.refresh()
                    matching_algorithm = self._infer_matching_algorithm()
                    matched = _match_item(tag, self._tag_map, normalize_simple, False)
                    if matched:
                        ids.append(matched.get("id"))
                        continue
                    raise
                self._tags.append(created)
                self._tag_map[normalize_simple(created.get("name", tag))] = created
                ids.append(created.get("id"))
        return [tag_id for tag_id in ids if tag_id is not None]

    def _infer_matching_algorithm(self) -> int | str:
        """
        Inspect existing tags to decide whether ``matching_algorithm`` should
        be an int (``0``) or a string (``"none"``).

        Paperless-ngx changed the API representation between versions; by
        matching the existing convention we avoid ``400 Bad Request`` errors.
        """
        with self._lock:
            for tag in self._tags:
                value = tag.get("matching_algorithm")
                if isinstance(value, int):
                    return 0
                if isinstance(value, str):
                    return "none"
        return "none"
