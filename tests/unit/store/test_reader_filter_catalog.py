"""Tests for StoreReader.list_filters_with_counts."""

from __future__ import annotations

from tests.helpers.store import open_reader


def test_list_filters_with_counts_reports_accurate_counts(populated_db: str) -> None:
    reader = open_reader(populated_db)
    catalog = reader.list_filters_with_counts()
    reader.close()

    corr = {f.name: f.count for f in catalog.correspondents}
    assert corr == {"Alpha Corp": 1, "Beta Ltd": 1}

    types = {f.name: f.count for f in catalog.document_types}
    # "Invoice" is on document 1 only.
    assert types["Invoice"] == 1

    tags = {f.name: f.count for f in catalog.tags}
    # Tag 102 ("scanned") is on both documents; 101 ("important") on doc 1 only.
    assert tags["scanned"] == 2
    assert tags["important"] == 1

    # Every facet carries the id needed to filter.
    assert all(f.id for f in catalog.correspondents)


def test_list_filters_with_counts_reports_date_range(populated_db: str) -> None:
    reader = open_reader(populated_db)
    catalog = reader.list_filters_with_counts()
    reader.close()

    assert catalog.earliest == "2023-01-01T00:00:00+00:00"
    assert catalog.latest == "2024-06-15T00:00:00+00:00"


def test_list_filters_with_counts_zero_for_unused_taxonomy(db_path: str) -> None:
    from store.models import TaxonomyEntry
    from tests.helpers.store import open_writer

    writer = open_writer(db_path)
    writer.refresh_taxonomy(
        [TaxonomyEntry(kind="correspondent", id=99, name="Unused Corp")]
    )
    writer.close()

    reader = open_reader(db_path)
    catalog = reader.list_filters_with_counts()
    reader.close()

    corr = {f.name: f.count for f in catalog.correspondents}
    assert corr == {"Unused Corp": 0}
