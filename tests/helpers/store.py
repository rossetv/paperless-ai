"""Open a real StoreWriter or StoreReader against a temporary SQLite file."""

from __future__ import annotations

from typing import Any

from store.reader import StoreReader
from store.writer import StoreWriter
from tests.helpers.factories import DEFAULT_EMBEDDING_DIMENSIONS, make_store_settings


def open_writer(
    db_path: str,
    *,
    model: str = "test-model",
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    **overrides: Any,
) -> StoreWriter:
    """Open a real StoreWriter against the database at *db_path*."""
    return StoreWriter(
        make_store_settings(db_path, model=model, dimensions=dimensions, **overrides)
    )


def open_reader(
    db_path: str,
    *,
    model: str = "test-model",
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    **overrides: Any,
) -> StoreReader:
    """Open a real StoreReader against the database at *db_path*."""
    return StoreReader(
        make_store_settings(db_path, model=model, dimensions=dimensions, **overrides)
    )
