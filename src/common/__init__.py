"""Shared infrastructure for every daemon and the search side.

Must not import from ``store``, ``ocr``, ``classifier``, ``indexer`` or
``search``; ``appdb`` is the only project package it may use.
"""

from __future__ import annotations

from .config import Settings
from .paperless import PaperlessClient

__all__ = [
    "PaperlessClient",
    "Settings",
]
