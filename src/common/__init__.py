"""Shared building blocks for the OCR and classification daemons."""

from __future__ import annotations

from .config import Settings
from .paperless import PaperlessClient

__all__ = [
    "PaperlessClient",
    "Settings",
]
