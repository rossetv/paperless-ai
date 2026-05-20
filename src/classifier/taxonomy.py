"""Thread-safe cache for Paperless-ngx correspondents, document types, and tags."""

from __future__ import annotations

import dataclasses
import threading
from typing import Callable, Iterable, NamedTuple

import structlog

from common.paperless import PAPERLESS_CALL_EXCEPTIONS, PaperlessClient, PaperlessItem
from .normalisers import normalise_name, normalise_simple
from .tag_filters import dedupe_tags

log = structlog.get_logger(__name__)


# frozen dataclass: chosen over NamedTuple because this is part of the public
# API (passed to classification providers), benefits from keyword-only
# construction for clarity, and may gain optional fields in the future.
@dataclasses.dataclass(frozen=True, slots=True)
class TaxonomyContext:
    """Snapshot of taxonomy name lists used as LLM prompt context.

    Groups the three taxonomy lists that are always passed together to
    the classification provider, reducing parameter count.
    """

    correspondents: list[str]
    document_types: list[str]
    tags: list[str]


def _index_items(
    items: list[PaperlessItem], normaliser: Callable[[str], str]
) -> dict[str, PaperlessItem]:
    """
    Build a ``{normalised_name: item}`` lookup from a Paperless listing.

    *normaliser* is typically :func:`normalise_simple` (for tags and document
    types) or :func:`normalise_name` (for correspondents).
    """
    mapping: dict[str, PaperlessItem] = {}
    for item in items:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        mapping[normaliser(name)] = item
    return mapping


def _match_item(
    name: str,
    mapping: dict[str, PaperlessItem],
    normaliser: Callable[[str], str],
    allow_substring: bool,
) -> PaperlessItem | None:
    """
    Find a Paperless item by normalised name, optionally allowing substrings.

    Substring matching is enabled for correspondents so that *"Revolut Ltd"*
    finds an existing *"Revolut"* entry.  Document types and tags use exact
    normalised matching only.
    """
    normalised = normaliser(name)
    if not normalised:
        return None
    matched = mapping.get(normalised)
    if matched:
        return matched
    if allow_substring:
        for key, item in mapping.items():
            if normalised in key or key in normalised:
                return item
    return None


def _get_usage_count(item: PaperlessItem) -> int:
    """
    Return how many documents reference this taxonomy item.

    Paperless-ngx has used different field names across versions
    (``document_count``, ``documents_count``, ``documents``).  We try all
    known variants and return ``0`` when none are present.
    """
    for key in ("document_count", "documents_count", "documents"):
        if key not in item:
            continue
        value = item[key]  # type: ignore[literal-required]
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        if isinstance(value, list):
            return len(value)
    return 0


class _RankedName(NamedTuple):
    """A taxonomy name paired with its usage count, for usage-ordered ranking."""

    name: str
    usage: int


def _top_names(items: list[PaperlessItem], limit: int) -> list[str]:
    """
    Return up to *limit* unique names sorted by usage count (descending).

    Used to build the prompt context lists so the LLM sees the most-used
    correspondents / types / tags first.
    """
    deduped: dict[str, _RankedName] = {}
    for item in items:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        key = name.lower()
        usage = _get_usage_count(item)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = _RankedName(name, usage)
        elif usage > existing.usage:
            deduped[key] = _RankedName(existing.name, usage)

    ranked = sorted(
        deduped.values(),
        key=lambda entry: (-entry.usage, entry.name.lower()),
    )
    if limit <= 0:
        return [entry.name for entry in ranked]
    return [entry.name for entry in ranked[:limit]]


# NamedTuple: lightweight immutable record used as a short-lived internal
# grouping of per-kind parameters (items list, lookup map, normaliser, etc.)
# passed between private methods.  NamedTuple is preferred over dataclass here
# because the value is created frequently, never mutated, and benefits from
# tuple unpacking and minimal memory footprint.
class _TaxonomyKind(NamedTuple):
    """Bundles the per-kind data needed by _get_or_create_item_id."""

    items: list[PaperlessItem]
    mapping: dict[str, PaperlessItem]
    normaliser: Callable[[str], str]
    allow_substring: bool
    creator: Callable[[str], PaperlessItem]
    label: str


class TaxonomyCache:
    """Thread-safe cache for Paperless taxonomy lookups and creation."""

    def __init__(self, paperless_client: PaperlessClient, taxonomy_limit: int):
        self._client = paperless_client
        self._taxonomy_limit = max(0, taxonomy_limit)
        self._lock = threading.RLock()
        self._correspondents: list[PaperlessItem] = []
        self._document_types: list[PaperlessItem] = []
        self._tags: list[PaperlessItem] = []
        self._correspondent_map: dict[str, PaperlessItem] = {}
        self._document_type_map: dict[str, PaperlessItem] = {}
        self._tag_map: dict[str, PaperlessItem] = {}
        self._cached_correspondent_names: list[str] = []
        self._cached_document_type_names: list[str] = []
        self._cached_tag_names: list[str] = []

    def refresh(self) -> None:
        """Fetch the latest taxonomy lists from Paperless and rebuild indices."""
        with self._lock:
            self._correspondents = self._client.list_correspondents()
            self._document_types = self._client.list_document_types()
            self._tags = self._client.list_tags()
            self._correspondent_map = _index_items(self._correspondents, normalise_name)
            self._document_type_map = _index_items(self._document_types, normalise_simple)
            self._tag_map = _index_items(self._tags, normalise_simple)
            self._cached_correspondent_names = _top_names(
                self._correspondents, self._taxonomy_limit
            )
            self._cached_document_type_names = _top_names(
                self._document_types, self._taxonomy_limit
            )
            self._cached_tag_names = _top_names(self._tags, self._taxonomy_limit)

    def taxonomy_context(self) -> TaxonomyContext:
        """Return a frozen snapshot of taxonomy names for the LLM prompt."""
        with self._lock:
            return TaxonomyContext(
                correspondents=list(self._cached_correspondent_names),
                document_types=list(self._cached_document_type_names),
                tags=list(self._cached_tag_names),
            )

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
            self._correspondents, self._correspondent_map, normalise_name,
            True, self._client.create_correspondent, "correspondent",
        )

    def _document_type_kind(self) -> _TaxonomyKind:
        return _TaxonomyKind(
            self._document_types, self._document_type_map, normalise_simple,
            False, self._client.create_document_type, "document type",
        )

    def _tag_kind(self) -> _TaxonomyKind:
        matching_algorithm = self._infer_matching_algorithm()

        def create_tag(name: str) -> PaperlessItem:
            return self._client.create_tag(name, matching_algorithm=matching_algorithm)

        return _TaxonomyKind(
            self._tags, self._tag_map, normalise_simple,
            False, create_tag, "tag",
        )

    @staticmethod
    def _extract_id(item: PaperlessItem) -> int | None:
        """Extract and validate the ``id`` field from a Paperless API item.

        The ``isinstance`` guard is deliberate: :class:`PaperlessItem` pins the
        expected shape, but a malformed upstream row can carry a non-int ``id``
        — that row yields ``None`` rather than a bad id (CODE_GUIDELINES §1.11).
        """
        value = item.get("id")
        return value if isinstance(value, int) else None

    def _get_or_create_item_id(
        self, name: str, kind_factory: Callable[[], _TaxonomyKind],
    ) -> int | None:
        """Look up an item by name, creating it if necessary."""
        if not name.strip():
            return None
        with self._lock:
            kind = kind_factory()
            matched = _match_item(name, kind.mapping, kind.normaliser, kind.allow_substring)
            if matched:
                return self._extract_id(matched)
            try:
                created = kind.creator(name.strip())
            except PAPERLESS_CALL_EXCEPTIONS:
                log.warning(
                    "Failed to create item; refreshing cache",
                    item_label=kind.label,
                    name=name,
                )
                try:
                    self.refresh()
                except PAPERLESS_CALL_EXCEPTIONS:
                    log.warning("Cache refresh also failed", item_label=kind.label)
                    raise
                kind = kind_factory()
                matched = _match_item(
                    name, kind.mapping, kind.normaliser, kind.allow_substring,
                )
                if matched:
                    return self._extract_id(matched)
                raise
            kind.items.append(created)
            kind.mapping[kind.normaliser(str(created.get("name", name)))] = created
            return self._extract_id(created)

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
        ids: list[int] = []
        for tag in dedupe_tags(tags):
            tag_id = self._get_or_create_item_id(tag, self._tag_kind)
            if tag_id is not None:
                ids.append(tag_id)
        return ids

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
