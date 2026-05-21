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
from typing import Protocol

from .config import Settings
from .paperless import PaperlessClient


class DocumentProcessor(Protocol):
    """A per-document processor: something with a ``process()`` method.

    Both :class:`ocr.worker.OcrProcessor` and
    :class:`classifier.worker.ClassificationProcessor` satisfy this; the
    protocol lets :func:`run_per_document` stay agnostic of which daemon it
    serves.
    """

    def process(self) -> None:
        """Run the full per-document workflow."""
        ...


def run_per_document(
    doc: dict,
    settings: Settings,
    build_processor: Callable[[dict, PaperlessClient], DocumentProcessor],
) -> None:
    """Process one document under a fresh, per-thread Paperless client.

    Constructs a :class:`PaperlessClient`, hands it to *build_processor* to
    assemble the daemon-specific processor, runs the processor, and closes the
    client — even when processing raises.

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
        build_processor(doc, paperless).process()
    finally:
        paperless.close()
