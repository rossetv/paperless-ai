"""
Paperless-ngx API Client
========================

This module provides a client for interacting with the Paperless-ngx API.
It encapsulates all the logic for making authenticated requests to a
Paperless-ngx instance, handling pagination, and performing common
operations like listing documents, downloading files, and updating
document content and tags.

The `PaperlessClient` class is designed to be a reusable and testable
component that abstracts away the details of the Paperless-ngx REST API.
"""

from typing import Generator, Iterable

import requests
import structlog

from .config import Settings
from .retry import retry

log = structlog.get_logger(__name__)


class PaperlessClient:
    """A client for interacting with the Paperless-ngx API."""

    def __init__(self, settings: Settings):
        """Initializes the client with a session and authentication."""
        self.settings = settings
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Token {self.settings.PAPERLESS_TOKEN}"}
        )

    def _raise_for_status_if_server_error(self, response: requests.Response) -> None:
        """
        Raise for 5xx responses to enable retries; let callers handle 4xx.
        """
        if response.status_code >= 500:
            response.raise_for_status()

    @retry(retryable_exceptions=(requests.exceptions.RequestException,))
    def _get(self, *args, **kwargs) -> requests.Response:
        """A retriable version of session.get."""
        kwargs.setdefault("timeout", self.settings.REQUEST_TIMEOUT)
        response = self._session.get(*args, **kwargs)
        self._raise_for_status_if_server_error(response)
        return response

    @retry(retryable_exceptions=(requests.exceptions.RequestException,))
    def _patch(self, *args, **kwargs) -> requests.Response:
        """A retriable version of session.patch."""
        kwargs.setdefault("timeout", self.settings.REQUEST_TIMEOUT)
        response = self._session.patch(*args, **kwargs)
        self._raise_for_status_if_server_error(response)
        return response

    @retry(retryable_exceptions=(requests.exceptions.RequestException,))
    def _post(self, *args, **kwargs) -> requests.Response:
        """A retriable version of session.post."""
        kwargs.setdefault("timeout", self.settings.REQUEST_TIMEOUT)
        response = self._session.post(*args, **kwargs)
        self._raise_for_status_if_server_error(response)
        return response

    def _list_all(self, url: str) -> Generator[dict, None, None]:
        """
        Generator that follows Paperless-ngx paginated API and yields every result.
        """
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
    ) -> dict:
        """
        Create a named item with an optional matching algorithm.

        Paperless uses the matching algorithm to auto-match new items. We default
        to "none" and try alternate representations if the API rejects the value.
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
        elif isinstance(matching_algorithm, int):
            candidates = [matching_algorithm, "none"]
        else:
            candidates = [matching_algorithm]

        for index, candidate in enumerate(candidates):
            payload = {"name": name}
            if candidate is not None:
                payload["matching_algorithm"] = candidate
            response = self._post(url, json=payload)
            try:
                response.raise_for_status()
                return response.json()
            except requests.exceptions.HTTPError:
                if response.status_code != 400 or index == len(candidates) - 1:
                    raise

    def get_documents_to_process(self) -> Iterable[dict]:
        """
        Return documents that have the pre-OCR tag.
        """
        yield from self.get_documents_by_tag(self.settings.PRE_TAG_ID)

    def get_documents_by_tag(self, tag_id: int) -> Iterable[dict]:
        """
        Return documents that have the provided tag.
        """
        url = (
            f"{self.settings.PAPERLESS_URL}/api/documents/"
            f"?tags__id={tag_id}"
            "&page_size=100"
        )
        log.debug("Fetching documents with tag", tag_id=tag_id, url=url)
        yield from self._list_all(url)

    def get_document(self, doc_id: int) -> dict:
        """
        Fetch a single document by ID.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/"
        log.debug("Fetching document", doc_id=doc_id, url=url)
        response = self._get(url)
        response.raise_for_status()
        return response.json()

    def download_content(self, doc_id: int) -> tuple[bytes, str]:
        """
        Download the content of a document from Paperless.

        Returns a tuple containing the raw file content as bytes and the content type.
        This method is a pure network operation and does not interact with the filesystem.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/download/"
        log.info("Downloading document", doc_id=doc_id, url=url)
        response = self._get(url)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "application/pdf")
        return response.content, content_type

    def update_document(self, doc_id: int, content: str, new_tags: list[int]) -> None:
        """
        Upload content back to Paperless and set the new tags.
        """
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
        """
        Update document metadata fields in Paperless.
        """
        payload: dict = {}
        if title is not None:
            payload["title"] = title
        if correspondent_id is not None:
            payload["correspondent"] = correspondent_id
        if document_type_id is not None:
            payload["document_type"] = document_type_id
        if document_date is not None:
            payload["created"] = document_date
        if tags is not None:
            payload["tags"] = tags
        if language is not None:
            payload["language"] = language
        if custom_fields is not None:
            payload["custom_fields"] = custom_fields

        if not payload:
            log.info("No metadata updates to apply", doc_id=doc_id)
            return

        url = f"{self.settings.PAPERLESS_URL}/api/documents/{doc_id}/"
        log.info("Updating document metadata", doc_id=doc_id, payload_keys=list(payload))
        response = self._patch(url, json=payload)
        response.raise_for_status()
        log.info("Successfully updated document metadata", doc_id=doc_id)

    def list_correspondents(self) -> list[dict]:
        """
        List all correspondents in Paperless.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/correspondents/?page_size=100"
        log.debug("Listing correspondents", url=url)
        return list(self._list_all(url))

    def list_document_types(self) -> list[dict]:
        """
        List all document types in Paperless.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/document_types/?page_size=100"
        log.debug("Listing document types", url=url)
        return list(self._list_all(url))

    def list_tags(self) -> list[dict]:
        """
        List all tags in Paperless.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/tags/?page_size=100"
        log.debug("Listing tags", url=url)
        return list(self._list_all(url))

    def create_correspondent(
        self, name: str, matching_algorithm: str | int | None = "none"
    ) -> dict:
        """
        Create a new correspondent and return the created object.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/correspondents/"
        return self._create_named_item(
            url=url,
            name=name,
            matching_algorithm=matching_algorithm,
            item_label="correspondent",
        )

    def create_document_type(
        self, name: str, matching_algorithm: str | int | None = "none"
    ) -> dict:
        """
        Create a new document type and return the created object.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/document_types/"
        return self._create_named_item(
            url=url,
            name=name,
            matching_algorithm=matching_algorithm,
            item_label="document type",
        )

    def create_tag(self, name: str, matching_algorithm: str | int | None = "none") -> dict:
        """
        Create a new tag and return the created object.
        """
        url = f"{self.settings.PAPERLESS_URL}/api/tags/"
        return self._create_named_item(
            url=url,
            name=name,
            matching_algorithm=matching_algorithm,
            item_label="tag",
        )

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()
