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
