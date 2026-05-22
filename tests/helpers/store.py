"""Helpers for constructing real store objects against a temporary database.

The store unit and integration tests all open a real :class:`~store.writer.StoreWriter`
or :class:`~store.reader.StoreReader` against a ``tmp_path`` SQLite file.  These
two helpers are the single wiring point — they build the Settings mock through
:func:`tests.helpers.factories.make_store_settings`, so no test re-hand-rolls
the store Settings shape (CODE_GUIDELINES §11.5).
"""

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
    """Open a real StoreWriter against the database at *db_path*.

    Args:
        db_path: Filesystem path for the index database (usually ``tmp_path``).
        model: The ``EMBEDDING_MODEL`` the writer records and compares.
        dimensions: The ``EMBEDDING_DIMENSIONS`` the writer records.
        **overrides: Any further Settings field overrides.
    """
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
    """Open a real StoreReader against the database at *db_path*.

    Args:
        db_path: Filesystem path for the index database (usually ``tmp_path``).
        model: The ``EMBEDDING_MODEL`` Settings value.
        dimensions: The ``EMBEDDING_DIMENSIONS`` Settings value.
        **overrides: Any further Settings field overrides.
    """
    return StoreReader(
        make_store_settings(db_path, model=model, dimensions=dimensions, **overrides)
    )
