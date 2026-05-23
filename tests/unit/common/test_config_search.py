"""Tests for common.config — search-server settings.

Split from test_config.py to stay within the §3.1 500-line ceiling.
Covers: SEARCH_TOP_K, SEARCH_MAX_REFINEMENTS, SEARCH_PLANNER_MODEL,
SEARCH_ANSWER_MODEL, SEARCH_SERVER_HOST/PORT, SEARCH_SESSION_TTL,
SEARCH_MAX_CONCURRENT — for both openai and ollama providers.
"""

from __future__ import annotations

import os

import pytest

from common.config import Settings

_MINIMAL_ENV = {
    "PAPERLESS_TOKEN": "tok-123",
    "OPENAI_API_KEY": "sk-test",
}

_MINIMAL_OLLAMA_ENV = {
    "PAPERLESS_TOKEN": "tok-123",
    "OPENAI_API_KEY": "sk-test",
    "LLM_PROVIDER": "ollama",
}


def _build(mocker, env: dict[str, str]) -> Settings:
    """Build Settings with *only* the supplied env vars."""
    mocker.patch.dict(os.environ, env, clear=True)
    return Settings.from_environment()


_SEARCH_DEFAULTS_OPENAI = [
    ("SEARCH_TOP_K", 10),
    ("SEARCH_MAX_REFINEMENTS", 1),
    ("SEARCH_PLANNER_MODEL", "gpt-5.4-mini"),
    ("SEARCH_ANSWER_MODEL", "gpt-5.4"),
    ("SEARCH_SERVER_HOST", "0.0.0.0"),
    ("SEARCH_SERVER_PORT", 8080),
    ("SEARCH_SESSION_TTL", 604800),
    ("SEARCH_MAX_CONCURRENT", 4),
]


class TestSearchSettingsDefaultsOpenAI:
    """Search settings load correct defaults for the openai provider."""

    @pytest.mark.parametrize(
        "attr, expected",
        _SEARCH_DEFAULTS_OPENAI,
        ids=[a for a, _ in _SEARCH_DEFAULTS_OPENAI],
    )
    def test_default_value(self, mocker, attr, expected):
        s = _build(mocker, _MINIMAL_ENV)
        assert getattr(s, attr) == expected


class TestSearchSettingsDefaultsOllama:
    """Provider-aware model defaults switch when LLM_PROVIDER=ollama."""

    def test_planner_model_defaults_to_gemma3_12b(self, mocker):
        s = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert s.SEARCH_PLANNER_MODEL == "gemma3:12b"

    def test_answer_model_defaults_to_gemma3_27b(self, mocker):
        s = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert s.SEARCH_ANSWER_MODEL == "gemma3:27b"


_SEARCH_CUSTOM = [
    ("SEARCH_TOP_K", "20", "SEARCH_TOP_K", 20),
    ("SEARCH_MAX_REFINEMENTS", "3", "SEARCH_MAX_REFINEMENTS", 3),
    ("SEARCH_PLANNER_MODEL", "gpt-4o-mini", "SEARCH_PLANNER_MODEL", "gpt-4o-mini"),
    ("SEARCH_ANSWER_MODEL", "gpt-4o", "SEARCH_ANSWER_MODEL", "gpt-4o"),
    ("SEARCH_SERVER_HOST", "127.0.0.1", "SEARCH_SERVER_HOST", "127.0.0.1"),
    ("SEARCH_SERVER_PORT", "9090", "SEARCH_SERVER_PORT", 9090),
    ("SEARCH_SESSION_TTL", "86400", "SEARCH_SESSION_TTL", 86400),
    ("SEARCH_MAX_CONCURRENT", "8", "SEARCH_MAX_CONCURRENT", 8),
]


class TestSearchSettingsCustom:
    """Search settings parse set values correctly."""

    @pytest.mark.parametrize(
        "env_key, env_val, attr, expected",
        _SEARCH_CUSTOM,
        ids=[e[0] for e in _SEARCH_CUSTOM],
    )
    def test_custom_value(self, mocker, env_key, env_val, attr, expected):
        s = _build(mocker, {**_MINIMAL_ENV, env_key: env_val})
        assert getattr(s, attr) == expected


class TestSearchSettingsInvalidInts:
    """Non-integer values for integer search settings raise a contextful ValueError."""

    @pytest.mark.parametrize(
        "env_key",
        [
            "SEARCH_TOP_K",
            "SEARCH_MAX_REFINEMENTS",
            "SEARCH_SERVER_PORT",
            "SEARCH_SESSION_TTL",
            "SEARCH_MAX_CONCURRENT",
        ],
    )
    def test_non_integer_raises(self, mocker, env_key):
        # The message must name the offending variable (CODE_GUIDELINES §6.6).
        with pytest.raises(ValueError, match=f"{env_key} must be an integer"):
            _build(mocker, {**_MINIMAL_ENV, env_key: "not-an-int"})


class TestSearchSettingsBounds:
    """Out-of-range integer search settings raise a contextful ValueError."""

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_search_top_k_must_be_positive(self, mocker, value):
        with pytest.raises(ValueError, match="SEARCH_TOP_K must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, "SEARCH_TOP_K": value})

    def test_search_max_refinements_ceiling_value_is_accepted(self, mocker):
        # 3 is the §14.3 three-LLM-call ceiling — the boundary, still valid.
        s = _build(mocker, {**_MINIMAL_ENV, "SEARCH_MAX_REFINEMENTS": "3"})
        assert s.SEARCH_MAX_REFINEMENTS == 3

    def test_search_max_refinements_zero_is_accepted(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "SEARCH_MAX_REFINEMENTS": "0"})
        assert s.SEARCH_MAX_REFINEMENTS == 0

    @pytest.mark.parametrize("value", ["4", "10", "-1"])
    def test_search_max_refinements_out_of_range_raises(self, mocker, value):
        # Above the §14.3 ceiling (or negative) — a hard correctness bound.
        with pytest.raises(ValueError, match="SEARCH_MAX_REFINEMENTS must be"):
            _build(mocker, {**_MINIMAL_ENV, "SEARCH_MAX_REFINEMENTS": value})

    @pytest.mark.parametrize("value", ["0", "65536", "-1", "99999"])
    def test_search_server_port_out_of_range_raises(self, mocker, value):
        with pytest.raises(ValueError, match="SEARCH_SERVER_PORT must be"):
            _build(mocker, {**_MINIMAL_ENV, "SEARCH_SERVER_PORT": value})

    @pytest.mark.parametrize("value", ["1", "65535"])
    def test_search_server_port_boundary_values_accepted(self, mocker, value):
        s = _build(mocker, {**_MINIMAL_ENV, "SEARCH_SERVER_PORT": value})
        assert s.SEARCH_SERVER_PORT == int(value)

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_search_session_ttl_must_be_positive(self, mocker, value):
        with pytest.raises(ValueError, match="SEARCH_SESSION_TTL must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, "SEARCH_SESSION_TTL": value})

    @pytest.mark.parametrize("value", ["-1", "-8"])
    def test_search_max_concurrent_clamped_to_zero(self, mocker, value):
        s = _build(mocker, {**_MINIMAL_ENV, "SEARCH_MAX_CONCURRENT": value})
        assert s.SEARCH_MAX_CONCURRENT == 0


