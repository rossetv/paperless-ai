"""Paperless-ngx REST API client with automatic retries."""

from __future__ import annotations

import types
from typing import Any, Generator, Iterable, TypedDict, Unpack

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


# TypedDict is used here because it maps directly to **kwargs with Unpack,
# giving callers keyword-level type checking while remaining a plain dict
# at runtime (no instantiation overhead, easy JSON serialisation).
class DocumentMetadataUpdate(TypedDict, total=False):
    """Keyword arguments accepted by :meth:`PaperlessClient.update_document_metadata`."""

    title: str
    correspondent_id: int
    document_type_id: int
    document_date: str
    tags: set[int]
    language: str
    custom_fields: list[dict]


class PaperlessClient:
    """A client for interacting with the Paperless-ngx API."""

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
    ) -> dict[str, Any]:
        """Create a named item, trying alternate matching_algorithm representations on 400."""
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
        elif isinstance(matching_algorithm, int):
            candidates = [matching_algorithm, "none"]
        else:
            candidates = [matching_algorithm]

        last_response: httpx.Response | None = None
        for index, candidate in enumerate(candidates):
            payload = {"name": name}
            if candidate is not None:
                payload["matching_algorithm"] = candidate
            last_response = self._post(url, json=payload)
            try:
                last_response.raise_for_status()
                return last_response.json()
            except httpx.HTTPStatusError:
                if last_response.status_code != 400 or index == len(candidates) - 1:
                    raise

        # All candidates were exhausted via non-raising 400 paths; this should
        # be unreachable because the last candidate always re-raises above.
        raise AssertionError(  # pragma: no cover
            f"_create_named_item fell through unexpectedly for {item_label!r} {name!r}"
        )

    def get_documents_by_tag(self, tag_id: int) -> Iterable[dict]:
        url = (
            f"{self.settings.PAPERLESS_URL}/api/documents/"
            f"?tags__id={tag_id}"
            "&page_size=100"
        )
        yield from self._list_all(url)

    def get_document(self, doc_id: int) -> dict[str, Any]:
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/"
        response = self._get(url)
        response.raise_for_status()
        return response.json()

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
                value = list(value)  # type: ignore[arg-type]
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
    ) -> dict[str, Any]:
        url = f"{self.settings.PAPERLESS_URL}/api/correspondents/"
        return self._create_named_item(
            url=url,
            name=name,
            matching_algorithm=matching_algorithm,
            item_label="correspondent",
        )

    def create_document_type(
        self, name: str, matching_algorithm: str | int | None = "none"
    ) -> dict[str, Any]:
        url = f"{self.settings.PAPERLESS_URL}/api/document_types/"
        return self._create_named_item(
            url=url,
            name=name,
            matching_algorithm=matching_algorithm,
            item_label="document type",
        )

    def create_tag(self, name: str, matching_algorithm: str | int | None = "none") -> dict[str, Any]:
        url = f"{self.settings.PAPERLESS_URL}/api/tags/"
        return self._create_named_item(
            url=url,
            name=name,
            matching_algorithm=matching_algorithm,
            item_label="tag",
        )

    def ping(self, timeout: float = 10) -> None:
        """Single fast request to verify the API is reachable (no retry)."""
        url = f"{self.settings.PAPERLESS_URL}/api/"
        response = self._client.get(url, timeout=timeout)
        response.raise_for_status()

    def close(self) -> None:
        self._client.close()
