"""Process-wide cache of the parameters each model has rejected.

Rejection is a property of the model, not the caller (GPT-5 rejects
``temperature``; some Ollama models reject ``response_format``), so one shared
singleton lets every worker thread learn it at most once per process.
"""

from __future__ import annotations

import threading


class ModelCompatCache:
    """Thread-safe map of model name to the parameters it has rejected.

    Bounded by the small strippable-parameter registry, so it needs no eviction.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rejected: dict[str, set[str]] = {}

    def rejected_params_for(self, model: str) -> frozenset[str]:
        """Return the parameters *model* has rejected so far (possibly empty)."""
        with self._lock:
            return frozenset(self._rejected.get(model, set()))

    def record_rejected(self, model: str, param: str) -> None:
        """Record that *model* rejected *param*. Idempotent."""
        with self._lock:
            self._rejected.setdefault(model, set()).add(param)

    def reset(self) -> None:
        """Clear every recorded rejection. For test isolation only."""
        with self._lock:
            self._rejected.clear()


model_compat_cache = ModelCompatCache()
