"""Thread-safe cache for Paperless-ngx correspondents, document types, and tags."""

from __future__ import annotations

import threading
from typing import Callable, Iterable, NamedTuple

import structlog

from common.paperless import PAPERLESS_CALL_EXCEPTIONS, PaperlessClient
from .normalizers import normalize_name, normalize_simple
from .tag_filters import dedupe_tags

log = structlog.get_logger(__name__)


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


class _TaxonomyKind(NamedTuple):
    """Bundles the per-kind data needed by _get_or_create_item_id."""

    items: list[dict]
    mapping: dict[str, dict]
    normalizer: Callable[[str], str]
    allow_substring: bool
    creator: Callable[[str], dict]
    label: str


class TaxonomyCache:
    """Thread-safe cache for Paperless taxonomy lookups and creation."""

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
        self._cached_correspondent_names: list[str] = []
        self._cached_document_type_names: list[str] = []
        self._cached_tag_names: list[str] = []

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

    def _correspondent_kind(self) -> _TaxonomyKind:
        return _TaxonomyKind(
            self._correspondents, self._correspondent_map, normalize_name,
            True, self._client.create_correspondent, "correspondent",
        )

    def _document_type_kind(self) -> _TaxonomyKind:
        return _TaxonomyKind(
            self._document_types, self._document_type_map, normalize_simple,
            False, self._client.create_document_type, "document type",
        )

    def _get_or_create_item_id(
        self, name: str, kind_factory: Callable[[], _TaxonomyKind],
    ) -> int | None:
        """Look up an item by name, creating it if necessary."""
        if not name.strip():
            return None
        with self._lock:
            kind = kind_factory()
            matched = _match_item(name, kind.mapping, kind.normalizer, kind.allow_substring)
            if matched:
                return matched.get("id")
            try:
                created = kind.creator(name.strip())
            except PAPERLESS_CALL_EXCEPTIONS:
                log.warning(
                    "Failed to create item; refreshing cache",
                    item_label=kind.label,
                    name=name,
                )
                self.refresh()
                kind = kind_factory()
                matched = _match_item(
                    name, kind.mapping, kind.normalizer, kind.allow_substring,
                )
                if matched:
                    return matched.get("id")
                raise
            kind.items.append(created)
            kind.mapping[kind.normalizer(created.get("name", name))] = created
            return created.get("id")

    def get_or_create_correspondent_id(self, name: str) -> int | None:
        return self._get_or_create_item_id(name, self._correspondent_kind)

    def get_or_create_document_type_id(self, name: str) -> int | None:
        return self._get_or_create_item_id(name, self._document_type_kind)

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
                except PAPERLESS_CALL_EXCEPTIONS:
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
