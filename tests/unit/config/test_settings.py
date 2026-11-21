"""Tests for the multi-spec retrieval settings in common.config.Settings."""

from __future__ import annotations

import os
from unittest.mock import patch

from common.config import Settings


_MINIMAL_ENV: dict[str, str] = {
    "PAPERLESS_TOKEN": "test-token",
    "OPENAI_API_KEY": "test-api-key",
}


def _make_settings(**overrides: str) -> Settings:
    """Build a real Settings from the minimal valid environment plus *overrides*."""
    env = {**_MINIMAL_ENV, **overrides}
    with patch.dict(os.environ, env, clear=True):
        return Settings.from_environment()


class TestSearchPlannerMaxSpecs:
    def test_default_is_eight(self) -> None:
        settings = _make_settings()
        assert settings.SEARCH_PLANNER_MAX_SPECS == 8

    def test_env_override(self) -> None:
        settings = _make_settings(SEARCH_PLANNER_MAX_SPECS="5")
        assert settings.SEARCH_PLANNER_MAX_SPECS == 5

    def test_zero_clamps_to_one(self) -> None:
        settings = _make_settings(SEARCH_PLANNER_MAX_SPECS="0")
        assert settings.SEARCH_PLANNER_MAX_SPECS == 1

    def test_negative_clamps_to_one(self) -> None:
        settings = _make_settings(SEARCH_PLANNER_MAX_SPECS="-3")
        assert settings.SEARCH_PLANNER_MAX_SPECS == 1


class TestSearchPerSpecK:
    def test_default_equals_search_top_k_when_unset(self) -> None:
        # SEARCH_TOP_K defaults to 10; SEARCH_PER_SPEC_K must mirror it.
        settings = _make_settings()
        assert settings.SEARCH_PER_SPEC_K == settings.SEARCH_TOP_K

    def test_default_tracks_explicit_search_top_k(self) -> None:
        settings = _make_settings(SEARCH_TOP_K="20")
        assert settings.SEARCH_PER_SPEC_K == 20

    def test_env_override_independent_of_top_k(self) -> None:
        settings = _make_settings(SEARCH_TOP_K="10", SEARCH_PER_SPEC_K="15")
        assert settings.SEARCH_PER_SPEC_K == 15
        assert settings.SEARCH_TOP_K == 10

    def test_zero_clamps_to_one(self) -> None:
        settings = _make_settings(SEARCH_PER_SPEC_K="0")
        assert settings.SEARCH_PER_SPEC_K == 1

    def test_negative_clamps_to_one(self) -> None:
        settings = _make_settings(SEARCH_PER_SPEC_K="-1")
        assert settings.SEARCH_PER_SPEC_K == 1


class TestSearchMaxChunksPerDoc:
    def test_default_is_three(self) -> None:
        settings = _make_settings()
        assert settings.SEARCH_MAX_CHUNKS_PER_DOC == 3

    def test_env_override(self) -> None:
        settings = _make_settings(SEARCH_MAX_CHUNKS_PER_DOC="7")
        assert settings.SEARCH_MAX_CHUNKS_PER_DOC == 7

    def test_zero_clamps_to_one(self) -> None:
        settings = _make_settings(SEARCH_MAX_CHUNKS_PER_DOC="0")
        assert settings.SEARCH_MAX_CHUNKS_PER_DOC == 1

    def test_negative_clamps_to_one(self) -> None:
        settings = _make_settings(SEARCH_MAX_CHUNKS_PER_DOC="-5")
        assert settings.SEARCH_MAX_CHUNKS_PER_DOC == 1
