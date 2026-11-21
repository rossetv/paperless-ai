"""Tests for common.config search-server settings."""

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
    ("SEARCH_PLANNER_MODEL", "gpt-5.6-terra"),
    ("SEARCH_ANSWER_MODEL", "gpt-5.6-terra"),
    ("SEARCH_SERVER_HOST", "0.0.0.0"),
    ("SEARCH_SERVER_PORT", 8080),
    ("SEARCH_FORWARDED_ALLOW_IPS", "*"),
    ("SEARCH_SESSION_TTL", 604800),
    ("SEARCH_MAX_CONCURRENT", 4),
]


class TestSearchSettingsDefaultsOpenAI:
    @pytest.mark.parametrize(
        "attr, expected",
        _SEARCH_DEFAULTS_OPENAI,
        ids=[a for a, _ in _SEARCH_DEFAULTS_OPENAI],
    )
    def test_default_value(self, mocker, attr, expected):
        s = _build(mocker, _MINIMAL_ENV)
        assert getattr(s, attr) == expected


class TestSearchSettingsDefaultsOllama:
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
    (
        "SEARCH_FORWARDED_ALLOW_IPS",
        "10.0.0.0/8",
        "SEARCH_FORWARDED_ALLOW_IPS",
        "10.0.0.0/8",
    ),
    ("SEARCH_SESSION_TTL", "86400", "SEARCH_SESSION_TTL", 86400),
    ("SEARCH_MAX_CONCURRENT", "8", "SEARCH_MAX_CONCURRENT", 8),
]


class TestSearchSettingsCustom:
    @pytest.mark.parametrize(
        "env_key, env_val, attr, expected",
        _SEARCH_CUSTOM,
        ids=[e[0] for e in _SEARCH_CUSTOM],
    )
    def test_custom_value(self, mocker, env_key, env_val, attr, expected):
        s = _build(mocker, {**_MINIMAL_ENV, env_key: env_val})
        assert getattr(s, attr) == expected


class TestSearchSettingsInvalidInts:
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
        with pytest.raises(ValueError, match=f"{env_key} must be an integer"):
            _build(mocker, {**_MINIMAL_ENV, env_key: "not-an-int"})


class TestSearchSettingsBounds:
    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_search_top_k_must_be_positive(self, mocker, value):
        with pytest.raises(ValueError, match="SEARCH_TOP_K must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, "SEARCH_TOP_K": value})

    def test_search_max_refinements_high_value_is_accepted(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "SEARCH_MAX_REFINEMENTS": "20"})
        assert s.SEARCH_MAX_REFINEMENTS == 20

    def test_search_max_refinements_zero_is_accepted(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "SEARCH_MAX_REFINEMENTS": "0"})
        assert s.SEARCH_MAX_REFINEMENTS == 0

    @pytest.mark.parametrize("value", ["-1", "-5"])
    def test_search_max_refinements_negative_raises(self, mocker, value):
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


class TestSearchRagCostSettings:
    def test_reasoning_effort_defaults(self, mocker) -> None:
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.SEARCH_PLANNER_REASONING_EFFORT == "medium"
        assert settings.SEARCH_ANSWER_REASONING_EFFORT == "medium"
        assert settings.SEARCH_CACHE_TTL_SECONDS == 14400
        assert settings.SEARCH_SKIP_PLANNER_FOR_TRIVIAL is False

    def test_overrides_win(self, mocker) -> None:
        # Not the "medium" default, so the override is observable.
        settings = _build(
            mocker,
            {
                **_MINIMAL_ENV,
                "SEARCH_PLANNER_REASONING_EFFORT": "high",
                "SEARCH_ANSWER_REASONING_EFFORT": "low",
                "SEARCH_CACHE_TTL_SECONDS": "0",
                "SEARCH_SKIP_PLANNER_FOR_TRIVIAL": "true",
            },
        )
        assert settings.SEARCH_PLANNER_REASONING_EFFORT == "high"
        assert settings.SEARCH_ANSWER_REASONING_EFFORT == "low"
        assert settings.SEARCH_CACHE_TTL_SECONDS == 0
        assert settings.SEARCH_SKIP_PLANNER_FOR_TRIVIAL is True

    def test_invalid_reasoning_effort_fails_closed(self, mocker) -> None:
        with pytest.raises(ValueError, match="SEARCH_PLANNER_REASONING_EFFORT"):
            _build(
                mocker,
                {**_MINIMAL_ENV, "SEARCH_PLANNER_REASONING_EFFORT": "ludicrous"},
            )

    def test_negative_cache_ttl_clamps_to_zero(self, mocker) -> None:
        settings = _build(mocker, {**_MINIMAL_ENV, "SEARCH_CACHE_TTL_SECONDS": "-5"})
        assert settings.SEARCH_CACHE_TTL_SECONDS == 0


class TestSearchFailFastGateDefaults:
    def test_planner_model_defaults_to_gpt_5_6_terra_for_openai(self, mocker) -> None:
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.SEARCH_PLANNER_MODEL == "gpt-5.6-terra"

    def test_gate_adequacy_defaults_true(self, mocker) -> None:
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.SEARCH_GATE_ADEQUACY is True

    def test_gate_relevance_defaults_true(self, mocker) -> None:
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.SEARCH_GATE_RELEVANCE is True

    def test_min_query_chars_defaults_to_two(self, mocker) -> None:
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.SEARCH_MIN_QUERY_CHARS == 2

    def test_relevance_min_similarity_defaults_to_calibrated_floor(
        self, mocker
    ) -> None:
        """0.60 sits between off-topic and genuine matches."""
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.SEARCH_RELEVANCE_MIN_SIMILARITY == 0.60


class TestSearchFailFastGateOverrides:
    def test_gate_adequacy_overridden_to_false(self, mocker) -> None:
        settings = _build(mocker, {**_MINIMAL_ENV, "SEARCH_GATE_ADEQUACY": "false"})
        assert settings.SEARCH_GATE_ADEQUACY is False

    def test_gate_relevance_overridden_to_false(self, mocker) -> None:
        settings = _build(mocker, {**_MINIMAL_ENV, "SEARCH_GATE_RELEVANCE": "false"})
        assert settings.SEARCH_GATE_RELEVANCE is False

    def test_gate_adequacy_truthy_strings_accepted(self, mocker) -> None:
        for val in ("true", "1", "yes"):
            settings = _build(mocker, {**_MINIMAL_ENV, "SEARCH_GATE_ADEQUACY": val})
            assert settings.SEARCH_GATE_ADEQUACY is True

    def test_min_query_chars_overridden(self, mocker) -> None:
        settings = _build(mocker, {**_MINIMAL_ENV, "SEARCH_MIN_QUERY_CHARS": "5"})
        assert settings.SEARCH_MIN_QUERY_CHARS == 5

    def test_relevance_min_similarity_overridden(self, mocker) -> None:
        settings = _build(
            mocker, {**_MINIMAL_ENV, "SEARCH_RELEVANCE_MIN_SIMILARITY": "0.15"}
        )
        assert settings.SEARCH_RELEVANCE_MIN_SIMILARITY == 0.15


class TestSearchFailFastGateClamping:
    def test_negative_min_query_chars_clamped_to_zero(self, mocker) -> None:
        settings = _build(mocker, {**_MINIMAL_ENV, "SEARCH_MIN_QUERY_CHARS": "-3"})
        assert settings.SEARCH_MIN_QUERY_CHARS == 0

    def test_zero_min_query_chars_accepted(self, mocker) -> None:
        """Zero opts out of the character check."""
        settings = _build(mocker, {**_MINIMAL_ENV, "SEARCH_MIN_QUERY_CHARS": "0"})
        assert settings.SEARCH_MIN_QUERY_CHARS == 0

    def test_negative_relevance_min_similarity_clamped_to_zero(self, mocker) -> None:
        settings = _build(
            mocker, {**_MINIMAL_ENV, "SEARCH_RELEVANCE_MIN_SIMILARITY": "-0.5"}
        )
        assert settings.SEARCH_RELEVANCE_MIN_SIMILARITY == 0.0

    def test_non_numeric_relevance_min_similarity_raises(self, mocker) -> None:
        with pytest.raises(ValueError, match="SEARCH_RELEVANCE_MIN_SIMILARITY"):
            _build(
                mocker, {**_MINIMAL_ENV, "SEARCH_RELEVANCE_MIN_SIMILARITY": "quite_low"}
            )

    def test_non_integer_min_query_chars_raises(self, mocker) -> None:
        with pytest.raises(
            ValueError, match="SEARCH_MIN_QUERY_CHARS must be an integer"
        ):
            _build(mocker, {**_MINIMAL_ENV, "SEARCH_MIN_QUERY_CHARS": "two"})


class TestJudgeSettings:
    def test_gate_defaults_on(self, mocker) -> None:
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.SEARCH_GATE_JUDGE is True

    def test_gate_overridable_off(self, mocker) -> None:
        settings = _build(mocker, {**_MINIMAL_ENV, "SEARCH_GATE_JUDGE": "false"})
        assert settings.SEARCH_GATE_JUDGE is False

    def test_judge_and_planner_openai_defaults(self, mocker) -> None:
        """On openai the judge does not mirror the planner model; on ollama it does."""
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.SEARCH_JUDGE_MODEL == "gpt-5.6-luna"
        assert settings.SEARCH_PLANNER_MODEL == "gpt-5.6-terra"

    def test_judge_model_defaults_to_planner_model_ollama(self, mocker) -> None:
        settings = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert settings.SEARCH_JUDGE_MODEL == "gemma3:12b"

    def test_judge_model_overridable(self, mocker) -> None:
        settings = _build(
            mocker, {**_MINIMAL_ENV, "SEARCH_JUDGE_MODEL": "gpt-5.4-nano"}
        )
        assert settings.SEARCH_JUDGE_MODEL == "gpt-5.4-nano"

    def test_reasoning_effort_defaults_to_none(self, mocker) -> None:
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.SEARCH_JUDGE_REASONING_EFFORT == "none"

    def test_reasoning_effort_overridable(self, mocker) -> None:
        settings = _build(
            mocker, {**_MINIMAL_ENV, "SEARCH_JUDGE_REASONING_EFFORT": "high"}
        )
        assert settings.SEARCH_JUDGE_REASONING_EFFORT == "high"

    def test_invalid_reasoning_effort_raises(self, mocker) -> None:
        with pytest.raises(ValueError, match="SEARCH_JUDGE_REASONING_EFFORT"):
            _build(mocker, {**_MINIMAL_ENV, "SEARCH_JUDGE_REASONING_EFFORT": "lots"})

    def test_minimal_coerces_to_none_with_warning(self, mocker) -> None:
        warn = mocker.patch("common.config._parsers.log.warning")
        settings = _build(
            mocker, {**_MINIMAL_ENV, "SEARCH_JUDGE_REASONING_EFFORT": "minimal"}
        )
        assert settings.SEARCH_JUDGE_REASONING_EFFORT == "none"
        warn.assert_any_call(
            "config.reasoning_effort_minimal_coerced",
            var_name="SEARCH_JUDGE_REASONING_EFFORT",
            coerced_to="none",
        )


class TestRelevanceTierThresholds:
    def test_defaults_are_the_calibrated_cut_points(self, mocker) -> None:
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.SEARCH_RELEVANCE_TIER_STRONG == 0.70
        assert settings.SEARCH_RELEVANCE_TIER_GOOD == 0.66
        assert settings.SEARCH_RELEVANCE_TIER_PARTIAL == 0.60

    def test_tiers_are_overridable(self, mocker) -> None:
        settings = _build(
            mocker,
            {
                **_MINIMAL_ENV,
                "SEARCH_RELEVANCE_TIER_STRONG": "0.8",
                "SEARCH_RELEVANCE_TIER_GOOD": "0.7",
                "SEARCH_RELEVANCE_TIER_PARTIAL": "0.5",
            },
        )
        assert settings.SEARCH_RELEVANCE_TIER_STRONG == 0.8
        assert settings.SEARCH_RELEVANCE_TIER_GOOD == 0.7
        assert settings.SEARCH_RELEVANCE_TIER_PARTIAL == 0.5

    def test_equal_adjacent_cut_points_are_allowed(self, mocker) -> None:
        """Equal bands collapse a tier rather than corrupt the ordering."""
        settings = _build(
            mocker,
            {
                **_MINIMAL_ENV,
                "SEARCH_RELEVANCE_TIER_STRONG": "0.70",
                "SEARCH_RELEVANCE_TIER_GOOD": "0.70",
            },
        )
        assert settings.SEARCH_RELEVANCE_TIER_GOOD == 0.70

    def test_partial_above_good_raises(self, mocker) -> None:
        with pytest.raises(ValueError, match="Relevance tiers must be ordered"):
            _build(mocker, {**_MINIMAL_ENV, "SEARCH_RELEVANCE_TIER_PARTIAL": "0.95"})

    def test_good_above_strong_raises(self, mocker) -> None:
        with pytest.raises(ValueError, match="Relevance tiers must be ordered"):
            _build(mocker, {**_MINIMAL_ENV, "SEARCH_RELEVANCE_TIER_GOOD": "0.99"})

    def test_above_range_raises_naming_the_key(self, mocker) -> None:
        with pytest.raises(
            ValueError, match="SEARCH_RELEVANCE_TIER_STRONG must be between"
        ):
            _build(mocker, {**_MINIMAL_ENV, "SEARCH_RELEVANCE_TIER_STRONG": "1.5"})

    def test_negative_tier_raises_naming_the_key(self, mocker) -> None:
        with pytest.raises(
            ValueError, match="SEARCH_RELEVANCE_TIER_PARTIAL must be between"
        ):
            _build(mocker, {**_MINIMAL_ENV, "SEARCH_RELEVANCE_TIER_PARTIAL": "-0.1"})

    def test_non_numeric_tier_raises(self, mocker) -> None:
        with pytest.raises(ValueError, match="SEARCH_RELEVANCE_TIER_GOOD"):
            _build(mocker, {**_MINIMAL_ENV, "SEARCH_RELEVANCE_TIER_GOOD": "high"})


class TestIdentityAwareSetting:
    def test_defaults_on(self, mocker) -> None:
        assert _build(mocker, _MINIMAL_ENV).SEARCH_IDENTITY_AWARE is True

    def test_overridable_off(self, mocker) -> None:
        settings = _build(mocker, {**_MINIMAL_ENV, "SEARCH_IDENTITY_AWARE": "false"})
        assert settings.SEARCH_IDENTITY_AWARE is False
