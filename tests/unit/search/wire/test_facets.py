"""Tests for the facets/taxonomy wire models in search.wire.facets.

Covers the length bounds on TaxonomyCreateRequest.name (L17): the name is
forwarded verbatim to Paperless, so an empty or over-255-character name is
rejected at the boundary rather than creating a blank or oversized entry.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from search.wire import TaxonomyCreateRequest


def test_taxonomy_create_accepts_a_normal_name() -> None:
    body = TaxonomyCreateRequest(name="Acme Corp")
    assert body.name == "Acme Corp"


def test_taxonomy_create_accepts_a_255_char_name() -> None:
    body = TaxonomyCreateRequest(name="x" * 255)
    assert body.name == "x" * 255


def test_taxonomy_create_rejects_an_empty_name() -> None:
    """A blank taxonomy name is rejected — never forwarded to Paperless."""
    with pytest.raises(ValidationError):
        TaxonomyCreateRequest(name="")


def test_taxonomy_create_rejects_an_overlong_name() -> None:
    with pytest.raises(ValidationError):
        TaxonomyCreateRequest(name="x" * 256)
