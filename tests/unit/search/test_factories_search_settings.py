"""Guard: make_search_settings carries the Area-3 SEARCH_* defaults.

A MagicMock auto-creates any attribute as a truthy mock, so the new
flag/numeric settings must be set explicitly or downstream search tests
silently misbehave (CODE_GUIDELINES §11.5).
"""

from __future__ import annotations

from tests.helpers.factories import make_search_settings


def test_cache_is_off_by_default_in_the_factory() -> None:
    settings = make_search_settings()
    assert settings.SEARCH_CACHE_TTL_SECONDS == 0


def test_skip_flags_are_false_by_default() -> None:
    settings = make_search_settings()
    assert settings.SEARCH_SKIP_PLANNER_FOR_TRIVIAL is False


def test_reasoning_effort_is_a_concrete_value() -> None:
    settings = make_search_settings()
    assert settings.SEARCH_PLANNER_REASONING_EFFORT == "medium"
    assert settings.SEARCH_ANSWER_REASONING_EFFORT == "medium"


def test_llm_provider_is_openai_so_response_format_is_built() -> None:
    settings = make_search_settings()
    assert settings.LLM_PROVIDER == "openai"


def test_planner_taxonomy_limit_defaults_to_100() -> None:
    settings = make_search_settings()
    assert settings.SEARCH_PLANNER_TAXONOMY_LIMIT == 100


def test_overrides_still_win() -> None:
    settings = make_search_settings(SEARCH_CACHE_TTL_SECONDS=14400)
    assert settings.SEARCH_CACHE_TTL_SECONDS == 14400
