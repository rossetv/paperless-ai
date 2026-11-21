"""Indexer: keeps the SQLite search store in sync with Paperless-ngx.

It chunks new and changed documents, embeds the chunks and upserts them into the
store.
"""
