"""Tests for common.model_compat — the per-model rejected-parameter cache.

The cache is a process-lifetime singleton (CODE_GUIDELINES §8.5): unsupported
parameters are a property of the model/API, not of any caller, so every daemon
worker in a process shares one cache. These tests pin the singleton's
record/get/reset contract and its thread-safety.
"""

from __future__ import annotations

import threading

import pytest

from common.model_compat import ModelCompatCache, model_compat_cache


@pytest.fixture()
def cache() -> ModelCompatCache:
    """A fresh, isolated cache instance (not the module singleton)."""
    return ModelCompatCache()


class TestRejectedParamsFor:
    def test_unknown_model_has_no_rejected_params(self, cache):
        assert cache.rejected_params_for("gpt-5.4-mini") == frozenset()

    def test_recorded_param_is_returned(self, cache):
        cache.record_rejected("gpt-5.4-mini", "temperature")
        assert cache.rejected_params_for("gpt-5.4-mini") == frozenset({"temperature"})

    def test_records_are_per_model(self, cache):
        cache.record_rejected("gpt-5.4-mini", "temperature")
        assert cache.rejected_params_for("claude-3") == frozenset()

    def test_multiple_params_accumulate(self, cache):
        cache.record_rejected("m", "temperature")
        cache.record_rejected("m", "response_format")
        assert cache.rejected_params_for("m") == frozenset(
            {"temperature", "response_format"}
        )

    def test_recording_the_same_param_twice_is_idempotent(self, cache):
        cache.record_rejected("m", "temperature")
        cache.record_rejected("m", "temperature")
        assert cache.rejected_params_for("m") == frozenset({"temperature"})


class TestModuleSingleton:
    def test_module_singleton_is_a_modelcompatcache(self):
        assert isinstance(model_compat_cache, ModelCompatCache)


class TestReset:
    def test_reset_clears_all_models(self, cache):
        cache.record_rejected("m1", "temperature")
        cache.record_rejected("m2", "response_format")
        cache.reset()
        assert cache.rejected_params_for("m1") == frozenset()
        assert cache.rejected_params_for("m2") == frozenset()

    def test_reset_on_empty_cache_is_safe(self, cache):
        cache.reset()
        assert cache.rejected_params_for("m") == frozenset()


class TestThreadSafety:
    def test_concurrent_records_do_not_corrupt_the_cache(self, cache):
        """N threads each record a distinct param for one model; all survive."""
        params = [f"param_{i}" for i in range(50)]
        barrier = threading.Barrier(len(params))
        errors: list[Exception] = []

        def record(param: str) -> None:
            try:
                barrier.wait(timeout=5)
                cache.record_rejected("shared-model", param)
            except Exception as exc:  # noqa: BLE001 - test surfaces any failure
                errors.append(exc)

        threads = [threading.Thread(target=record, args=(p,)) for p in params]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert errors == []
        assert cache.rejected_params_for("shared-model") == frozenset(params)
