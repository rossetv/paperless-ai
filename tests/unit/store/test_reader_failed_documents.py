"""Tests for StoreReader.get_failed_documents — the index failed-doc list.

Covers: an empty/absent failed_documents meta key yields an empty list; a
populated map yields one FailedDocument per id with its failure count; the
document title is joined from the documents table when present and is None
when the document row is absent; a corrupt meta value yields an empty list.
"""

from __future__ import annotations

import pytest

from tests.helpers.store import open_reader, open_writer


@pytest.fixture()
def db_path(tmp_path) -> str:
    """A fresh index database path for each test."""
    path = str(tmp_path / "index.db")
    # Initialise the schema by opening (and immediately closing) a writer.
    writer = open_writer(path)
    writer.close()
    return path


def test_no_failed_documents_yields_an_empty_list(db_path: str) -> None:
    reader = open_reader(db_path)
    try:
        assert reader.get_failed_documents() == []
    finally:
        reader.close()


def test_failed_documents_are_listed_with_their_counts(db_path: str) -> None:
    # Write the failed-documents map directly into index.db meta.
    writer = open_writer(db_path)
    try:
        writer.write_meta("failed_documents", '{"7": 2, "9": 5}')
    finally:
        writer.close()

    reader = open_reader(db_path)
    try:
        failed = reader.get_failed_documents()
    finally:
        reader.close()

    by_id = {f.document_id: f for f in failed}
    assert set(by_id) == {7, 9}
    assert by_id[7].failure_count == 2
    assert by_id[9].failure_count == 5


def test_title_is_none_when_the_document_row_is_absent(db_path: str) -> None:
    """A failed id with no documents row still appears — title is None."""
    writer = open_writer(db_path)
    try:
        writer.write_meta("failed_documents", '{"42": 1}')
    finally:
        writer.close()

    reader = open_reader(db_path)
    try:
        failed = reader.get_failed_documents()
    finally:
        reader.close()

    assert len(failed) == 1
    assert failed[0].document_id == 42
    assert failed[0].title is None


def test_a_corrupt_failed_documents_value_yields_an_empty_list(db_path: str) -> None:
    writer = open_writer(db_path)
    try:
        writer.write_meta("failed_documents", "not-json")
    finally:
        writer.close()

    reader = open_reader(db_path)
    try:
        assert reader.get_failed_documents() == []
    finally:
        reader.close()
