"""OCR daemon: transcribes Paperless-ngx document pages with a vision model.

A tag-driven processing daemon (CODE_GUIDELINES §2.3). It polls Paperless for
documents carrying the OCR queue tag, rasterises each into page images,
transcribes every page through a vision-capable LLM with model fallback,
assembles the per-page text into one document body, and writes it back —
swapping the queue tag for the done tag, or applying the error tag on failure.

Allowed dependencies: ``common`` only. The daemon is stateless — all of its
state lives in Paperless-ngx tags — so it is safe to run as multiple instances.

Forbidden: imports from ``store``, ``indexer``, ``search``, or ``classifier``;
any ``sqlite3`` import; FastAPI. Outbound I/O goes through the shared clients —
Paperless HTTP through ``common.paperless``, LLM calls through ``common.llm``.
"""
