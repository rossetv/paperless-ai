"""TypedDict shapes of the JSON the Paperless-ngx REST API returns and accepts.

Re-exported by :mod:`common.paperless`.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict


class PaperlessCustomField(TypedDict):
    """One ``{field, value}`` custom-field entry on a Paperless document.

    ``value`` is a string for every field type this project sets.
    """

    field: int
    value: str


class DocumentMetadataUpdate(TypedDict, total=False):
    """Keyword arguments for :meth:`PaperlessClient.update_document_metadata`.

    An absent key leaves the field unchanged; ``None`` clears it. Exceptions:
    ``tags`` is never ``None`` (an empty set clears all tags), and a ``None``
    ``custom_fields`` or ``document_date`` leaves the field unchanged because
    Paperless rejects null for them.

    ``notes`` replaces every existing note with the new text; an empty string
    leaves the document with no notes.
    """

    title: str | None
    correspondent_id: int | None
    document_type_id: int | None
    document_date: str | None
    tags: set[int]
    language: str | None
    custom_fields: list[PaperlessCustomField] | None
    notes: str | None
    archive_serial_number: int | None


class PaperlessDocument(TypedDict):
    """The subset of the Paperless-ngx document JSON the indexer reads.

    Only ``id`` is guaranteed; the rest may be missing (an un-OCR'd document has
    no ``content``, and a light listing asks for only some fields). ``created``
    is ``"YYYY-MM-DD"`` or an ISO-8601 datetime.
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


class PaperlessItem(TypedDict):
    """A Paperless correspondent, document type or tag, as the API returns it.

    The usage-count field differs across Paperless-ngx versions
    (``document_count``, ``documents_count``, or a ``documents`` id list), and
    ``matching_algorithm`` is an int on some versions and a string on others.
    """

    id: int
    name: str
    document_count: NotRequired[int | str]
    documents_count: NotRequired[int | str]
    documents: NotRequired[list[int]]
    matching_algorithm: NotRequired[int | str]
