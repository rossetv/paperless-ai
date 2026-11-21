"""Paperless-ngx REST API client with automatic retries."""

from __future__ import annotations

import types
from collections.abc import Iterator, Sequence
from typing import Any, Generator, Iterable, Unpack, cast

import httpx
import structlog

from .config import Settings
from .paperless_types import (
    DocumentMetadataUpdate,
    PaperlessCustomField,
    PaperlessDocument,
    PaperlessItem,
)
from .retry import retry

# The wire-shape TypedDicts live in ``common.paperless_types`` and are
# re-exported here so callers can import everything from ``common.paperless``.
__all__ = [
    "DocumentMetadataUpdate",
    "PAPERLESS_CALL_EXCEPTIONS",
    "PaperlessClient",
    "PaperlessCustomField",
    "PaperlessDocument",
    "PaperlessItem",
    "RETRYABLE_HTTP_EXCEPTIONS",
    "RETRYABLE_POST_EXCEPTIONS",
    "is_permanent_paperless_error",
]

log = structlog.get_logger(__name__)

# Retried for the idempotent verbs (GET, PATCH, DELETE): network errors and the
# 5xx HTTPStatusError raised by _raise_for_status_if_server_error.
RETRYABLE_HTTP_EXCEPTIONS = (httpx.RequestError, httpx.HTTPStatusError)

# A POST is not idempotent (re-sending ``add_note`` duplicates the note), so it
# retries only when the request provably was not applied: a failed or timed-out
# connect, or a 5xx. ReadTimeout and RemoteProtocolError are excluded because
# the server may already have applied the write.
RETRYABLE_POST_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.HTTPStatusError,
)

# What callers catch to treat a PaperlessClient failure as non-fatal: network
# errors, HTTP errors and unexpected response shapes.
PAPERLESS_CALL_EXCEPTIONS = (OSError, httpx.HTTPError, ValueError, KeyError)


def is_permanent_paperless_error(exc: BaseException) -> bool:
    """True when *exc* is a Paperless 4xx that will fail the same way on retry.

    Callers quarantine the document on a permanent error instead of re-running
    LLM work that has already spent tokens. 408 and 429 are excluded because
    they are transient (e.g. from a proxy in front of Paperless).
    """
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and 400 <= exc.response.status_code < 500
        and exc.response.status_code not in (408, 429)
    )


def _named_item_payload(
    name: str, matching_algorithm: str | int | None
) -> dict[str, str | int]:
    """Build the create-payload for a named item, omitting a ``None`` algorithm."""
    payload: dict[str, str | int] = {"name": name}
    if matching_algorithm is not None:
        payload["matching_algorithm"] = matching_algorithm
    return payload


class PaperlessClient:
    """Paperless-ngx REST client handling auth, retries, pagination and timeouts.

    Not thread-safe (the ``httpx`` session is not): each worker thread builds
    its own client.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.Client(
            headers={"Authorization": f"Token {self.settings.PAPERLESS_TOKEN}"},
            timeout=self.settings.REQUEST_TIMEOUT,
            follow_redirects=True,
        )

    def _raise_for_status_if_server_error(self, response: httpx.Response) -> None:
        """Raise on 5xx so the ``@retry`` decorator can retry the request.

        Only server errors are retried; 4xx errors are left for the caller's
        ``raise_for_status()`` to handle without retry.
        """
        if response.status_code >= 500:
            response.raise_for_status()

    def _raise_for_status_logging_body(
        self, response: httpx.Response, *, doc_id: int, payload_keys: list[str]
    ) -> None:
        """``raise_for_status`` that first logs the response body on an error.

        ``HTTPStatusError`` omits the body, which is where Paperless says which
        field it rejected (e.g. ``{"tags": ["Invalid pk 47 - ..."]}``).
        """
        if response.is_success:
            return
        try:
            body: object = response.json()
        except ValueError:
            body = response.text
        log.error(
            "Paperless rejected document write",
            doc_id=doc_id,
            status_code=response.status_code,
            payload_keys=payload_keys,
            response_body=body,
        )
        response.raise_for_status()

    # **kwargs pass straight through to httpx, which types them loosely too.
    @retry(retryable_exceptions=RETRYABLE_HTTP_EXCEPTIONS)
    def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        response = self._client.get(url, **kwargs)
        self._raise_for_status_if_server_error(response)
        return response

    @retry(retryable_exceptions=RETRYABLE_HTTP_EXCEPTIONS)
    def _patch(self, url: str, **kwargs: Any) -> httpx.Response:
        response = self._client.patch(url, **kwargs)
        self._raise_for_status_if_server_error(response)
        return response

    # POST uses the narrower retry set; see RETRYABLE_POST_EXCEPTIONS.
    @retry(retryable_exceptions=RETRYABLE_POST_EXCEPTIONS)
    def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        response = self._client.post(url, **kwargs)
        self._raise_for_status_if_server_error(response)
        return response

    @retry(retryable_exceptions=RETRYABLE_HTTP_EXCEPTIONS)
    def _delete(self, url: str, **kwargs: Any) -> httpx.Response:
        response = self._client.delete(url, **kwargs)
        self._raise_for_status_if_server_error(response)
        return response

    def _list_all(self, url: str) -> Generator[dict, None, None]:
        while url:
            response = self._get(url)
            response.raise_for_status()
            page = response.json()
            yield from page.get("results", [])
            url = page.get("next")

    def _create_named_item(
        self,
        *,
        url: str,
        name: str,
        matching_algorithm: str | int | None,
        item_label: str,
    ) -> dict[str, object]:
        """Create a named item, retrying other ``matching_algorithm`` forms on 400.

        Paperless rejects a ``matching_algorithm`` of the wrong type (string or
        int) with a 400, so the other form is tried. Returns the decoded body.
        """
        log.info(
            "paperless.item_creating",
            item_label=item_label,
            name=name,
            matching_algorithm=matching_algorithm,
        )

        candidates: list[str | int | None]
        if matching_algorithm is None:
            candidates = [None]
        elif isinstance(matching_algorithm, str):
            candidates = [matching_algorithm, 0]
        else:
            candidates = [matching_algorithm, "none"]

        # A 400 on any but the last candidate means "try the next one".
        for candidate in candidates[:-1]:
            body = self._post_named_item(url, name, candidate)
            if body is not None:
                return body

        return self._post_final_named_item(url, name, candidates[-1])

    def _post_final_named_item(
        self, url: str, name: str, matching_algorithm: str | int | None
    ) -> dict[str, object]:
        """POST the last named-item candidate; any HTTP error propagates."""
        response = self._post(url, json=_named_item_payload(name, matching_algorithm))
        response.raise_for_status()
        decoded: dict[str, object] = response.json()
        return decoded

    def _post_named_item(
        self, url: str, name: str, matching_algorithm: str | int | None
    ) -> dict[str, object] | None:
        """POST one non-final named-item candidate; ``None`` on a 400."""
        response = self._post(url, json=_named_item_payload(name, matching_algorithm))
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            if response.status_code == 400:
                return None
            raise
        decoded: dict[str, object] = response.json()
        return decoded

    def get_documents_by_tag(self, tag_id: int) -> Iterable[dict]:
        url = (
            f"{self.settings.PAPERLESS_URL}/api/documents/"
            f"?tags__id={tag_id}"
            "&page_size=100"
        )
        yield from self._list_all(url)

    def get_document(self, doc_id: int) -> dict[str, Any]:
        """Fetch one document's raw Paperless JSON.

        A 404 raises like any other error; use :meth:`document_exists` to test
        for existence.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/"
        response = self._get(url)
        response.raise_for_status()
        decoded: dict[str, Any] = response.json()
        return decoded

    def download_content(self, doc_id: int) -> tuple[bytes, str]:
        """Download raw file bytes and content type for a document."""
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/download/"
        response = self._get(url)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "application/pdf")
        return response.content, content_type

    def download_original(self, doc_id: int) -> tuple[bytes, str]:
        """Download the original file (not the archived copy) and its content type.

        The born-digital check needs the original: Paperless's archived copy of a
        scan carries a Tesseract text layer, so it would look born-digital.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/download/?original=true"
        response = self._get(url)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "application/pdf")
        return response.content, content_type

    def download_stream(self, doc_id: int) -> tuple[str, Iterator[bytes]]:
        """Stream a document's file without buffering it, for the PDF viewer.

        Returns the content type and a body iterator; see :meth:`_stream_endpoint`.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/download/"
        return self._stream_endpoint(url, default_content_type="application/pdf")

    def _stream_endpoint(
        self, url: str, *, default_content_type: str
    ) -> tuple[str, Iterator[bytes]]:
        """Open *url* as one streaming response; return (content_type, body).

        A non-2xx status raises before returning, with the response closed.
        The iterator owns the open response and closes it when drained, closed
        or failed, so the caller must drain or close it. Not retried: a
        partly consumed stream cannot be replayed.
        """
        request = self._client.build_request("GET", url)
        response = self._client.send(request, stream=True)
        try:
            response.raise_for_status()
        except httpx.HTTPError:
            response.close()
            raise
        content_type = response.headers.get("Content-Type", default_content_type)

        def _iter_body() -> Iterator[bytes]:
            """Yield the open response's body, closing it however iteration ends."""
            try:
                yield from response.iter_bytes()
            finally:
                response.close()

        return content_type, _iter_body()

    def thumb_stream(self, doc_id: int) -> tuple[str, Iterator[bytes]]:
        """Stream a document's first-page thumbnail (WebP or JPEG).

        Same contract as :meth:`download_stream`.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/thumb/"
        return self._stream_endpoint(url, default_content_type="image/jpeg")

    def update_document(
        self, doc_id: int, content: str, new_tags: Iterable[int]
    ) -> None:
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/"
        tags_list = list(new_tags)
        log.info(
            "paperless.document_updating",
            doc_id=doc_id,
            new_tags=tags_list,
            content_len=len(content),
        )
        payload = {"content": content, "tags": tags_list}
        response = self._patch(url, json=payload)
        self._raise_for_status_logging_body(
            response, doc_id=doc_id, payload_keys=list(payload)
        )
        log.info("paperless.document_updated", doc_id=doc_id)

    # DocumentMetadataUpdate key -> Paperless API field. ``notes`` is absent
    # because it goes through the separate notes endpoint.
    _METADATA_FIELDS = types.MappingProxyType(
        {
            "title": "title",
            "correspondent_id": "correspondent",
            "document_type_id": "document_type",
            "document_date": "created",
            "tags": "tags",
            "language": "language",
            "custom_fields": "custom_fields",
            "archive_serial_number": "archive_serial_number",
        }
    )

    # Fields Paperless rejects as null; for these None means "leave unchanged".
    _NON_NULLABLE_FIELDS = frozenset({"custom_fields", "document_date"})

    def update_document_metadata(
        self,
        doc_id: int,
        **kwargs: Unpack[DocumentMetadataUpdate],
    ) -> None:
        """Update document metadata fields on Paperless.

        Absent keys are left unchanged. ``None`` clears a field, except for
        :attr:`_NON_NULLABLE_FIELDS`, where it leaves the field unchanged.

        ``notes`` replaces the document's notes; an empty string removes them.
        """
        if "notes" in kwargs:
            notes_text = kwargs.pop("notes")  # type: ignore[misc]
            # Add before delete: a failure part-way leaves a stale duplicate
            # rather than losing the notes. The ids are taken before the add so
            # the new note is not deleted.
            existing = self.list_notes(doc_id)
            existing_ids = [note["id"] for note in existing]
            if notes_text is not None and notes_text != "":
                self.add_note(doc_id, notes_text)
            for note_id in existing_ids:
                self.delete_note(doc_id, note_id)

        payload: dict[str, object] = {}
        for key, api_field in self._METADATA_FIELDS.items():
            # TypedDict access needs a Literal key; `key` is a plain str here.
            if key not in kwargs:  # type: ignore[literal-required]
                continue
            value = kwargs[key]  # type: ignore[literal-required]
            if key in self._NON_NULLABLE_FIELDS and value is None:
                # Paperless 400s on null here: custom_fields clear with an empty
                # list, and a document always has a created date. The classifier
                # sends None when it found no date, meaning "keep the old one".
                continue
            if key == "tags" and value is not None:
                # mypy cannot narrow the TypedDict value union by key.
                value = list(value)  # type: ignore[call-overload]
            payload[api_field] = value

        if not payload:
            log.info("paperless.metadata_noop", doc_id=doc_id)
            return

        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/"
        log.info(
            "paperless.metadata_updating", doc_id=doc_id, payload_keys=list(payload)
        )
        response = self._patch(url, json=payload)
        self._raise_for_status_logging_body(
            response, doc_id=doc_id, payload_keys=list(payload)
        )
        log.info("paperless.metadata_updated", doc_id=doc_id)

    def _list_named_items(self, url: str) -> list[PaperlessItem]:
        """List a correspondent, document-type or tag endpoint as items."""
        return [cast("PaperlessItem", item) for item in self._list_all(url)]

    def list_correspondents(self) -> list[PaperlessItem]:
        url = f"{self.settings.PAPERLESS_URL}/api/correspondents/?page_size=100"
        return self._list_named_items(url)

    def list_document_types(self) -> list[PaperlessItem]:
        url = f"{self.settings.PAPERLESS_URL}/api/document_types/?page_size=100"
        return self._list_named_items(url)

    def list_tags(self) -> list[PaperlessItem]:
        url = f"{self.settings.PAPERLESS_URL}/api/tags/?page_size=100"
        return self._list_named_items(url)

    def create_correspondent(
        self, name: str, matching_algorithm: str | int | None = "none"
    ) -> PaperlessItem:
        """Create a correspondent; return the decoded Paperless item body."""
        url = f"{self.settings.PAPERLESS_URL}/api/correspondents/"
        return cast(
            "PaperlessItem",
            self._create_named_item(
                url=url,
                name=name,
                matching_algorithm=matching_algorithm,
                item_label="correspondent",
            ),
        )

    def create_document_type(
        self, name: str, matching_algorithm: str | int | None = "none"
    ) -> PaperlessItem:
        """Create a document type; return the decoded Paperless item body."""
        url = f"{self.settings.PAPERLESS_URL}/api/document_types/"
        return cast(
            "PaperlessItem",
            self._create_named_item(
                url=url,
                name=name,
                matching_algorithm=matching_algorithm,
                item_label="document type",
            ),
        )

    def create_tag(
        self, name: str, matching_algorithm: str | int | None = "none"
    ) -> PaperlessItem:
        """Create a tag; return the decoded Paperless item body."""
        url = f"{self.settings.PAPERLESS_URL}/api/tags/"
        return cast(
            "PaperlessItem",
            self._create_named_item(
                url=url,
                name=name,
                matching_algorithm=matching_algorithm,
                item_label="tag",
            ),
        )

    def iter_all_documents(
        self,
        *,
        modified_after: str | None = None,
        fields: Sequence[str] | None = None,
    ) -> Iterator[dict]:
        """Yield every document, oldest ``modified`` first.

        *modified_after* keeps only documents modified strictly after it.
        *fields* asks Paperless for just those fields, so a light
        ``("id", "modified")`` listing skips transferring every OCR body.
        """
        params: dict[str, str | int] = {"ordering": "modified", "page_size": 100}
        if modified_after is not None:
            params["modified__gt"] = modified_after
        if fields is not None:
            params["fields"] = ",".join(fields)
        url = str(
            httpx.URL(f"{self.settings.PAPERLESS_URL}/api/documents/", params=params)
        )
        yield from self._list_all(url)

    def document_exists(self, doc_id: int) -> bool:
        """Return True if the document exists, False on a 404.

        Only a 404 means "does not exist": auth failures, 5xx after retries and
        network errors raise rather than report ``False``.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/"
        response = self._get(url)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def count_documents(self, timeout: float = 10) -> int:
        """Return the total document count Paperless reports.

        Backs the Settings "Test connection" action; a rejected token raises.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/?page_size=1"
        # Not retried, like ping(): the connection test should report a 5xx to
        # the operator at once rather than back off.
        response = self._client.get(url, timeout=timeout)
        response.raise_for_status()
        count = response.json().get("count", 0)
        return int(count)

    def ping(self, timeout: float = 10) -> None:
        """Single fast request to verify the API is reachable (no retry)."""
        url = f"{self.settings.PAPERLESS_URL}/api/"
        response = self._client.get(url, timeout=timeout)
        response.raise_for_status()

    def modify_tags(
        self,
        doc_id: int,
        *,
        add: Iterable[int] = (),
        remove: Iterable[int] = (),
    ) -> None:
        """Add and remove tags on a document without rewriting its tag list.

        Paperless applies the change server-side, so a tag another writer adds
        meanwhile is kept, unlike a read-modify-write of ``tags``.

        Raises:
            httpx.HTTPStatusError: On a non-2xx response.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/bulk_edit/"
        payload = {
            "documents": [doc_id],
            "method": "modify_tags",
            "parameters": {"add_tags": sorted(add), "remove_tags": sorted(remove)},
        }
        response = self._post(url, json=payload)
        self._raise_for_status_logging_body(
            response, doc_id=doc_id, payload_keys=["add_tags", "remove_tags"]
        )

    def delete_document(self, doc_id: int) -> None:
        """Delete a document from Paperless-ngx.

        Raises:
            httpx.HTTPStatusError: On a non-2xx response.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/"
        log.info("paperless.delete_document", doc_id=doc_id)
        response = self._delete(url)
        response.raise_for_status()

    def list_notes(self, doc_id: int) -> list[dict[str, Any]]:
        """Return the document's notes (each with ``id`` and ``note``), or ``[]``."""
        doc = self.get_document(doc_id)
        notes = doc.get("notes") or []
        return cast("list[dict[str, Any]]", notes)

    def add_note(self, doc_id: int, text: str) -> None:
        """Post a new note onto a document.

        Raises:
            httpx.HTTPStatusError: On a non-2xx response.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/notes/"
        log.info("paperless.add_note", doc_id=doc_id, length=len(text))
        response = self._post(url, json={"note": text})
        response.raise_for_status()

    def delete_note(self, doc_id: int, note_id: int) -> None:
        """Delete one note from a document by its id.

        Raises:
            httpx.HTTPStatusError: On a non-2xx response.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/notes/"
        log.info("paperless.delete_note", doc_id=doc_id, note_id=note_id)
        response = self._delete(url, params={"id": str(note_id)})
        response.raise_for_status()

    def close(self) -> None:
        self._client.close()
