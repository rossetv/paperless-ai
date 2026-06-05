"""Per-thread Paperless client lifecycle for the tag-driven daemons.

The OCR and classifier daemons fan documents across a thread pool and process
each one with its own :class:`~common.paperless.PaperlessClient` — the client
is not thread-safe (CODE_GUIDELINES §8.3), so a per-document client is the
contract, not an optimisation. :func:`run_per_document` owns that
construct-process-close lifecycle once, so each daemon's per-document function
collapses to a single call.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Protocol

from .config import Settings
from .paperless import PaperlessClient


class WriteBackOutcome(Enum):
    """What a processor did with its token-costly result when it wrote back.

    The daemon feeds this to the write-back circuit breaker
    (:class:`common.circuit_breaker.WriteBackCircuitBreaker`): a ``SAVED`` resets
    the failure streak, a ``QUARANTINED`` extends it. ``process()`` returns
    ``None`` for a cycle that did no result write-back at all — a skipped,
    requeued, or already-errored document — which the breaker ignores.
    """

    #: The result was written back to Paperless successfully.
    SAVED = "saved"
    #: Paperless rejected the write permanently (a 4xx); the document was
    #: error-tagged so it leaves the queue instead of looping.
    QUARANTINED = "quarantined"


class DocumentProcessor(Protocol):
    """A per-document processor: something with a ``process()`` method.

    Both :class:`ocr.worker.OcrProcessor` and
    :class:`classifier.worker.ClassificationProcessor` satisfy this; the
    protocol lets :func:`run_per_document` stay agnostic of which daemon it
    serves.
    """

    def process(self) -> WriteBackOutcome | None:
        """Run the full per-document workflow, reporting the write-back outcome."""
        ...


def run_per_document(
    doc: dict,
    settings: Settings,
    build_processor: Callable[[dict, PaperlessClient], DocumentProcessor],
) -> WriteBackOutcome | None:
    """Process one document under a fresh, per-thread Paperless client.

    Constructs a :class:`PaperlessClient`, hands it to *build_processor* to
    assemble the daemon-specific processor, runs the processor, and closes the
    client — even when processing raises. Returns the processor's write-back
    outcome so the daemon can drive the circuit breaker.

    Args:
        doc: The Paperless document dict to process.
        settings: The loaded application settings.
        build_processor: A callable that, given the document and the freshly
            constructed client, returns the processor to run.
    """
    # Each thread gets its own PaperlessClient (and thus its own HTTP session)
    # because httpx sessions are not thread-safe (CODE_GUIDELINES §8.3).
    paperless = PaperlessClient(settings)
    try:
        return build_processor(doc, paperless).process()
    finally:
        paperless.close()
