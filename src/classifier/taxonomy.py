"""Thread-safe cache for Paperless-ngx correspondents, document types, and tags."""

from __future__ import annotations

import dataclasses
import threading
from typing import Callable, Iterable, NamedTuple

import structlog

from common.paperless import PAPERLESS_CALL_EXCEPTIONS, PaperlessClient, PaperlessItem
from .normalisers import name_words, normalise_name, normalise_simple
from .tag_filters import dedupe_tags

log = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class TaxonomyContext:
    """Snapshot of taxonomy name lists used as LLM prompt context."""

    correspondents: list[str]
    document_types: list[str]
    tags: list[str]


def _index_items(
    items: list[PaperlessItem], normaliser: Callable[[str], str]
) -> dict[str, PaperlessItem]:
    """Build a ``{normalised_name: item}`` lookup from a Paperless listing."""
    mapping: dict[str, PaperlessItem] = {}
    for item in items:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        key = normaliser(name)
        if not key:
            # The normaliser stripped every token (a correspondent named "AS"
            # or "Ltd"); store under the raw lowercase name for _match_item.
            mapping[name.lower()] = item
        else:
            mapping[key] = item
    return mapping


def _index_words(mapping: dict[str, PaperlessItem]) -> dict[str, str]:
    """Build a ``{key: name_words}`` lookup so a miss need not re-fold every name."""
    return {key: name_words(str(item.get("name", ""))) for key, item in mapping.items()}


def _match_item(
    name: str,
    mapping: dict[str, PaperlessItem],
    normaliser: Callable[[str], str],
    allow_substring: bool,
    words: dict[str, str] | None = None,
) -> PaperlessItem | None:
    """Find a Paperless item by normalised name, optionally allowing substrings.

    Substring matching lets a *"Neon"* correspondent find *"Neon Energy"*; it
    compares whole words only, so *"Eon"* does not. Words are compared both
    with punctuation removed (*"E.ON"* is *"eon"*) and with punctuation as a
    word break (*"Amazon.co.uk"* holds *"amazon"*). *words* holds each key's
    stored word form; without it the forms are computed per call.
    """
    normalised = normaliser(name)
    if not normalised:
        # A name made only of a suffix ("AS", "Ltd") normalises to "". Match it
        # on the raw lowercase name, or it would be re-created on every poll.
        lower = name.strip().lower()
        if not lower:
            return None
        return mapping.get(lower)
    matched = mapping.get(normalised)
    if matched:
        return matched
    if allow_substring:
        wanted = {normalised, name_words(name)}
        for key, item in mapping.items():
            folded = (
                words[key]
                if words is not None and key in words
                else name_words(str(item.get("name", "")))
            )
            have = {key, folded}
            if any(_contains_words(a, b) for a in wanted for b in have if a and b):
                return item
    return None


def _contains_words(a: str, b: str) -> bool:
    """Whether either string holds the other as a run of whole words."""
    padded_a, padded_b = f" {a} ", f" {b} "
    return padded_a in padded_b or padded_b in padded_a


def _get_usage_count(item: PaperlessItem) -> int:
    """Return how many documents reference this taxonomy item.

    The field name differs across Paperless-ngx versions, so all known ones are
    tried.
    """
    for key in ("document_count", "documents_count", "documents"):
        if key not in item:
            continue
        # mypy cannot prove a runtime str is one of the TypedDict's literal keys.
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
    """Return up to *limit* unique names, most-used first (all if *limit* <= 0)."""
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
            deduped[key] = _RankedName(name, usage)

    ranked = sorted(
        deduped.values(),
        key=lambda entry: (-entry.usage, entry.name.lower()),
    )
    if limit <= 0:
        return [entry.name for entry in ranked]
    return [entry.name for entry in ranked[:limit]]


class _TaxonomyKind(NamedTuple):
    """Bundles the per-kind data needed by _get_or_create_item_id."""

    items: list[PaperlessItem]
    mapping: dict[str, PaperlessItem]
    words: dict[str, str]
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
        self._correspondent_words: dict[str, str] = {}
        self._document_type_words: dict[str, str] = {}
        self._tag_words: dict[str, str] = {}
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
            self._document_type_map = _index_items(
                self._document_types, normalise_simple
            )
            self._tag_map = _index_items(self._tags, normalise_simple)
            self._correspondent_words = _index_words(self._correspondent_map)
            self._document_type_words = {}
            self._tag_words = {}
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

    def _correspondent_kind(self) -> _TaxonomyKind:
        return _TaxonomyKind(
            self._correspondents,
            self._correspondent_map,
            self._correspondent_words,
            normalise_name,
            True,
            self._client.create_correspondent,
            "correspondent",
        )

    def _document_type_kind(self) -> _TaxonomyKind:
        return _TaxonomyKind(
            self._document_types,
            self._document_type_map,
            self._document_type_words,
            normalise_simple,
            False,
            self._client.create_document_type,
            "document type",
        )

    def _tag_kind(self) -> _TaxonomyKind:
        matching_algorithm = self._infer_matching_algorithm()

        def create_tag(name: str) -> PaperlessItem:
            return self._client.create_tag(name, matching_algorithm=matching_algorithm)

        return _TaxonomyKind(
            self._tags,
            self._tag_map,
            self._tag_words,
            normalise_simple,
            False,
            create_tag,
            "tag",
        )

    @staticmethod
    def _extract_id(item: PaperlessItem) -> int | None:
        """Return the item's ``id``, or ``None`` if a malformed row has a non-int."""
        value = item.get("id")
        return value if isinstance(value, int) else None

    def _get_or_create_item_id(
        self,
        name: str,
        kind_factory: Callable[[], _TaxonomyKind],
    ) -> int | None:
        """Look up an item by name, creating it in Paperless if necessary.

        The lock is released around the HTTP create so other workers are not
        serialised behind a slow Paperless call; the mapping is re-checked
        afterwards in case another thread created the same item meanwhile.
        """
        if not name.strip():
            return None

        with self._lock:
            kind = kind_factory()
            matched = _match_item(
                name,
                kind.mapping,
                kind.normaliser,
                kind.allow_substring,
                kind.words,
            )
            if matched:
                return self._extract_id(matched)
            creator = kind.creator
            label = kind.label

        try:
            created = creator(name.strip())
        except PAPERLESS_CALL_EXCEPTIONS:
            log.exception(
                "Failed to create item; refreshing cache",
                item_label=label,
                name=name,
            )
            try:
                self.refresh()
            except PAPERLESS_CALL_EXCEPTIONS:
                log.exception("Cache refresh also failed", item_label=label)
                raise
            with self._lock:
                kind = kind_factory()
                matched = _match_item(
                    name,
                    kind.mapping,
                    kind.normaliser,
                    kind.allow_substring,
                    kind.words,
                )
                if matched:
                    return self._extract_id(matched)
            raise

        with self._lock:
            kind = kind_factory()
            matched = _match_item(
                name,
                kind.mapping,
                kind.normaliser,
                kind.allow_substring,
                kind.words,
            )
            if matched:
                # Another thread created it first; discard ours.
                return self._extract_id(matched)
            created_name = str(created.get("name", name))
            key = kind.normaliser(created_name)
            if not key:
                # Suffix-only name like "AS"; see _index_items.
                key = created_name.strip().lower()
            if key:
                kind.mapping[key] = created
                if kind.allow_substring:
                    kind.words[key] = name_words(str(created.get("name", "")))
            kind.items.append(created)
            return self._extract_id(created)

    def get_or_create_correspondent_id(self, name: str) -> int | None:
        return self._get_or_create_item_id(name, self._correspondent_kind)

    def get_or_create_document_type_id(self, name: str) -> int | None:
        return self._get_or_create_item_id(name, self._document_type_kind)

    def get_or_create_tag_ids(self, tags: Iterable[str]) -> list[int]:
        """Resolve or create *tags*, returning their Paperless tag ids."""
        ids: list[int] = []
        for tag in dedupe_tags(tags):
            tag_id = self._get_or_create_item_id(tag, self._tag_kind)
            if tag_id is not None:
                ids.append(tag_id)
        return ids

    def tag_name(self, tag_id: int) -> str | None:
        """Return the cached name of tag *tag_id*, or ``None`` if it is not cached."""
        with self._lock:
            for tag in self._tags:
                if self._extract_id(tag) == tag_id:
                    return str(tag.get("name", "")).strip() or None
        return None

    def _infer_matching_algorithm(self) -> int | str:
        """Return ``0`` or ``"none"`` for new tags' ``matching_algorithm``.

        Paperless-ngx changed the representation between versions; matching the
        existing tags' form avoids a 400.
        """
        with self._lock:
            for tag in self._tags:
                value = tag.get("matching_algorithm")
                if isinstance(value, int):
                    return 0
                if isinstance(value, str):
                    return "none"
        return "none"
