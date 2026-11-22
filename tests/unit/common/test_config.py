"""Tests for common.config core daemon settings.

Indexer and search-server settings are in test_config_index.py and
test_config_search.py.
"""

from __future__ import annotations

import os

import pytest

from common.config import Settings
from tests.helpers.factories import make_settings

_MINIMAL_ENV = {
    "PAPERLESS_TOKEN": "tok-123",
    "OPENAI_API_KEY": "sk-test",
}

# Embeddings default to openai regardless of LLM_PROVIDER, so the key stays
# required here; tests that omit it also set EMBEDDING_PROVIDER=ollama.
_MINIMAL_OLLAMA_ENV = {
    "PAPERLESS_TOKEN": "tok-123",
    "OPENAI_API_KEY": "sk-test",
    "LLM_PROVIDER": "ollama",
}


def _build(mocker, env: dict[str, str]) -> Settings:
    """Build Settings with *only* the supplied env vars."""
    mocker.patch.dict(os.environ, env, clear=True)
    return Settings.from_environment()


_SIMPLE_DEFAULTS = [
    ("PAPERLESS_URL", "http://paperless:8000"),
    ("LLM_PROVIDER", "openai"),
    ("OCR_INCLUDE_PAGE_MODELS", False),
    ("PRE_TAG_ID", 443),
    ("POST_TAG_ID", 444),
    ("OCR_PROCESSING_TAG_ID", None),
    ("CLASSIFY_POST_TAG_ID", None),
    ("CLASSIFY_PROCESSING_TAG_ID", None),
    ("ERROR_TAG_ID", 552),
    ("POLL_INTERVAL", 15),
    ("MAX_RETRIES", 3),
    ("MAX_RETRY_BACKOFF_SECONDS", 30),
    ("REQUEST_TIMEOUT", 180),
    ("LLM_MAX_CONCURRENT", 4),
    ("OCR_DPI", 300),
    ("OCR_MAX_SIDE", 1600),
    ("PAGE_WORKERS", 8),
    ("DOCUMENT_WORKERS", 4),
    ("LOG_LEVEL", "INFO"),
    ("LOG_FORMAT", "console"),
    ("CLASSIFY_PERSON_FIELD_ID", None),
    ("CLASSIFY_DEFAULT_COUNTRY_TAG", ""),
    ("CLASSIFY_MAX_CHARS", 0),
    ("CLASSIFY_MAX_TOKENS", 0),
    ("CLASSIFY_TAG_LIMIT", 5),
    ("CLASSIFY_TAXONOMY_LIMIT", 40),
    ("CLASSIFY_MAX_PAGES", 3),
    ("CLASSIFY_TAIL_PAGES", 2),
    ("CLASSIFY_HEADERLESS_CHAR_LIMIT", 15000),
    ("CLASSIFY_REASONING_EFFORT", "low"),
]


class TestDefaults:
    @pytest.mark.parametrize(
        "attr, expected", _SIMPLE_DEFAULTS, ids=[a for a, _ in _SIMPLE_DEFAULTS]
    )
    def test_default_value(self, mocker, attr, expected):
        s = _build(mocker, _MINIMAL_ENV)
        assert getattr(s, attr) == expected

    def test_ocr_and_classify_models_default_openai(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.OCR_MODELS == ["gpt-5.6-luna", "gpt-5.6-terra"]
        assert s.CLASSIFY_MODELS == ["gpt-5.6-luna", "gpt-5.6-terra"]

    def test_ocr_refusal_markers_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert "chatgpt refused to transcribe" in s.OCR_REFUSAL_MARKERS
        assert "i can't assist" in s.OCR_REFUSAL_MARKERS

    def test_classify_pre_tag_id_defaults_to_post_tag_id(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_PRE_TAG_ID == s.POST_TAG_ID

    def test_classify_reasoning_effort_defaults_to_low(self, mocker):
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.CLASSIFY_REASONING_EFFORT == "low"


_CUSTOM_ENV_VARS = [
    ("PAPERLESS_URL", "http://custom:9999", "PAPERLESS_URL", "http://custom:9999"),
    ("PRE_TAG_ID", "100", "PRE_TAG_ID", 100),
    ("POST_TAG_ID", "200", "POST_TAG_ID", 200),
    ("POLL_INTERVAL", "60", "POLL_INTERVAL", 60),
    ("MAX_RETRIES", "5", "MAX_RETRIES", 5),
    ("MAX_RETRY_BACKOFF_SECONDS", "120", "MAX_RETRY_BACKOFF_SECONDS", 120),
    ("REQUEST_TIMEOUT", "60", "REQUEST_TIMEOUT", 60),
    ("LLM_MAX_CONCURRENT", "4", "LLM_MAX_CONCURRENT", 4),
    ("OCR_DPI", "600", "OCR_DPI", 600),
    ("OCR_MAX_SIDE", "2400", "OCR_MAX_SIDE", 2400),
    ("LOG_LEVEL", "debug", "LOG_LEVEL", "DEBUG"),
    ("LOG_FORMAT", "json", "LOG_FORMAT", "json"),
    ("CLASSIFY_PERSON_FIELD_ID", "42", "CLASSIFY_PERSON_FIELD_ID", 42),
    ("CLASSIFY_DEFAULT_COUNTRY_TAG", " US ", "CLASSIFY_DEFAULT_COUNTRY_TAG", "US"),
    ("CLASSIFY_MAX_CHARS", "5000", "CLASSIFY_MAX_CHARS", 5000),
    ("CLASSIFY_MAX_TOKENS", "2048", "CLASSIFY_MAX_TOKENS", 2048),
    ("CLASSIFY_TAG_LIMIT", "10", "CLASSIFY_TAG_LIMIT", 10),
    ("CLASSIFY_TAXONOMY_LIMIT", "50", "CLASSIFY_TAXONOMY_LIMIT", 50),
    ("CLASSIFY_MAX_PAGES", "10", "CLASSIFY_MAX_PAGES", 10),
    ("CLASSIFY_TAIL_PAGES", "5", "CLASSIFY_TAIL_PAGES", 5),
    ("CLASSIFY_HEADERLESS_CHAR_LIMIT", "8000", "CLASSIFY_HEADERLESS_CHAR_LIMIT", 8000),
    ("CLASSIFY_REASONING_EFFORT", "high", "CLASSIFY_REASONING_EFFORT", "high"),
    ("CLASSIFY_REASONING_EFFORT", "low", "CLASSIFY_REASONING_EFFORT", "low"),
    ("CLASSIFY_REASONING_EFFORT", "minimal", "CLASSIFY_REASONING_EFFORT", "none"),
    ("CLASSIFY_REASONING_EFFORT", "MEDIUM", "CLASSIFY_REASONING_EFFORT", "medium"),
    ("CLASSIFY_REASONING_EFFORT", " minimal ", "CLASSIFY_REASONING_EFFORT", "none"),
    ("ERROR_TAG_ID", "999", "ERROR_TAG_ID", 999),
    ("OCR_PROCESSING_TAG_ID", "77", "OCR_PROCESSING_TAG_ID", 77),
    ("CLASSIFY_PRE_TAG_ID", "555", "CLASSIFY_PRE_TAG_ID", 555),
    ("CLASSIFY_POST_TAG_ID", "666", "CLASSIFY_POST_TAG_ID", 666),
    ("CLASSIFY_PROCESSING_TAG_ID", "777", "CLASSIFY_PROCESSING_TAG_ID", 777),
]


class TestCustomEnvVars:
    @pytest.mark.parametrize(
        "env_key, env_val, attr, expected",
        _CUSTOM_ENV_VARS,
        ids=[e[0] for e in _CUSTOM_ENV_VARS],
    )
    def test_custom_env(self, mocker, env_key, env_val, attr, expected):
        s = _build(mocker, {**_MINIMAL_ENV, env_key: env_val})
        assert getattr(s, attr) == expected

    def test_ocr_models_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_MODELS": "model-a, model-b"})
        assert s.OCR_MODELS == ["model-a", "model-b"]

    def test_classify_models_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_MODELS": "model-c"})
        assert s.CLASSIFY_MODELS == ["model-c"]


class TestMissingRequired:
    def test_missing_paperless_token(self, mocker):
        with pytest.raises(ValueError, match="PAPERLESS_TOKEN"):
            _build(mocker, {"OPENAI_API_KEY": "sk-test"})

    def test_missing_openai_api_key_for_openai_provider(self, mocker):
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            _build(mocker, {"PAPERLESS_TOKEN": "tok"})

    def test_openai_api_key_required_when_embedding_provider_is_openai(self, mocker):
        """Embeddings on OpenAI need the key even when the LLM is local."""
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            _build(
                mocker,
                {
                    "PAPERLESS_TOKEN": "tok",
                    "LLM_PROVIDER": "ollama",
                    "EMBEDDING_PROVIDER": "openai",
                },
            )

    def test_openai_api_key_optional_when_both_providers_are_ollama(self, mocker):
        s = _build(
            mocker,
            {
                "PAPERLESS_TOKEN": "tok",
                "LLM_PROVIDER": "ollama",
                "EMBEDDING_PROVIDER": "ollama",
            },
        )
        assert s.OPENAI_API_KEY == ""
        assert s.EMBEDDING_PROVIDER == "ollama"

    def test_openai_api_key_required_when_only_llm_provider_is_openai(self, mocker):
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            _build(
                mocker,
                {
                    "PAPERLESS_TOKEN": "tok",
                    "LLM_PROVIDER": "openai",
                    "EMBEDDING_PROVIDER": "ollama",
                },
            )

    def test_openai_api_key_required_when_llm_ollama_but_embeddings_default(
        self, mocker
    ):
        """LLM_PROVIDER=ollama alone leaves embeddings on the openai default."""
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            _build(mocker, {"PAPERLESS_TOKEN": "tok", "LLM_PROVIDER": "ollama"})

    def test_empty_paperless_token_is_treated_as_missing(self, mocker):
        """Fail at validation rather than authenticate every daemon with ``""``."""
        with pytest.raises(ValueError, match="PAPERLESS_TOKEN"):
            _build(mocker, {**_MINIMAL_ENV, "PAPERLESS_TOKEN": ""})

    def test_whitespace_only_openai_api_key_is_treated_as_missing(self, mocker):
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            _build(mocker, {**_MINIMAL_ENV, "OPENAI_API_KEY": "   "})


class TestSettingsRepr:
    def test_repr_masks_secret_keys(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        text = repr(s)
        assert "tok-123" not in text
        assert "sk-test" not in text
        # The mask is the same sentinel the Settings API uses.
        assert "PAPERLESS_TOKEN='********'" in text
        assert "OPENAI_API_KEY='********'" in text

    def test_str_masks_secret_keys(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert "tok-123" not in str(s)
        assert "sk-test" not in str(s)

    def test_repr_keeps_non_secret_values(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_DPI": "275"})
        assert "275" in repr(s)


class TestOllamaConfig:
    def test_ollama_default_models(self, mocker):
        s = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert s.OCR_MODELS == ["gemma3:27b", "gemma3:12b"]
        assert s.CLASSIFY_MODELS == ["gemma3:27b", "gemma3:12b"]

    def test_ollama_default_base_url(self, mocker):
        s = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert s.OLLAMA_BASE_URL == "http://localhost:11434/v1/"

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_ollama_base_url_means_the_default(self, mocker, blank):
        s = _build(mocker, {**_MINIMAL_OLLAMA_ENV, "OLLAMA_BASE_URL": blank})
        assert s.OLLAMA_BASE_URL == "http://localhost:11434/v1/"

    def test_ollama_custom_base_url(self, mocker):
        s = _build(
            mocker, {**_MINIMAL_OLLAMA_ENV, "OLLAMA_BASE_URL": "http://gpu:11434/v1/"}
        )
        assert s.OLLAMA_BASE_URL == "http://gpu:11434/v1/"

    def test_ollama_still_loads_openai_api_key_when_present(self, mocker):
        s = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert s.OPENAI_API_KEY == "sk-test"

    def test_openai_provider_ollama_base_url_is_none(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.OLLAMA_BASE_URL is None


class TestEmbeddingProvider:
    def test_defaults_to_openai_when_llm_provider_is_openai(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.EMBEDDING_PROVIDER == "openai"

    def test_defaults_to_openai_independent_of_llm_provider(self, mocker):
        """Switching the chat provider must not move embeddings and force a re-embed."""
        s = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert s.EMBEDDING_PROVIDER == "openai"

    def test_explicit_override_selects_the_embedding_provider(self, mocker):
        s = _build(
            mocker,
            {**_MINIMAL_ENV, "LLM_PROVIDER": "openai", "EMBEDDING_PROVIDER": "ollama"},
        )
        assert s.EMBEDDING_PROVIDER == "ollama"
        # The reverse split is also honoured.
        s2 = _build(
            mocker,
            {**_MINIMAL_OLLAMA_ENV, "EMBEDDING_PROVIDER": "openai"},
        )
        assert s2.EMBEDDING_PROVIDER == "openai"

    def test_blank_override_falls_back_to_openai_default(self, mocker):
        """A value cleared in the UI arrives blank and must not crash."""
        s = _build(mocker, {**_MINIMAL_OLLAMA_ENV, "EMBEDDING_PROVIDER": "  "})
        assert s.EMBEDDING_PROVIDER == "openai"

    def test_invalid_value_rejected(self, mocker):
        with pytest.raises(ValueError, match="EMBEDDING_PROVIDER must be"):
            _build(mocker, {**_MINIMAL_ENV, "EMBEDDING_PROVIDER": "anthropic"})


class TestValidation:
    def test_invalid_provider_raises(self, mocker):
        with pytest.raises(ValueError, match="LLM_PROVIDER must be"):
            _build(mocker, {**_MINIMAL_ENV, "LLM_PROVIDER": "anthropic"})

    def test_invalid_log_format_raises(self, mocker):
        with pytest.raises(ValueError, match="LOG_FORMAT must be"):
            _build(mocker, {**_MINIMAL_ENV, "LOG_FORMAT": "xml"})

    @pytest.mark.parametrize("value", ["max", "medium-rare"])
    def test_invalid_reasoning_effort_raises(self, mocker, value):
        with pytest.raises(
            ValueError, match="CLASSIFY_REASONING_EFFORT must be one of"
        ):
            _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_REASONING_EFFORT": value})

    def test_minimal_coerces_for_classify_too(self, mocker):
        warn = mocker.patch("common.config._parsers.log.warning")
        settings = _build(
            mocker, {**_MINIMAL_ENV, "CLASSIFY_REASONING_EFFORT": "minimal"}
        )
        assert settings.CLASSIFY_REASONING_EFFORT == "none"
        warn.assert_any_call(
            "config.reasoning_effort_minimal_coerced",
            var_name="CLASSIFY_REASONING_EFFORT",
            coerced_to="none",
        )

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_max_retries_invalid_raises(self, mocker, value):
        with pytest.raises(ValueError, match="MAX_RETRIES must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, "MAX_RETRIES": value})

    @pytest.mark.parametrize("value", ["0", "-5"])
    def test_max_retry_backoff_invalid_raises(self, mocker, value):
        with pytest.raises(ValueError, match="MAX_RETRY_BACKOFF_SECONDS must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, "MAX_RETRY_BACKOFF_SECONDS": value})

    # Reject at startup: a negative timeout fails only at request time and a
    # negative DPI corrupts rasterisation.
    @pytest.mark.parametrize(
        "env_key, value",
        [
            ("REQUEST_TIMEOUT", "-5"),
            ("REQUEST_TIMEOUT", "0"),
            ("OCR_DPI", "-1"),
            ("OCR_DPI", "0"),
            ("OCR_MAX_SIDE", "-100"),
            ("OCR_MAX_SIDE", "0"),
            ("POLL_INTERVAL", "-1"),
            ("POLL_INTERVAL", "0"),
        ],
    )
    def test_non_positive_required_numeric_fails_closed(self, mocker, env_key, value):
        with pytest.raises(ValueError, match=f"{env_key} must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, env_key: value})


class TestBlankNumericFallsBackToDefault:
    """The Settings UI round-trips a cleared numeric field as ""."""

    @pytest.mark.parametrize(
        "env_key, expected_default",
        [
            ("POLL_INTERVAL", 15),
            ("REQUEST_TIMEOUT", 180),
            ("OCR_DPI", 300),
            ("OCR_MAX_SIDE", 1600),
            ("MAX_RETRIES", 3),
            ("CHUNK_SIZE", 2000),
            ("PRE_TAG_ID", 443),
        ],
    )
    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_falls_back_to_default(
        self, mocker, env_key, expected_default, blank
    ):
        s = _build(mocker, {**_MINIMAL_ENV, env_key: blank})
        assert getattr(s, env_key) == expected_default


class TestOcrImageDetail:
    def test_defaults_to_high(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.OCR_IMAGE_DETAIL == "high"

    @pytest.mark.parametrize("value", ["low", "high", "auto"])
    def test_accepts_each_allowed_value(self, mocker, value):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_IMAGE_DETAIL": value})
        assert s.OCR_IMAGE_DETAIL == value

    def test_rejects_unknown_value(self, mocker):
        with pytest.raises(ValueError, match="OCR_IMAGE_DETAIL must be"):
            _build(mocker, {**_MINIMAL_ENV, "OCR_IMAGE_DETAIL": "medium"})


class TestOcrReasoningEffort:
    """OCR is perception and the highest-volume call, so it defaults to none."""

    def test_defaults_to_none(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.OCR_REASONING_EFFORT == "none"

    @pytest.mark.parametrize("value", ["none", "low", "medium", "high", "xhigh"])
    def test_accepts_each_allowed_value(self, mocker, value):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_REASONING_EFFORT": value})
        assert s.OCR_REASONING_EFFORT == value

    def test_rejects_unknown_value(self, mocker):
        with pytest.raises(ValueError, match="OCR_REASONING_EFFORT must be"):
            _build(mocker, {**_MINIMAL_ENV, "OCR_REASONING_EFFORT": "ludicrous"})

    def test_minimal_coerces_to_none_with_warning(self, mocker):
        warn = mocker.patch("common.config._parsers.log.warning")
        settings = _build(mocker, {**_MINIMAL_ENV, "OCR_REASONING_EFFORT": "minimal"})
        assert settings.OCR_REASONING_EFFORT == "none"
        warn.assert_any_call(
            "config.reasoning_effort_minimal_coerced",
            var_name="OCR_REASONING_EFFORT",
            coerced_to="none",
        )


_CLAMPED_TO_ONE = [
    ("PAGE_WORKERS", "0"),
    ("PAGE_WORKERS", "-5"),
    ("DOCUMENT_WORKERS", "0"),
    ("DOCUMENT_WORKERS", "-3"),
]


class TestWorkerClamping:
    @pytest.mark.parametrize(
        "env_key, env_val",
        _CLAMPED_TO_ONE,
        ids=[f"{k}={v}" for k, v in _CLAMPED_TO_ONE],
    )
    def test_clamped_to_1(self, mocker, env_key, env_val):
        s = _build(mocker, {**_MINIMAL_ENV, env_key: env_val})
        assert getattr(s, env_key) == 1


_POSITIVE_OR_NONE = [
    ("OCR_PROCESSING_TAG_ID", "-1", None),
    ("OCR_PROCESSING_TAG_ID", "0", None),
    ("OCR_PROCESSING_TAG_ID", "", None),
    ("OCR_PROCESSING_TAG_ID", "42", 42),
    ("CLASSIFY_POST_TAG_ID", "-1", None),
    ("CLASSIFY_POST_TAG_ID", "0", None),
    ("CLASSIFY_PROCESSING_TAG_ID", "-5", None),
    ("ERROR_TAG_ID", "-1", None),
    ("ERROR_TAG_ID", "0", None),
    ("ERROR_TAG_ID", "99", 99),
]


class TestPositiveOrNone:
    @pytest.mark.parametrize(
        "env_key, env_val, expected",
        _POSITIVE_OR_NONE,
        ids=[f"{k}={v}" for k, v, _ in _POSITIVE_OR_NONE],
    )
    def test_positive_or_none(self, mocker, env_key, env_val, expected):
        s = _build(mocker, {**_MINIMAL_ENV, env_key: env_val})
        assert getattr(s, env_key) == expected


_CLAMPED_TO_ZERO = [
    ("CLASSIFY_MAX_CHARS", "-1"),
    ("CLASSIFY_MAX_TOKENS", "-10"),
    ("CLASSIFY_TAG_LIMIT", "-1"),
    ("CLASSIFY_TAXONOMY_LIMIT", "-1"),
    ("CLASSIFY_MAX_PAGES", "-1"),
    ("CLASSIFY_TAIL_PAGES", "-1"),
    ("CLASSIFY_HEADERLESS_CHAR_LIMIT", "-5"),
]


class TestClassifyClamping:
    @pytest.mark.parametrize(
        "env_key, env_val",
        _CLAMPED_TO_ZERO,
        ids=[f"{k}={v}" for k, v in _CLAMPED_TO_ZERO],
    )
    def test_clamped_to_zero(self, mocker, env_key, env_val):
        s = _build(mocker, {**_MINIMAL_ENV, env_key: env_val})
        assert getattr(s, env_key) == 0


class TestSearchKeyDailyTokenQuota:
    def test_defaults_to_zero_disabled(self, mocker):
        s = _build(mocker, dict(_MINIMAL_ENV))
        assert s.SEARCH_KEY_DAILY_TOKEN_QUOTA == 0

    def test_positive_value_is_kept(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "SEARCH_KEY_DAILY_TOKEN_QUOTA": "50000"})
        assert s.SEARCH_KEY_DAILY_TOKEN_QUOTA == 50000

    def test_negative_value_clamps_to_zero(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "SEARCH_KEY_DAILY_TOKEN_QUOTA": "-1"})
        assert s.SEARCH_KEY_DAILY_TOKEN_QUOTA == 0


class TestModelListsValidation:
    def test_ocr_models_all_commas_raises(self, mocker):
        with pytest.raises(
            ValueError, match="OCR_MODELS must contain at least one model"
        ):
            _build(mocker, {**_MINIMAL_ENV, "OCR_MODELS": ",,, ,"})

    def test_ocr_models_empty_string_raises(self, mocker):
        with pytest.raises(
            ValueError, match="OCR_MODELS must contain at least one model"
        ):
            _build(mocker, {**_MINIMAL_ENV, "OCR_MODELS": ""})

    def test_classify_models_all_commas_raises(self, mocker):
        with pytest.raises(
            ValueError, match="CLASSIFY_MODELS must contain at least one model"
        ):
            _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_MODELS": ",,, ,"})

    def test_classify_models_empty_string_raises(self, mocker):
        with pytest.raises(
            ValueError, match="CLASSIFY_MODELS must contain at least one model"
        ):
            _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_MODELS": ""})

    def test_ocr_models_single_model(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_MODELS": "model-a"})
        assert s.OCR_MODELS == ["model-a"]

    def test_ocr_models_whitespace_stripped(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_MODELS": " model-a , model-b "})
        assert s.OCR_MODELS == ["model-a", "model-b"]


class TestOcrRefusalMarkers:
    def test_custom_markers(self, mocker):
        s = _build(
            mocker, {**_MINIMAL_ENV, "OCR_REFUSAL_MARKERS": "forbidden,blocked, nope "}
        )
        assert s.OCR_REFUSAL_MARKERS == ["forbidden", "blocked", "nope"]

    def test_custom_markers_lowered(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_REFUSAL_MARKERS": "FORBIDDEN,Blocked"})
        assert s.OCR_REFUSAL_MARKERS == ["forbidden", "blocked"]

    def test_empty_markers_returns_empty(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_REFUSAL_MARKERS": ",,,"})
        assert s.OCR_REFUSAL_MARKERS == []


class TestBoolEnvParsing:
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "y", "on"])
    def test_truthy_values(self, mocker, value):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_INCLUDE_PAGE_MODELS": value})
        assert s.OCR_INCLUDE_PAGE_MODELS is True

    @pytest.mark.parametrize(
        "value", ["false", "False", "FALSE", "0", "no", "n", "off"]
    )
    def test_falsy_values(self, mocker, value):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_INCLUDE_PAGE_MODELS": value})
        assert s.OCR_INCLUDE_PAGE_MODELS is False

    def test_invalid_bool_raises(self, mocker):
        with pytest.raises(ValueError, match="must be a boolean value"):
            _build(mocker, {**_MINIMAL_ENV, "OCR_INCLUDE_PAGE_MODELS": "maybe"})

    @pytest.mark.parametrize(
        "env_key, expected_default",
        [
            ("STALE_LOCK_RECOVERY", True),
            ("SEARCH_GATE_JUDGE", True),
            ("OCR_INCLUDE_PAGE_MODELS", False),
        ],
    )
    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_falls_back_to_default(
        self, mocker, env_key, expected_default, blank
    ):
        """A blank boolean means unset, as for the numeric parsers.

        ``STALE_LOCK_RECOVERY=`` in a compose file is seeded verbatim into the
        config table; raising would fail every daemon's boot and every Settings
        save, with no way back through the UI.
        """
        s = _build(mocker, {**_MINIMAL_ENV, env_key: blank})
        assert getattr(s, env_key) is expected_default


class TestPaperlessUrlTrailingSlash:
    def test_trailing_slash_stripped(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "PAPERLESS_URL": "http://example.com/"})
        assert s.PAPERLESS_URL == "http://example.com"

    def test_multiple_trailing_slashes_stripped(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "PAPERLESS_URL": "http://example.com///"})
        assert s.PAPERLESS_URL == "http://example.com"

    def test_no_trailing_slash_unchanged(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "PAPERLESS_URL": "http://example.com"})
        assert s.PAPERLESS_URL == "http://example.com"


class TestPaperlessPublicUrl:
    def test_defaults_to_paperless_url_when_unset(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "PAPERLESS_URL": "http://paperless:8000"})
        assert s.PAPERLESS_PUBLIC_URL == "http://paperless:8000"

    def test_explicit_value_overrides_paperless_url(self, mocker):
        s = _build(
            mocker,
            {
                **_MINIMAL_ENV,
                "PAPERLESS_URL": "http://paperless:8000",
                "PAPERLESS_PUBLIC_URL": "https://docs.example.com",
            },
        )
        assert s.PAPERLESS_PUBLIC_URL == "https://docs.example.com"
        # The API base is untouched — the two URLs are independent.
        assert s.PAPERLESS_URL == "http://paperless:8000"

    def test_trailing_slash_stripped(self, mocker):
        s = _build(
            mocker,
            {**_MINIMAL_ENV, "PAPERLESS_PUBLIC_URL": "https://docs.example.com/"},
        )
        assert s.PAPERLESS_PUBLIC_URL == "https://docs.example.com"


class TestClassifyPreTagIdDefault:
    def test_defaults_to_post_tag_id(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "POST_TAG_ID": "999"})
        assert s.CLASSIFY_PRE_TAG_ID == 999

    def test_can_be_overridden(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_PRE_TAG_ID": "111"})
        assert s.CLASSIFY_PRE_TAG_ID == 111

    def test_empty_string_falls_back_to_post_tag_id(self, mocker):
        s = _build(
            mocker, {**_MINIMAL_ENV, "CLASSIFY_PRE_TAG_ID": "", "POST_TAG_ID": "888"}
        )
        assert s.CLASSIFY_PRE_TAG_ID == 888


class TestClassifyPersonFieldId:
    def test_not_set_is_none(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_PERSON_FIELD_ID is None

    def test_empty_string_is_none(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_PERSON_FIELD_ID": ""})
        assert s.CLASSIFY_PERSON_FIELD_ID is None

    def test_whitespace_only_is_none(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_PERSON_FIELD_ID": "  "})
        assert s.CLASSIFY_PERSON_FIELD_ID is None

    def test_valid_int(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_PERSON_FIELD_ID": "7"})
        assert s.CLASSIFY_PERSON_FIELD_ID == 7


class TestLlmMaxConcurrent:
    def test_negative_clamped_to_zero(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "LLM_MAX_CONCURRENT": "-3"})
        assert s.LLM_MAX_CONCURRENT == 0

    def test_env_zero_overrides_the_new_default(self, mocker):
        """0 selects unbounded even though the default is bounded."""
        s = _build(mocker, {**_MINIMAL_ENV, "LLM_MAX_CONCURRENT": "0"})
        assert s.LLM_MAX_CONCURRENT == 0


class TestOpenAiFlexTier:
    def test_defaults_to_true(self, mocker):
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.OPENAI_FLEX_TIER is True

    def test_can_be_disabled(self, mocker):
        settings = _build(mocker, {**_MINIMAL_ENV, "OPENAI_FLEX_TIER": "false"})
        assert settings.OPENAI_FLEX_TIER is False

    def test_is_a_config_table_key(self):
        from common.config._catalogue import CONFIG_KEYS

        assert "OPENAI_FLEX_TIER" in CONFIG_KEYS


class TestAppDbPath:
    def test_app_db_path_defaults_to_data_app_db(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.APP_DB_PATH == "/data/app.db"

    def test_app_db_path_is_read_from_the_environment(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "APP_DB_PATH": "/custom/accounts.db"})
        assert s.APP_DB_PATH == "/custom/accounts.db"


def test_bootstrap_keys_are_the_two_database_paths() -> None:
    from common.config import BOOTSTRAP_KEYS

    assert BOOTSTRAP_KEYS == frozenset({"APP_DB_PATH", "INDEX_DB_PATH"})


def test_secret_keys_cover_the_two_secrets() -> None:
    from common.config import SECRET_KEYS

    assert SECRET_KEYS == frozenset({"OPENAI_API_KEY", "PAPERLESS_TOKEN"})


def test_ocr_detail_and_reasoning_are_config_keys_only() -> None:
    from common.config import CONFIG_KEYS, REINDEX_KEYS, SECRET_KEYS

    for key in ("OCR_IMAGE_DETAIL", "OCR_REASONING_EFFORT"):
        assert key in CONFIG_KEYS
        assert key not in SECRET_KEYS
        assert key not in REINDEX_KEYS


def test_relevance_tier_keys_are_config_only() -> None:
    from common.config import CONFIG_KEYS, REINDEX_KEYS, SECRET_KEYS

    for key in (
        "SEARCH_RELEVANCE_TIER_STRONG",
        "SEARCH_RELEVANCE_TIER_GOOD",
        "SEARCH_RELEVANCE_TIER_PARTIAL",
    ):
        assert key in CONFIG_KEYS
        assert key not in SECRET_KEYS
        assert key not in REINDEX_KEYS


def test_identity_aware_is_config_only() -> None:
    from common.config import CONFIG_KEYS, REINDEX_KEYS, SECRET_KEYS

    assert "SEARCH_IDENTITY_AWARE" in CONFIG_KEYS
    assert "SEARCH_IDENTITY_AWARE" not in SECRET_KEYS
    assert "SEARCH_IDENTITY_AWARE" not in REINDEX_KEYS


def test_config_keys_has_ninety_entries() -> None:
    from common.config import CONFIG_KEYS

    assert len(CONFIG_KEYS) == 90
    assert "OPENAI_FLEX_TIER" in CONFIG_KEYS
    assert "PRICING_REFRESH_URL" in CONFIG_KEYS
    assert "PRICING_REFRESH_INTERVAL_HOURS" in CONFIG_KEYS
    assert "SEARCH_KEY_DAILY_TOKEN_QUOTA" in CONFIG_KEYS
    assert "SEARCH_JUDGE_KEEP_THRESHOLD" not in CONFIG_KEYS
    assert "EMBEDDING_PROVIDER" in CONFIG_KEYS
    assert "STALE_LOCK_RECOVERY" in CONFIG_KEYS
    assert "SEARCH_PER_SPEC_K" in CONFIG_KEYS
    assert "SEARCH_MAX_CHUNKS_PER_DOC" in CONFIG_KEYS
    assert "SEARCH_PLANNER_MAX_SPECS" in CONFIG_KEYS
    assert "SEARCH_PLANNER_TAXONOMY_LIMIT" in CONFIG_KEYS
    assert "SEARCH_IDENTITY_AWARE" in CONFIG_KEYS
    assert "SEARCH_API_KEY" not in CONFIG_KEYS
    assert "AI_MODELS" not in CONFIG_KEYS
    assert "OCR_MODELS" in CONFIG_KEYS
    assert "CLASSIFY_MODELS" in CONFIG_KEYS
    assert "SEARCH_FORWARDED_ALLOW_IPS" in CONFIG_KEYS
    assert "SEARCH_GATE_ADEQUACY" in CONFIG_KEYS
    assert "SEARCH_GATE_RELEVANCE" in CONFIG_KEYS
    assert "SEARCH_RELEVANCE_MIN_SIMILARITY" in CONFIG_KEYS
    assert "SEARCH_RELEVANCE_TIER_STRONG" in CONFIG_KEYS
    assert "SEARCH_RELEVANCE_TIER_GOOD" in CONFIG_KEYS
    assert "SEARCH_RELEVANCE_TIER_PARTIAL" in CONFIG_KEYS
    assert "SEARCH_MIN_QUERY_CHARS" in CONFIG_KEYS
    assert "SEARCH_GATE_JUDGE" in CONFIG_KEYS
    assert "SEARCH_JUDGE_MODEL" in CONFIG_KEYS
    assert "SEARCH_JUDGE_REASONING_EFFORT" in CONFIG_KEYS
    assert "SEARCH_JUDGE_RATIONALES" in CONFIG_KEYS
    assert {
        "OCR_SKIP_BORN_DIGITAL",
        "OCR_BORN_DIGITAL_MIN_CHARS",
        "OCR_BORN_DIGITAL_TAG_ID",
    } <= CONFIG_KEYS


def test_judge_keys_are_config_only() -> None:
    from common.config import CONFIG_KEYS, REINDEX_KEYS, SECRET_KEYS

    for key in (
        "SEARCH_GATE_JUDGE",
        "SEARCH_JUDGE_MODEL",
        "SEARCH_JUDGE_REASONING_EFFORT",
        "SEARCH_JUDGE_RATIONALES",
    ):
        assert key in CONFIG_KEYS
        assert key not in SECRET_KEYS
        assert key not in REINDEX_KEYS


def test_search_judge_rationales_defaults_true_and_parses_false(mocker) -> None:
    settings_default = _build(mocker, _MINIMAL_ENV)
    assert settings_default.SEARCH_JUDGE_RATIONALES is True

    settings_off = _build(mocker, {**_MINIMAL_ENV, "SEARCH_JUDGE_RATIONALES": "false"})
    assert settings_off.SEARCH_JUDGE_RATIONALES is False


class TestPricingRefreshConfig:
    def test_defaults_are_disabled_and_daily(self, mocker) -> None:
        settings = _build(mocker, _MINIMAL_ENV)
        assert settings.PRICING_REFRESH_URL == ""
        assert settings.PRICING_REFRESH_INTERVAL_HOURS == 24

    def test_blank_url_stays_disabled(self, mocker) -> None:
        settings = _build(mocker, {**_MINIMAL_ENV, "PRICING_REFRESH_URL": "   "})
        assert settings.PRICING_REFRESH_URL == ""

    @pytest.mark.parametrize(
        "url",
        [
            "https://prices.example/openai.json",
            "http://prices.local:9000/list",
        ],
    )
    def test_accepts_absolute_http_urls(self, mocker, url: str) -> None:
        settings = _build(mocker, {**_MINIMAL_ENV, "PRICING_REFRESH_URL": url})
        assert settings.PRICING_REFRESH_URL == url

    def test_strips_surrounding_whitespace(self, mocker) -> None:
        settings = _build(
            mocker,
            {**_MINIMAL_ENV, "PRICING_REFRESH_URL": "  https://x.example/p.json  "},
        )
        assert settings.PRICING_REFRESH_URL == "https://x.example/p.json"

    @pytest.mark.parametrize(
        "bad",
        [
            "prices.example/list.json",  # no scheme
            "ftp://prices.example/list",  # wrong scheme
            "file:///etc/passwd",  # local file scheme
            "https://",  # no host
        ],
    )
    def test_rejects_non_http_urls(self, mocker, bad: str) -> None:
        with pytest.raises(ValueError, match="PRICING_REFRESH_URL"):
            _build(mocker, {**_MINIMAL_ENV, "PRICING_REFRESH_URL": bad})

    def test_interval_custom_value_is_honoured(self, mocker) -> None:
        settings = _build(
            mocker, {**_MINIMAL_ENV, "PRICING_REFRESH_INTERVAL_HOURS": "6"}
        )
        assert settings.PRICING_REFRESH_INTERVAL_HOURS == 6

    @pytest.mark.parametrize("raw", ["0", "-5"])
    def test_interval_clamps_to_at_least_one(self, mocker, raw: str) -> None:
        """A 0/negative typo clamps to 1 so the refresh never hot-loops."""
        settings = _build(
            mocker, {**_MINIMAL_ENV, "PRICING_REFRESH_INTERVAL_HOURS": raw}
        )
        assert settings.PRICING_REFRESH_INTERVAL_HOURS == 1

    def test_pricing_keys_are_config_only(self) -> None:
        from common.config import CONFIG_KEYS, REINDEX_KEYS, SECRET_KEYS

        for key in ("PRICING_REFRESH_URL", "PRICING_REFRESH_INTERVAL_HOURS"):
            assert key in CONFIG_KEYS
            assert key not in SECRET_KEYS
            assert key not in REINDEX_KEYS


def test_config_keys_excludes_the_bootstrap_keys() -> None:
    from common.config import BOOTSTRAP_KEYS, CONFIG_KEYS

    assert not (BOOTSTRAP_KEYS & CONFIG_KEYS)


def test_secret_keys_are_all_config_keys() -> None:
    from common.config import CONFIG_KEYS, SECRET_KEYS

    assert SECRET_KEYS <= CONFIG_KEYS


def test_reindex_keys_are_the_chunking_and_embedding_keys() -> None:
    from common.config import CONFIG_KEYS, REINDEX_KEYS

    assert REINDEX_KEYS == frozenset(
        {"EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "CHUNK_SIZE", "CHUNK_OVERLAP"}
    )
    assert REINDEX_KEYS <= CONFIG_KEYS


_STEP_PROVIDER_KEYS = (
    "OCR_PROVIDER",
    "CLASSIFY_PROVIDER",
    "SEARCH_PLANNER_PROVIDER",
    "SEARCH_JUDGE_PROVIDER",
    "SEARCH_ANSWER_PROVIDER",
)

# A reachable Ollama URL so a step set to ollama builds (the API-layer guard,
# not the config builder, enforces "configure the URL first").
_OLLAMA_URL = "http://gpu.lan:11434/v1/"


class TestPerStepProviders:
    """An absent per-step key seeds from LLM_PROVIDER (the judge from the planner)."""

    def test_default_to_openai_when_unset(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        for key in _STEP_PROVIDER_KEYS:
            assert getattr(s, key) == "openai"

    def test_all_seed_from_llm_provider_ollama(self, mocker):
        s = _build(mocker, {**_MINIMAL_OLLAMA_ENV, "OLLAMA_BASE_URL": _OLLAMA_URL})
        for key in _STEP_PROVIDER_KEYS:
            assert getattr(s, key) == "ollama"

    def test_judge_seeds_from_planner_not_llm_provider(self, mocker):
        s = _build(
            mocker,
            {
                **_MINIMAL_ENV,
                "SEARCH_PLANNER_PROVIDER": "ollama",
                "OLLAMA_BASE_URL": _OLLAMA_URL,
            },
        )
        assert s.SEARCH_PLANNER_PROVIDER == "ollama"
        assert s.SEARCH_JUDGE_PROVIDER == "ollama"  # mirrors the planner
        assert s.SEARCH_ANSWER_PROVIDER == "openai"  # seeds from LLM_PROVIDER
        assert s.OCR_PROVIDER == "openai"

    def test_explicit_judge_overrides_planner_seed(self, mocker):
        s = _build(
            mocker,
            {
                **_MINIMAL_ENV,
                "SEARCH_PLANNER_PROVIDER": "ollama",
                "SEARCH_JUDGE_PROVIDER": "openai",
                "OLLAMA_BASE_URL": _OLLAMA_URL,
            },
        )
        assert s.SEARCH_JUDGE_PROVIDER == "openai"

    def test_model_default_follows_step_provider(self, mocker):
        # OCR on Ollama → Gemma OCR models; classification stays OpenAI → GPT.
        s = _build(
            mocker,
            {**_MINIMAL_ENV, "OCR_PROVIDER": "ollama", "OLLAMA_BASE_URL": _OLLAMA_URL},
        )
        assert s.OCR_MODELS == ["gemma3:27b", "gemma3:12b"]
        assert s.CLASSIFY_MODELS == ["gpt-5.6-luna", "gpt-5.6-terra"]

    def test_search_model_default_follows_step_provider(self, mocker):
        s = _build(
            mocker,
            {
                **_MINIMAL_ENV,
                "SEARCH_ANSWER_PROVIDER": "ollama",
                "OLLAMA_BASE_URL": _OLLAMA_URL,
            },
        )
        assert s.SEARCH_ANSWER_MODEL == "gemma3:27b"
        assert s.SEARCH_PLANNER_MODEL == "gpt-5.6-terra"

    def test_invalid_value_rejected_naming_the_key(self, mocker):
        with pytest.raises(ValueError, match="OCR_PROVIDER"):
            _build(mocker, {**_MINIMAL_ENV, "OCR_PROVIDER": "bogus"})

    def test_openai_key_optional_when_every_step_ollama(self, mocker):
        s = _build(
            mocker,
            {
                "PAPERLESS_TOKEN": "tok-123",
                "LLM_PROVIDER": "ollama",
                "EMBEDDING_PROVIDER": "ollama",
                "OLLAMA_BASE_URL": _OLLAMA_URL,
            },
        )
        assert s.OPENAI_API_KEY == ""

    def test_openai_key_required_when_one_step_openai(self, mocker):
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            _build(
                mocker,
                {
                    "PAPERLESS_TOKEN": "tok-123",
                    "LLM_PROVIDER": "ollama",
                    "EMBEDDING_PROVIDER": "ollama",
                    "OCR_PROVIDER": "openai",
                    "OLLAMA_BASE_URL": _OLLAMA_URL,
                },
            )


def test_per_step_provider_keys_are_config_only() -> None:
    from common.config import CONFIG_KEYS, REINDEX_KEYS, SECRET_KEYS

    for key in _STEP_PROVIDER_KEYS:
        assert key in CONFIG_KEYS
        assert key not in SECRET_KEYS
        assert key not in REINDEX_KEYS


def test_born_digital_defaults() -> None:
    """The 1-char floor only separates "has a text layer" from "none".

    A higher floor sends a long PDF with a short cover page to vision OCR.
    """
    s = make_settings()
    assert s.OCR_SKIP_BORN_DIGITAL is True
    assert s.OCR_BORN_DIGITAL_MIN_CHARS == 1
    assert s.OCR_BORN_DIGITAL_TAG_ID is None


def test_min_chars_rejects_zero() -> None:
    """Zero would treat every page as born-digital."""
    with pytest.raises(ValueError):
        make_settings(OCR_BORN_DIGITAL_MIN_CHARS="0")


def test_tag_id_parses_positive_int() -> None:
    assert make_settings(OCR_BORN_DIGITAL_TAG_ID="17").OCR_BORN_DIGITAL_TAG_ID == 17
