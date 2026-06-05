"""Process-lifetime cache of parameters each model has rejected.

A model (or the API serving it) rejects parameters it does not understand —
OpenAI's GPT-5 series rejects ``temperature``; an Ollama-served model may
reject ``response_format``. Which parameters a model rejects is a property of
the model/API, **not** of any caller, so the cache is one process-wide
singleton shared by every daemon worker: OCR, classifier, planner, and
synthesiser all learn a given model's incompatibilities at most once per
process.

``model_compat_cache`` is the module singleton, mirroring ``llm_limiter`` in
:mod:`common.concurrency`. It is the documented lock-owning singleton that
CODE_GUIDELINES §8.5 sanctions — a module-level mutable guarded by an internal
:class:`threading.Lock`, required because the discovery made by one worker
thread must be visible to all the others.
"""

from __future__ import annotations

import threading


class ModelCompatCache:
    """Maps each model name to the set of parameters it has rejected.

    Thread-safe: the daemons fan documents across worker pools, so reads and
    writes are guarded by an internal lock. The cache is bounded by the small
    strippable-parameter registry — a model can reject at most a handful of
    parameter names — so it never needs eviction.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rejected: dict[str, set[str]] = {}

    def rejected_params_for(self, model: str) -> frozenset[str]:
        """Return the parameters *model* has rejected so far (possibly empty)."""
        with self._lock:
            return frozenset(self._rejected.get(model, set()))

    def record_rejected(self, model: str, param: str) -> None:
        """Record that *model* rejected *param*. Idempotent (set semantics)."""
        with self._lock:
            self._rejected.setdefault(model, set()).add(param)

    def reset(self) -> None:
        """Clear every recorded rejection. For test isolation only."""
        with self._lock:
            self._rejected.clear()


model_compat_cache = ModelCompatCache()
