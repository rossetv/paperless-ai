"""Indexer package — the write side of the semantic search subsystem.

This package contains the reconciliation daemon that keeps the SQLite search
store in sync with Paperless-ngx: it chunks new and changed documents, embeds
the chunks via ``common.embeddings``, and upserts them into the store via
``store.StoreWriter``.

Allowed dependencies: ``store/`` (write API), ``common/``.
Forbidden: no ``search/`` imports, no FastAPI, no direct ``sqlite3`` usage.
"""
