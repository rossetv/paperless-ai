"""Paperless-ngx REST API client with automatic retries."""

from __future__ import annotations

from typing import Any, Generator, Iterable

import httpx
import structlog

from .config import Settings
from .retry import retry

log = structlog.get_logger(__name__)

# Exceptions that should trigger a retry: transient network errors and
# 5xx-induced HTTPStatusError (raised by _raise_for_status_if_server_error).
RETRYABLE_HTTP_EXCEPTIONS = (httpx.RequestError, httpx.HTTPStatusError)


class PaperlessClient:
    """A client for interacting with the Paperless-ngx API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.Client(
            headers={"Authorization": f"Token {self.settings.PAPERLESS_TOKEN}"},
            timeout=self.settings.REQUEST_TIMEOUT,
        )

    def _raise_for_status_if_server_error(self, response: httpx.Response) -> None:
        if response.status_code >= 500:
            response.raise_for_status()

    @retry(retryable_exceptions=RETRYABLE_HTTP_EXCEPTIONS)
    def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        kwargs.setdefault("timeout", self.settings.REQUEST_TIMEOUT)
        response = self._client.get(url, **kwargs)
        self._raise_for_status_if_server_error(response)
        return response

    @retry(retryable_exceptions=RETRYABLE_HTTP_EXCEPTIONS)
    def _patch(self, url: str, **kwargs: Any) -> httpx.Response:
        kwargs.setdefault("timeout", self.settings.REQUEST_TIMEOUT)
        response = self._client.patch(url, **kwargs)
        self._raise_for_status_if_server_error(response)
        return response

    @retry(retryable_exceptions=RETRYABLE_HTTP_EXCEPTIONS)
    def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        kwargs.setdefault("timeout", self.settings.REQUEST_TIMEOUT)
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

    def get_documents_to_process(self) -> Iterable[dict]:
        yield from self.get_documents_by_tag(self.settings.PRE_TAG_ID)

    def get_documents_by_tag(self, tag_id: int) -> Iterable[dict]:
        url = (
            f"{self.settings.PAPERLESS_URL}/api/documents/"
            f"?tags__id={tag_id}"
            "&page_size=100"
        )
        log.debug("Fetching documents with tag", tag_id=tag_id, url=url)
        yield from self._list_all(url)

    def get_document(self, doc_id: int) -> dict[str, Any]:
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/"
        log.debug("Fetching document", doc_id=doc_id, url=url)
        response = self._get(url)
        response.raise_for_status()
        return response.json()

    def download_content(self, doc_id: int) -> tuple[bytes, str]:
        """Download raw file bytes and content type for a document."""
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/download/"
        log.info("Downloading document", doc_id=doc_id, url=url)
        response = self._get(url)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "application/pdf")
        return response.content, content_type

    def update_document(self, doc_id: int, content: str, new_tags: list[int]) -> None:
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/"
        log.info(
            "Updating document",
            doc_id=doc_id,
            new_tags=new_tags,
            content_len=len(content),
        )
        payload = {"content": content, "tags": new_tags}
        response = self._patch(url, json=payload)
        response.raise_for_status()
        log.info("Successfully updated document", doc_id=doc_id)

    # Maps keyword argument names to Paperless API field names.
    _METADATA_FIELDS: tuple[tuple[str, str], ...] = (
        ("title", "title"),
        ("correspondent_id", "correspondent"),
        ("document_type_id", "document_type"),
        ("document_date", "created"),
        ("tags", "tags"),
        ("language", "language"),
        ("custom_fields", "custom_fields"),
    )

    def update_document_metadata(
        self,
        doc_id: int,
        *,
        title: str | None = None,
        correspondent_id: int | None = None,
        document_type_id: int | None = None,
        document_date: str | None = None,
        tags: list[int] | None = None,
        language: str | None = None,
        custom_fields: list[dict] | None = None,
    ) -> None:
        local_vars = locals()
        payload = {
            api_key: local_vars[param]
            for param, api_key in self._METADATA_FIELDS
            if local_vars[param] is not None
        }

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
        log.debug("Listing correspondents", url=url)
        return list(self._list_all(url))

    def list_document_types(self) -> list[dict]:
        url = f"{self.settings.PAPERLESS_URL}/api/document_types/?page_size=100"
        log.debug("Listing document types", url=url)
        return list(self._list_all(url))

    def list_tags(self) -> list[dict]:
        url = f"{self.settings.PAPERLESS_URL}/api/tags/?page_size=100"
        log.debug("Listing tags", url=url)
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
        """Close the underlying HTTP client."""
        self._client.close()
