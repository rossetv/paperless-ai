"""Classifier daemon: enriches Paperless-ngx document metadata with an LLM.

Polls for documents carrying the classification queue tag and writes back the
title, correspondent, type, date, language, tags and person the LLM returns. All
state lives in Paperless tags, so several instances can run side by side.
"""

from __future__ import annotations

from .provider import ClassificationProvider
from .result import ClassificationResult, parse_classification_response
from .taxonomy import TaxonomyCache
from .worker import ClassificationProcessor

__all__ = [
    "ClassificationProcessor",
    "ClassificationProvider",
    "ClassificationResult",
    "TaxonomyCache",
    "parse_classification_response",
]
