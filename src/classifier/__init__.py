"""Classifier daemon: enriches Paperless-ngx document metadata with an LLM.

A tag-driven processing daemon (CODE_GUIDELINES §2.3). It polls Paperless for
documents carrying the classification queue tag, sends the OCR text (truncated
to a budget) to an LLM with the existing taxonomy as context, and applies the
returned title, correspondent, document type, date, language, tags, and person
field back to Paperless — swapping the queue tag for the done tag, requeueing
for OCR when there is no content, or applying the error tag on failure.

Allowed dependencies: ``common`` only. The daemon is stateless — all of its
state lives in Paperless-ngx tags — so it is safe to run as multiple instances.

Forbidden: imports from ``store``, ``indexer``, ``search``, or ``ocr``; any
``sqlite3`` import; FastAPI. Outbound I/O goes through the shared clients —
Paperless HTTP through ``common.paperless``, LLM calls through ``common.llm``.
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
