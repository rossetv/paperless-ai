"""
Common building blocks shared by the OCR and classification daemons.

This package contains reusable, domain-agnostic code:

- **config** — environment-variable-based settings (pure data, no side effects).
- **library_setup** — one-shot third-party library configuration (OpenAI, Pillow).
- **retry** — generic retry decorator with exponential backoff and jitter.
- **paperless** — Paperless-ngx REST API client with automatic retries.
- **utils** — text/image content helpers (blank detection, redaction markers).
- **daemon_loop** — polling + threadpool loop used by both daemon entry points.
- **logging_config** — structured logging (structlog) configuration.
- **llm** — OpenAI-compatible chat completion mixin with retries.
- **claims** — processing-lock tag claiming with race-condition mitigation.
- **tags** — tag extraction, hygiene, and pipeline-tag lifecycle helpers.
"""
