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

# rationale: this module exceeds the CODE_GUIDELINES §3.1 500-line ceiling. The bulk is the single ``PaperlessClient`` class: every Paperless
# operation (documents, tags, custom fields, the streaming download for the
# in-app PDF viewer, the count for the test-connection probe) is a method on the
# same instance, sharing one ``httpx`` session and the retry/timeout/auth state
# set up in ``__init__``. §3.3 says to prefer a package over a sibling-dump when
# a file grows — but a package split here would have to scatter ONE class across
# modules via inheritance mixins, each carrying an implicit ``self._client`` /
# ``self.settings`` contract. That is precisely the mixin-for-DRY anti-pattern
# §1.9 warns against and the one this very codebase just deleted (ErrorFinaliser
# Mixin, COMMON-07); reintroducing three or four of them to split one client
# would lower clarity, not raise it. The genuinely separable pieces have already
# left: the wire-shape TypedDicts live in ``common.paperless_types`` (re-exported
# below). One cohesive client is one concept (§3.2); keeping it whole is the
# honest call. (COMMON-02)
#
# Re-exported below so callers keep importing the Paperless wire shapes from
# ``common.paperless``; the definitions live in ``common.paperless_types``.
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

# Exceptions that should trigger a retry: transient network errors and
# 5xx-induced HTTPStatusError (raised by _raise_for_status_if_server_error).
# Used for the idempotent verbs (GET, PATCH, DELETE) where re-issuing a request
# the server may already have processed is harmless.
RETRYABLE_HTTP_EXCEPTIONS = (httpx.RequestError, httpx.HTTPStatusError)

# A POST is **not** idempotent — re-issuing one the server already processed
# double-applies a non-idempotent write. For ``add_note`` (Paperless notes are
# not unique) that means a duplicate note. So a POST retries only on the
# *connect phase*, where the request provably never reached the server:
#   - ``httpx.ConnectError`` — the TCP/TLS connection could not be established.
#   - ``httpx.ConnectTimeout`` — the connection attempt itself timed out.
#   - ``httpx.HTTPStatusError`` — only 5xx reach this (4xx are not raised by
#     ``_raise_for_status_if_server_error``); a 5xx means the server refused to
#     process the request, so re-sending is safe.
# Deliberately EXCLUDED (unlike the idempotent verbs): ``httpx.ReadTimeout`` and
# ``httpx.RemoteProtocolError`` — those drop while reading the *response* to a
# request the server may already have applied, so retrying would double-write.
RETRYABLE_POST_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.HTTPStatusError,
)

# Exceptions that callers should catch when wrapping PaperlessClient calls
# in non-fatal error handling.  Covers network errors, HTTP errors, and
# unexpected response shapes.
PAPERLESS_CALL_EXCEPTIONS = (OSError, httpx.HTTPError, ValueError, KeyError)


def is_permanent_paperless_error(exc: BaseException) -> bool:
    """True when *exc* is a Paperless HTTP 4xx client error.

    A 4xx (bad request, invalid pk, unrecognised field, …) is **deterministic**:
    the same payload will be rejected on every retry, so re-running the upstream
    work — for the daemons, an LLM OCR or classification call that has *already
    spent tokens* — only burns more tokens to fail again. Callers use this to
    decide between **quarantining** the document (error-tag it, stop the loop)
    and **re-raising** a transient error (network blip, 5xx) for the daemon loop
    to retry. 5xx is intentionally excluded: it is the retryable class the
    ``@retry`` decorator already backs off on.

    408 (Request Timeout) and 429 (Too Many Requests) are 4xx by number but
    transient by semantics — a retry can succeed — so they are excluded from the
    permanent set and left to retry like a 5xx. Paperless-ngx ships no rate
    limiter today, so neither is expected in practice; excluding them is
    belt-and-braces for a proxy sitting in front of it.
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
    """The sole sanctioned path for Paperless-ngx HTTP (CODE_GUIDELINES §8.1).

    Every call against the Paperless-ngx REST API in the codebase goes through
    this client. It owns the four cross-cutting concerns that a bespoke
    ``httpx`` call gets wrong eventually:

    - **Authentication** — the ``Token`` header is set once at construction.
    - **Retries** — :func:`~common.retry.retry` wraps every request, retrying
      transient network errors and 5xx responses with exponential backoff.
    - **Pagination** — :meth:`_list_all` follows the ``next`` cursor so callers
      receive a flat iterator, never a page.
    - **Timeouts** — a request timeout is enforced on every call.

    The client is **not thread-safe** (CODE_GUIDELINES §8.3): the underlying
    ``httpx`` session is single-threaded. Each worker thread constructs its own
    :class:`PaperlessClient`.
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
        """``raise_for_status`` that first logs the body on a 4xx.

        ``httpx.HTTPStatusError`` only carries the status line and URL — not the
        response body — so a Paperless 400 surfaces as an opaque "Client error
        '400 Bad Request'" with no clue which field was rejected. Paperless
        returns a per-field JSON error body (e.g. ``{"tags": ["Invalid pk 47 -
        object does not exist."]}``); capturing it here turns an undiagnosable
        loop into a one-line answer. The exception is still raised so callers'
        error handling is unchanged.
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

    # Any: **kwargs here is a pure passthrough to httpx's request methods
    # (json=, params=, timeout=, …); httpx itself types those parameters with
    # broad union/Any aliases, so a tighter annotation here would be a fiction
    # narrower than the function it forwards to.
    @retry(retryable_exceptions=RETRYABLE_HTTP_EXCEPTIONS)
    def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        response = self._client.get(url, **kwargs)
        self._raise_for_status_if_server_error(response)
        return response

    # Any: see _get — pure passthrough to httpx.Client.patch.
    @retry(retryable_exceptions=RETRYABLE_HTTP_EXCEPTIONS)
    def _patch(self, url: str, **kwargs: Any) -> httpx.Response:
        response = self._client.patch(url, **kwargs)
        self._raise_for_status_if_server_error(response)
        return response

    # Any: see _get — pure passthrough to httpx.Client.post.
    # POST uses the narrowed connect-phase-only retry set: a non-idempotent write
    # must not be re-issued after a response-read drop the server may have already
    # applied (see RETRYABLE_POST_EXCEPTIONS).
    @retry(retryable_exceptions=RETRYABLE_POST_EXCEPTIONS)
    def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        response = self._client.post(url, **kwargs)
        self._raise_for_status_if_server_error(response)
        return response

    # Any: see _get — pure passthrough to httpx.Client.delete.
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
        """Create a named item, trying alternate matching_algorithm representations on 400.

        Paperless-ngx rejects an unexpected ``matching_algorithm`` type with a
        400. We POST each candidate representation in turn; a 400 on a
        non-final candidate means "try the next". The final candidate is POSTed
        with ``swallow_400=False`` so its outcome — a decoded body or a raised
        error — is the function's outcome. The loop therefore always returns or
        raises; there is no exhausted fall-through path.

        Returns:
            The decoded JSON body of the created item (raw Paperless shape).
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

        # Try every candidate but the last, swallowing a 400 ("this
        # matching_algorithm representation was rejected — try the next").
        for candidate in candidates[:-1]:
            body = self._post_named_item(url, name, candidate)
            if body is not None:
                return body

        # The final candidate is POSTed with swallow_400=False: it returns a
        # decoded body or raises. Its return type therefore excludes None, so
        # this is the function's only terminal statement — no unreachable
        # fall-through branch and no AssertionError control-flow marker.
        return self._post_final_named_item(url, name, candidates[-1])

    def _post_final_named_item(
        self, url: str, name: str, matching_algorithm: str | int | None
    ) -> dict[str, object]:
        """POST the final named-item candidate; return its decoded body or raise.

        Unlike :meth:`_post_named_item`, this never swallows a 400 — the final
        candidate has no successor to fall through to, so every HTTP error
        propagates. The non-optional return type makes this a valid terminal
        statement for :meth:`_create_named_item`.
        """
        response = self._post(url, json=_named_item_payload(name, matching_algorithm))
        response.raise_for_status()
        # JSON object: the decoded Paperless API response body — an external
        # shape with no fixed schema worth pinning here.
        decoded: dict[str, object] = response.json()
        return decoded

    def _post_named_item(
        self, url: str, name: str, matching_algorithm: str | int | None
    ) -> dict[str, object] | None:
        """POST one non-final named-item candidate; return its body, or None on a 400.

        A 400 returns ``None`` so :meth:`_create_named_item` can try the next
        ``matching_algorithm`` representation; any other HTTP error propagates.

        Returns:
            The decoded JSON body, or ``None`` when Paperless returned a 400.
        """
        response = self._post(url, json=_named_item_payload(name, matching_algorithm))
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            if response.status_code == 400:
                return None
            raise
        # JSON object: the decoded Paperless API response body — an external
        # shape with no fixed schema worth pinning here.
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
        """Fetch a single document by ID; return its raw Paperless JSON dict.

        Raises:
            httpx.HTTPStatusError: On a non-2xx response (a 404 for an unknown
                ID is *not* swallowed here — use :meth:`document_exists` for an
                existence check).
        """
        # dict[str, Any]: the value is decoded Paperless document JSON — a
        # foreign shape with many optional fields. Callers translate it into a
        # domain dataclass at their boundary (CODE_GUIDELINES §5.3).
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
        """Download the pristine ORIGINAL file (pre-archive/pre-OCR) bytes + content type.

        Unlike :meth:`download_content` (which serves the archive when one exists), this
        appends ``?original=true`` so a scan's original has no Tesseract text layer — the
        mode-independent signal the born-digital gate needs (spec D2).
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/download/?original=true"
        response = self._get(url)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "application/pdf")
        return response.content, content_type

    def download_stream(self, doc_id: int) -> tuple[str, Iterator[bytes]]:
        """Stream a document's original file straight from Paperless-ngx.

        Unlike :meth:`download_content`, this never buffers the whole file:
        it opens a *single* ``httpx`` streaming response and returns the
        document's content type plus an iterator that yields the body in
        chunks. It backs the search server's in-app PDF viewer proxy
        (web-redesign §5), where buffering a large scan into memory per
        request is wasteful.

        The status and headers are read from the streaming response before
        the body is consumed — ``httpx`` exposes them as soon as the
        response head has arrived — so exactly one HTTP request is made per
        call, not one to probe the headers and another for the body.

        The returned iterator owns the open HTTP response: it must be fully
        drained (or closed) by the caller so the underlying connection is
        released. The search server hands it to a Starlette
        ``StreamingResponse``, which drains it as it writes the body, and
        also guards the un-drained paths (a client disconnect) by closing
        the client. The iterator's ``finally`` closes the response so a
        partially-consumed stream never leaks the connection.

        A non-2xx status (notably a 404 for an unknown ``doc_id``) is raised
        as an :class:`httpx.HTTPStatusError` *here*, before this method
        returns — the stream is opened and ``raise_for_status`` is checked
        eagerly. Server errors are **not** retried — a streaming body cannot
        be safely replayed once partially consumed — so this deliberately
        does not use the ``@retry``-wrapped ``_get``.

        Args:
            doc_id: The Paperless-ngx document id.

        Returns:
            A two-tuple of the response ``Content-Type`` (defaulting to
            ``application/pdf`` when Paperless omits the header) and an
            iterator yielding the file body in byte chunks.

        Raises:
            httpx.HTTPStatusError: On a non-2xx response — the open stream
                is closed before the exception propagates.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/download/"
        return self._stream_endpoint(url, default_content_type="application/pdf")

    def _stream_endpoint(
        self, url: str, *, default_content_type: str
    ) -> tuple[str, Iterator[bytes]]:
        """Open *url* as a single streaming response, returning (content_type, body).

        The shared engine behind :meth:`download_stream` and
        :meth:`thumb_stream` — the only difference between those two is the URL
        suffix and the *default_content_type* used when Paperless omits the
        header, so the connection-leak-safety contract lives here once rather
        than being duplicated (COMMON-09).

        ``send(..., stream=True)`` opens the response without reading the body;
        the status and headers are available immediately. ``raise_for_status``
        is checked eagerly here so a non-2xx status surfaces before this method
        returns — the response is closed first so the failed-request connection
        is never leaked. Server errors are **not** retried: a streaming body
        cannot be safely replayed once partially consumed, so this deliberately
        bypasses the ``@retry``-wrapped :meth:`_get`.

        Args:
            url: The fully-qualified Paperless endpoint to stream.
            default_content_type: The ``Content-Type`` to report when Paperless
                omits the header.

        Returns:
            A two-tuple of the response ``Content-Type`` and an iterator that
            yields the body in byte chunks. The iterator owns the open
            response; its ``finally`` closes it so a partially-consumed stream
            never leaks the connection.

        Raises:
            httpx.HTTPStatusError: On a non-2xx response — the open stream is
                closed before the exception propagates.
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
            """Yield the body of the already-open streaming response.

            The ``finally`` closes the response — releasing the connection —
            whether the caller drained every chunk, stopped early, or the
            transfer raised mid-body.
            """
            try:
                yield from response.iter_bytes()
            finally:
                response.close()

        return content_type, _iter_body()

    def thumb_stream(self, doc_id: int) -> tuple[str, Iterator[bytes]]:
        """Stream a document's first-page thumbnail straight from Paperless-ngx.

        Mirrors :meth:`download_stream` but hits the thumbnail endpoint
        (``/api/documents/{doc_id}/thumb/``) instead of the download endpoint.
        Paperless-ngx returns a WebP or JPEG image; the content type is
        forwarded to the caller unchanged.

        The same connection-management contract as :meth:`download_stream`
        applies: a single streaming response is opened, ``raise_for_status``
        is checked eagerly, and the returned iterator owns the open response —
        it must be fully drained (or closed) so the underlying connection is
        released.

        Args:
            doc_id: The Paperless-ngx document id.

        Returns:
            A two-tuple of the response ``Content-Type`` (defaulting to
            ``image/jpeg`` when Paperless omits the header) and an iterator
            yielding the thumbnail body in byte chunks.

        Raises:
            httpx.HTTPStatusError: On a non-2xx response — the open stream
                is closed before the exception propagates.
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

    # Maps DocumentMetadataUpdate keys to Paperless API field names.
    # ``notes`` is intentionally absent: it is handled via the separate notes
    # endpoint before the PATCH payload is assembled.
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

    # DocumentMetadataUpdate keys that Paperless rejects when sent as null
    # ("This field may not be null"). A None for these means "leave unchanged"
    # and is omitted from the PATCH payload rather than forwarded as null.
    _NON_NULLABLE_FIELDS = frozenset({"custom_fields", "document_date"})

    def update_document_metadata(
        self,
        doc_id: int,
        **kwargs: Unpack[DocumentMetadataUpdate],
    ) -> None:
        """Update document metadata fields on Paperless.

        Accepts keyword arguments matching :class:`DocumentMetadataUpdate`.
        Absent keys are silently skipped (field is left unchanged). Explicitly
        supplied ``None`` values are forwarded to Paperless as ``null``, which
        Paperless treats as "clear this field" — except for the fields in
        :attr:`_NON_NULLABLE_FIELDS` (``custom_fields`` and ``document_date``),
        which Paperless rejects when null and where None means "leave unchanged".

        ``notes`` is handled separately from the PATCH payload: the new text is
        posted FIRST (unless the value is the empty string), then the previously
        existing notes are deleted. This add-before-delete order means a failure
        mid-operation never leaves the document with zero notes — losing notes is
        unrecoverable, a transient duplicate is not. An empty string leaves the
        document with no notes (the old ones are deleted, nothing is added).
        ``archive_serial_number`` is passed through to the PATCH endpoint.
        """
        if "notes" in kwargs:
            notes_text = kwargs.pop("notes")  # type: ignore[misc]
            # Add-before-delete: the new note is posted FIRST, then the old ones
            # are removed. Posting before deleting means a failure part-way
            # through never leaves the document with zero notes — at worst it
            # leaves the new note alongside a stale one, which is recoverable;
            # losing the notes entirely is not. The existing IDs are snapshotted
            # before the add so the freshly-added note is never itself deleted.
            existing = self.list_notes(doc_id)
            existing_ids = [note["id"] for note in existing]
            if notes_text is not None and notes_text != "":
                self.add_note(doc_id, notes_text)
            for note_id in existing_ids:
                self.delete_note(doc_id, note_id)

        payload: dict[str, object] = {}
        for key, api_field in self._METADATA_FIELDS.items():
            # rationale: TypedDict.get() requires a Literal key; the loop variable
            # `key` is typed as `str` so mypy cannot prove it is Literal["tags"|…].
            if key not in kwargs:  # type: ignore[literal-required]
                # Field absent — caller did not supply it, leave unchanged.
                continue
            value = kwargs[key]  # type: ignore[literal-required]
            # `value` may be None — Paperless treats null as "clear the field".
            if key in self._NON_NULLABLE_FIELDS and value is None:
                # Exception to the null-clears contract: Paperless rejects null
                # for these fields with a 400 ("This field may not be null").
                #   - custom_fields: cleared with an empty list, not null.
                #   - document_date (`created`): every document always has a
                #     creation date; there is no "clear" operation. The
                #     classifier passes None whenever it cannot extract a date,
                #     which must mean "leave the existing date unchanged".
                # A None here therefore means "no opinion — leave unchanged" and
                # is omitted from the payload rather than forwarded as null.
                continue
            if key == "tags" and value is not None:
                # rationale: `value` is `int | str | list[int] | None` from the
                # TypedDict union; mypy cannot narrow to Iterable[int] here even
                # though the runtime branch guarantees it when key == "tags".
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
        """List a taxonomy endpoint, typing each row as a :class:`PaperlessItem`.

        cast: :meth:`_list_all` yields the raw decoded Paperless JSON dict; for
        the correspondent / document-type / tag endpoints that shape *is* a
        :class:`PaperlessItem`. The cast pins the type at the single place the
        taxonomy rows enter the typed world.
        """
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
        # cast: the created-item body Paperless returns is a PaperlessItem.
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
        # cast: the created-item body Paperless returns is a PaperlessItem.
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
        # cast: the created-item body Paperless returns is a PaperlessItem.
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
        """Yield every document from Paperless, ordered by ``modified`` ascending.

        Pages ``GET /api/documents/`` with ``ordering=modified`` via the
        existing :meth:`_list_all` pagination generator.  Retries are handled
        by the ``@retry``-wrapped :meth:`_get` that ``_list_all`` calls
        internally — no additional retry logic is needed here.

        Args:
            modified_after: If supplied, only documents whose ``modified``
                timestamp is strictly after this value are returned.  The
                value is passed to Paperless as the ``modified__gt`` filter
                parameter (server-side filter).
            fields: If supplied, request only these document fields from
                Paperless via the ``fields`` sparse-fieldset projection.
                ``None`` (the default) returns the full document object,
                including the OCR ``content`` body.  A light
                ``("id", "modified")`` projection lets the reconciler diff which
                documents changed without paying to transfer every OCR body
                (IDX-03); Paperless drops every field not listed.
        """
        params: dict[str, str | int] = {"ordering": "modified", "page_size": 100}
        if modified_after is not None:
            # modified__gt is the Paperless-ngx documents filterset parameter
            # for strict greater-than on the modified field (server-side filter).
            params["modified__gt"] = modified_after
        if fields is not None:
            # fields is the Paperless-ngx sparse-fieldset projection: the server
            # serialises only the listed fields, omitting the heavy OCR content
            # body when it is not requested (IDX-03).
            params["fields"] = ",".join(fields)
        url = str(
            httpx.URL(f"{self.settings.PAPERLESS_URL}/api/documents/", params=params)
        )
        yield from self._list_all(url)

    def document_exists(self, doc_id: int) -> bool:
        """Return True if the document exists in Paperless, False on a 404.

        Uses :meth:`_get` which retries 5xx errors.  A genuine 404 is not a
        server error — :meth:`_raise_for_status_if_server_error` leaves it
        untouched — so it surfaces here as a normal response and is mapped to
        ``False`` without retrying.

        Only a 404 is treated as "does not exist". This is **not** a
        catch-all reachability check: an authentication or authorisation
        failure (401/403), a 5xx that survives all retries, or a network
        error all propagate as an :class:`httpx.HTTPStatusError` /
        :class:`httpx.RequestError` rather than being reported as ``False``.

        Raises:
            httpx.HTTPStatusError: On any non-404, non-2xx response — notably
                401/403 (token rejected) and 5xx after retries are exhausted.
            httpx.RequestError: On a network-level failure.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/"
        response = self._get(url)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def count_documents(self, timeout: float = 10) -> int:
        """Return the total document count Paperless reports.

        Requests a single-item page of the documents list and reads its
        ``count`` field — Paperless returns the full collection size there.
        Used by the Settings "Test connection" action to confirm an
        authenticated round-trip and show the operator the library size.

        Raises:
            httpx.HTTPStatusError: A non-2xx response — notably 401/403 when
                the token is rejected.
            httpx.RequestError: A network-level failure.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/?page_size=1"
        # why: deliberately bypasses the @retry-wrapped _get, like ping(). This
        # backs the Settings "Test connection" probe, which wants a single fast
        # shot with a short timeout — a transient 5xx should surface to the
        # operator immediately, not be retried with backoff (COMMON-10).
        response = self._client.get(url, timeout=timeout)
        response.raise_for_status()
        count = response.json().get("count", 0)
        return int(count)

    def ping(self, timeout: float = 10) -> None:
        """Single fast request to verify the API is reachable (no retry)."""
        url = f"{self.settings.PAPERLESS_URL}/api/"
        response = self._client.get(url, timeout=timeout)
        response.raise_for_status()

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
        """Return the document's notes array (each entry has ``id`` and ``note``).

        Returns an empty list when the document has no notes or the ``notes``
        field is absent from the response.
        """
        doc = self.get_document(doc_id)
        notes = doc.get("notes") or []
        # cast: the Paperless document JSON keeps a `notes` list of {id, note, …} dicts.
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
