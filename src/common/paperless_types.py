"""TypedDict wire shapes for the Paperless-ngx REST API.

The JSON the Paperless-ngx API returns and accepts, pinned as ``TypedDict``s
(CODE_GUIDELINES §5.3) so daemon code names fields and types instead of
indexing a bare ``dict``.  These describe the *foreign* wire shape; a daemon
translates them into domain dataclasses at its boundary.  :mod:`common.paperless`
re-exports every name here, so callers import from ``common.paperless`` and need
not know the shapes live in a sibling module — the split exists only to keep
``paperless.py`` under the file-size ceiling (CODE_GUIDELINES §3.1).
"""

from __future__ import annotations

from typing import NotRequired, TypedDict


# A single Paperless custom-field assignment on a document. Paperless returns
# and accepts custom fields as a list of these {field_id, value} pairs; pinning
# the shape (CODE_GUIDELINES §5.3) keeps the classifier off a bare ``dict``.
class PaperlessCustomField(TypedDict):
    """One ``{field, value}`` custom-field entry on a Paperless document.

    Attributes:
        field: The Paperless custom-field id.
        value: The field's value (Paperless stores custom-field values as
            strings for the field types this project sets).
    """

    field: int
    value: str


# TypedDict is used here because it maps directly to **kwargs with Unpack,
# giving callers keyword-level type checking while remaining a plain dict
# at runtime (no instantiation overhead, easy JSON serialisation).
class DocumentMetadataUpdate(TypedDict, total=False):
    """Keyword arguments accepted by :meth:`PaperlessClient.update_document_metadata`.

    Every value type except ``tags`` admits ``None``: the classifier passes
    ``None`` for a field it could not determine (no correspondent, no title),
    and :meth:`update_document_metadata` skips any ``None`` value rather than
    patching it. ``tags`` is always a concrete set — the classifier never has
    "no opinion" on tags, it computes the full replacement set every time.
    """

    title: str | None
    correspondent_id: int | None
    document_type_id: int | None
    document_date: str | None
    tags: set[int]
    language: str | None
    custom_fields: list[PaperlessCustomField] | None


# A read-side view of the Paperless-ngx document JSON shape (CODE_GUIDELINES
# §5.3): it pins the field names and types the indexer relies on without
# copying the whole foreign object into a dataclass.  ``id`` is the only field
# Paperless guarantees on every document; the rest are NotRequired because the
# indexer reads them defensively (a not-yet-OCR'd document has no ``content``,
# an un-dated document no ``created``).  A daemon translates this into a domain
# dataclass — ``store.models.DocumentMeta`` — at its boundary.
class PaperlessDocument(TypedDict):
    """The subset of the Paperless-ngx document JSON the indexer consumes.

    Attributes:
        id: The Paperless document id — always present.
        title: Human-readable title, or ``None`` if unset.
        content: The OCR content body; absent or ``None`` until the document
            has been transcribed.
        tags: Tag ids applied to the document.
        correspondent: The correspondent id, or ``None`` if unset.
        document_type: The document-type id, or ``None`` if unset.
        created: The document date (``"YYYY-MM-DD"`` or ISO-8601 datetime).
        modified: The last-modified timestamp; an ISO-8601 datetime.
        page_count: The number of pages, when Paperless reports it.
    """

    id: int
    title: NotRequired[str | None]
    content: NotRequired[str | None]
    tags: NotRequired[list[int]]
    correspondent: NotRequired[int | None]
    document_type: NotRequired[int | None]
    created: NotRequired[str | None]
    modified: NotRequired[str | None]
    page_count: NotRequired[int | None]


# A read-side view of a Paperless taxonomy item — a correspondent, document
# type, or tag (CODE_GUIDELINES §5.3). The list and create endpoints all return
# this shape; pinning it keeps the classifier's taxonomy code off a bare
# ``dict``. ``id`` and ``name`` are always present; the usage-count field name
# varies across Paperless-ngx versions (``document_count`` /
# ``documents_count`` / ``documents``), and ``matching_algorithm`` is an int on
# some versions and a string on others — the classifier reads all variants
# defensively, so they are NotRequired and union-typed.
class PaperlessItem(TypedDict):
    """A Paperless correspondent, document type, or tag, as returned by the API.

    Attributes:
        id: The Paperless item id — always present.
        name: The item's display name — always present.
        document_count: How many documents reference the item; the field name
            and value type vary by Paperless-ngx version.
        documents_count: An older-version alias of ``document_count``.
        documents: A still-older variant — the referencing document ids.
        matching_algorithm: The item's matching mode; an int or a string
            depending on the Paperless-ngx version.
    """

    id: int
    name: str
    document_count: NotRequired[int | str]
    documents_count: NotRequired[int | str]
    documents: NotRequired[list[int]]
    matching_algorithm: NotRequired[int | str]
