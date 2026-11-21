"""Per-document Paperless client lifecycle for the OCR and classifier daemons.

:class:`~common.paperless.PaperlessClient` is not thread-safe, so each document
processed on the pool gets its own client.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Protocol

from .config import Settings
from .paperless import PaperlessClient


class WriteBackOutcome(Enum):
    """How a processor's result write-back ended, fed to the circuit breaker.

    ``SAVED`` resets the breaker's failure streak and ``QUARANTINED`` extends
    it. ``process()`` returns ``None`` when nothing was written back (a skipped,
    requeued or already-errored document), which the breaker ignores.
    """

    #: The result was written back to Paperless successfully.
    SAVED = "saved"
    #: Paperless rejected the write permanently (a 4xx); the document was
    #: error-tagged so it leaves the queue instead of looping.
    QUARANTINED = "quarantined"


class DocumentProcessor(Protocol):
    """A per-document processor (the OCR or classification processor)."""

    def process(self) -> WriteBackOutcome | None:
        """Run the full per-document workflow, reporting the write-back outcome."""
        ...


def run_per_document(
    doc: dict,
    settings: Settings,
    build_processor: Callable[[dict, PaperlessClient], DocumentProcessor],
) -> WriteBackOutcome | None:
    """Process one document with its own Paperless client, closed afterwards.

    *build_processor* builds the daemon's processor from the document and the
    new client; the processor's write-back outcome is returned.
    """
    # httpx sessions are not thread-safe, so every thread needs its own client.
    paperless = PaperlessClient(settings)
    try:
        return build_processor(doc, paperless).process()
    finally:
        paperless.close()
