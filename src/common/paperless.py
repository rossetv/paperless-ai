"""Paperless-ngx REST API client with automatic retries."""

from __future__ import annotations

import types
from collections.abc import Iterator
from typing import Any, Generator, Iterable, NotRequired, TypedDict, Unpack

import httpx
import structlog

from .config import Settings
from .retry import retry

log = structlog.get_logger(__name__)

# Exceptions that should trigger a retry: transient network errors and
# 5xx-induced HTTPStatusError (raised by _raise_for_status_if_server_error).
RETRYABLE_HTTP_EXCEPTIONS = (httpx.RequestError, httpx.HTTPStatusError)

# Exceptions that callers should catch when wrapping PaperlessClient calls
# in non-fatal error handling.  Covers network errors, HTTP errors, and
# unexpected response shapes.
PAPERLESS_CALL_EXCEPTIONS = (OSError, httpx.HTTPError, ValueError, KeyError)


def _named_item_payload(
    name: str, matching_algorithm: str | int | None
) -> dict[str, str | int]:
    """Build the create-payload for a named item, omitting a ``None`` algorithm."""
    payload: dict[str, str | int] = {"name": name}
    if matching_algorithm is not None:
        payload["matching_algorithm"] = matching_algorithm
    return payload


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
    custom_fields: list[dict] | None


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
    @retry(retryable_exceptions=RETRYABLE_HTTP_EXCEPTIONS)
    def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        response = self._client.post(url, **kwargs)
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
            "Creating item",
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

    def update_document(self, doc_id: int, content: str, new_tags: Iterable[int]) -> None:
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/"
        tags_list = list(new_tags)
        log.info(
            "Updating document",
            doc_id=doc_id,
            new_tags=tags_list,
            content_len=len(content),
        )
        payload = {"content": content, "tags": tags_list}
        response = self._patch(url, json=payload)
        response.raise_for_status()
        log.info("Successfully updated document", doc_id=doc_id)

    # Maps DocumentMetadataUpdate keys to Paperless API field names.
    _METADATA_FIELDS = types.MappingProxyType({
        "title": "title",
        "correspondent_id": "correspondent",
        "document_type_id": "document_type",
        "document_date": "created",
        "tags": "tags",
        "language": "language",
        "custom_fields": "custom_fields",
    })

    def update_document_metadata(
        self,
        doc_id: int,
        **kwargs: Unpack[DocumentMetadataUpdate],
    ) -> None:
        """Update document metadata fields on Paperless.

        Accepts keyword arguments matching :class:`DocumentMetadataUpdate`.
        Keys not provided (or absent) are silently skipped.
        """
        payload: dict[str, object] = {}
        for key, api_field in self._METADATA_FIELDS.items():
            value = kwargs.get(key)  # type: ignore[literal-required]
            if value is None:
                continue
            if key == "tags":
                value = list(value)  # type: ignore[call-overload]
            payload[api_field] = value

        if not payload:
            log.info("No metadata updates to apply", doc_id=doc_id)
            return

        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/"
        log.info("Updating document metadata", doc_id=doc_id, payload_keys=list(payload))
        response = self._patch(url, json=payload)
        response.raise_for_status()
        log.info("Successfully updated document metadata", doc_id=doc_id)

    def list_correspondents(self) -> list[dict]:
        url = f"{self.settings.PAPERLESS_URL}/api/correspondents/?page_size=100"
        return list(self._list_all(url))

    def list_document_types(self) -> list[dict]:
        url = f"{self.settings.PAPERLESS_URL}/api/document_types/?page_size=100"
        return list(self._list_all(url))

    def list_tags(self) -> list[dict]:
        url = f"{self.settings.PAPERLESS_URL}/api/tags/?page_size=100"
        return list(self._list_all(url))

    def create_correspondent(
        self, name: str, matching_algorithm: str | int | None = "none"
    ) -> dict[str, object]:
        """Create a correspondent; return the decoded Paperless JSON body."""
        url = f"{self.settings.PAPERLESS_URL}/api/correspondents/"
        return self._create_named_item(
            url=url,
            name=name,
            matching_algorithm=matching_algorithm,
            item_label="correspondent",
        )

    def create_document_type(
        self, name: str, matching_algorithm: str | int | None = "none"
    ) -> dict[str, object]:
        """Create a document type; return the decoded Paperless JSON body."""
        url = f"{self.settings.PAPERLESS_URL}/api/document_types/"
        return self._create_named_item(
            url=url,
            name=name,
            matching_algorithm=matching_algorithm,
            item_label="document type",
        )

    def create_tag(
        self, name: str, matching_algorithm: str | int | None = "none"
    ) -> dict[str, object]:
        """Create a tag; return the decoded Paperless JSON body."""
        url = f"{self.settings.PAPERLESS_URL}/api/tags/"
        return self._create_named_item(
            url=url,
            name=name,
            matching_algorithm=matching_algorithm,
            item_label="tag",
        )

    def iter_all_documents(self, *, modified_after: str | None = None) -> Iterator[dict]:
        """Yield every document from Paperless, ordered by ``modified`` ascending.

        Pages ``GET /api/documents/`` with ``ordering=modified`` via the
        existing :meth:`_list_all` pagination generator.  Retries are handled
        by the ``@retry``-wrapped :meth:`_get` that ``_list_all`` calls
        internally — no additional retry logic is needed here.

        Args:
            modified_after: If supplied, only documents whose ``modified``
                timestamp is strictly after this value are returned.  The
                value is passed to Paperless as the ``modified__gt`` filter
                parameter.
        """
        params: dict[str, str | int] = {"ordering": "modified", "page_size": 100}
        if modified_after is not None:
            # modified__gt is the Paperless-ngx documents filterset parameter
            # for strict greater-than on the modified field (server-side filter).
            params["modified__gt"] = modified_after
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

    def ping(self, timeout: float = 10) -> None:
        """Single fast request to verify the API is reachable (no retry)."""
        url = f"{self.settings.PAPERLESS_URL}/api/"
        response = self._client.get(url, timeout=timeout)
        response.raise_for_status()

    def close(self) -> None:
        self._client.close()
