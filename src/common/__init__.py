"""
Common building blocks shared by the OCR and classification daemons.

This package contains reusable, domain-agnostic code:

- **bootstrap** — shared daemon startup sequence (config → logging → preflight).
- **claims** — processing-lock tag claiming with race-condition mitigation.
- **concurrency** — bounded semaphore for LLM call limiting.
- **config** — environment-variable-based settings (pure data, no side effects).
- **daemon_loop** — polling + threadpool loop used by both daemon entry points.
- **library_setup** — one-shot third-party library configuration (OpenAI, Pillow).
- **llm** — OpenAI-compatible chat completion mixin with retries.
- **logging_config** — structured logging (structlog) configuration.
- **paperless** — Paperless-ngx REST API client with automatic retries.
- **preflight** — startup health checks (Paperless reachable, tags exist, LLM up).
- **retry** — generic retry decorator with exponential backoff and jitter.
- **shutdown** — graceful shutdown coordinator (SIGTERM / SIGINT).
- **stale_lock** — stale processing-lock tag recovery on daemon restart.
- **tags** — tag extraction, hygiene, and pipeline-tag lifecycle helpers.
- **utils** — text/image content helpers (blank detection, redaction markers).
"""
