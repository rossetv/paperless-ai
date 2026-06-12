"""Tests for common.config — core daemon settings.

Indexer settings live in test_config_index.py; search-server settings live
in test_config_search.py (§3.1 500-line ceiling split).
"""

from __future__ import annotations

import os

import pytest

from common.config import Settings

_MINIMAL_ENV = {
    "PAPERLESS_TOKEN": "tok-123",
    "OPENAI_API_KEY": "sk-test",
}

# A fully-local deployment (LLM and embeddings both ollama) may omit
# OPENAI_API_KEY, but it must set EMBEDDING_PROVIDER=ollama explicitly — the
# embedding provider is independent of LLM_PROVIDER and defaults to openai. Most
# of these tests supply the key anyway because they exercise unrelated ollama
# defaults; the key is harmless when present.
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
    ("CLASSIFY_REASONING_EFFORT", "medium"),
]


class TestDefaults:
    """Settings constructed with the minimal env should have correct defaults."""

    @pytest.mark.parametrize(
        "attr, expected", _SIMPLE_DEFAULTS, ids=[a for a, _ in _SIMPLE_DEFAULTS]
    )
    def test_default_value(self, mocker, attr, expected):
        s = _build(mocker, _MINIMAL_ENV)
        assert getattr(s, attr) == expected

    def test_ocr_and_classify_models_default_openai(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.OCR_MODELS == ["gpt-5.4-mini", "gpt-5.4", "gpt-5.5"]
        assert s.CLASSIFY_MODELS == ["gpt-5.4-mini", "gpt-5.4", "gpt-5.5"]

    def test_ocr_refusal_markers_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert "chatgpt refused to transcribe" in s.OCR_REFUSAL_MARKERS
        assert "i can't assist" in s.OCR_REFUSAL_MARKERS

    def test_classify_pre_tag_id_defaults_to_post_tag_id(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_PRE_TAG_ID == s.POST_TAG_ID


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
    ("CLASSIFY_REASONING_EFFORT", "minimal", "CLASSIFY_REASONING_EFFORT", "minimal"),
    ("CLASSIFY_REASONING_EFFORT", "MEDIUM", "CLASSIFY_REASONING_EFFORT", "medium"),
    ("CLASSIFY_REASONING_EFFORT", " minimal ", "CLASSIFY_REASONING_EFFORT", "minimal"),
    ("ERROR_TAG_ID", "999", "ERROR_TAG_ID", 999),
    ("OCR_PROCESSING_TAG_ID", "77", "OCR_PROCESSING_TAG_ID", 77),
    ("CLASSIFY_PRE_TAG_ID", "555", "CLASSIFY_PRE_TAG_ID", 555),
    ("CLASSIFY_POST_TAG_ID", "666", "CLASSIFY_POST_TAG_ID", 666),
    ("CLASSIFY_PROCESSING_TAG_ID", "777", "CLASSIFY_PROCESSING_TAG_ID", 777),
]


class TestCustomEnvVars:
    """Every env var can be overridden from its default."""

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
        """OPENAI_API_KEY is required when OpenAI is used by EITHER provider.

        Under LLM_PROVIDER=ollama the LLM is local, but an explicit
        EMBEDDING_PROVIDER=openai means embeddings still go to OpenAI, so the
        key is required (CODE_GUIDELINES §10.8, §15.4).
        """
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
        """A fully-local deployment (LLM + embeddings ollama) may omit the key.

        EMBEDDING_PROVIDER is independent and defaults to openai, so a local
        deployment must set it to ollama explicitly; then no call ever reaches
        OpenAI and OPENAI_API_KEY is not required (resolves to an empty string).
        """
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
        """OPENAI_API_KEY is required when the LLM uses OpenAI even if embeddings
        are local (EMBEDDING_PROVIDER=ollama)."""
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
        """LLM_PROVIDER=ollama alone leaves embeddings on the openai default, so
        OPENAI_API_KEY is still required until EMBEDDING_PROVIDER is set local."""
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            _build(mocker, {"PAPERLESS_TOKEN": "tok", "LLM_PROVIDER": "ollama"})

    def test_empty_paperless_token_is_treated_as_missing(self, mocker):
        """An empty PAPERLESS_TOKEN must fail at validation, not at runtime.

        Regression for the Wave 4 boundary: an admin saving an empty secret
        through the Settings PUT used to round-trip the empty string into the
        config table, and every daemon then authenticated to Paperless with
        ``""`` until an admin manually fixed it.
        """
        with pytest.raises(ValueError, match="PAPERLESS_TOKEN"):
            _build(mocker, {**_MINIMAL_ENV, "PAPERLESS_TOKEN": ""})

    def test_whitespace_only_openai_api_key_is_treated_as_missing(self, mocker):
        """A whitespace-only required secret is rejected — same as empty."""
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            _build(mocker, {**_MINIMAL_ENV, "OPENAI_API_KEY": "   "})


class TestSettingsRepr:
    """`Settings.__repr__` masks every secret value (CODE_GUIDELINES §7.4)."""

    def test_repr_masks_secret_keys(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        text = repr(s)
        assert "tok-123" not in text
        assert "sk-test" not in text
        # The mask is the same sentinel the Settings API uses.
        assert "PAPERLESS_TOKEN='********'" in text
        assert "OPENAI_API_KEY='********'" in text

    def test_str_masks_secret_keys(self, mocker):
        """`str(Settings)` masks too — both surfaces share the redaction."""
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

    def test_ollama_custom_base_url(self, mocker):
        s = _build(
            mocker, {**_MINIMAL_OLLAMA_ENV, "OLLAMA_BASE_URL": "http://gpu:11434/v1/"}
        )
        assert s.OLLAMA_BASE_URL == "http://gpu:11434/v1/"

    def test_ollama_still_loads_openai_api_key_when_present(self, mocker):
        """A supplied OPENAI_API_KEY is still loaded under ollama (harmless)."""
        s = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert s.OPENAI_API_KEY == "sk-test"

    def test_openai_provider_ollama_base_url_is_none(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.OLLAMA_BASE_URL is None


class TestEmbeddingProvider:
    """EMBEDDING_PROVIDER resolution: defaults to openai, independent of
    LLM_PROVIDER, overridable."""

    def test_defaults_to_openai_when_llm_provider_is_openai(self, mocker):
        """The prod default: EMBEDDING_PROVIDER is openai."""
        s = _build(mocker, _MINIMAL_ENV)
        assert s.EMBEDDING_PROVIDER == "openai"

    def test_defaults_to_openai_independent_of_llm_provider(self, mocker):
        """The embedding provider is independent: it stays openai by default even
        when the chat provider is ollama, so flipping chat never moves
        embeddings (and never triggers a re-embed)."""
        s = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert s.EMBEDDING_PROVIDER == "openai"

    def test_explicit_override_selects_the_embedding_provider(self, mocker):
        """An explicit EMBEDDING_PROVIDER selects it, decoupled from the chat one."""
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
        """A blank EMBEDDING_PROVIDER (cleared in the UI) falls back to the openai
        default, not a crash."""
        s = _build(mocker, {**_MINIMAL_OLLAMA_ENV, "EMBEDDING_PROVIDER": "  "})
        assert s.EMBEDDING_PROVIDER == "openai"

    def test_invalid_value_rejected(self, mocker):
        """Junk fails closed at config-build time, naming the key."""
        with pytest.raises(ValueError, match="EMBEDDING_PROVIDER must be"):
            _build(mocker, {**_MINIMAL_ENV, "EMBEDDING_PROVIDER": "anthropic"})


class TestValidation:
    """Invalid config values raise ValueError."""

    def test_invalid_provider_raises(self, mocker):
        with pytest.raises(ValueError, match="LLM_PROVIDER must be"):
            _build(mocker, {**_MINIMAL_ENV, "LLM_PROVIDER": "anthropic"})

    def test_invalid_log_format_raises(self, mocker):
        with pytest.raises(ValueError, match="LOG_FORMAT must be"):
            _build(mocker, {**_MINIMAL_ENV, "LOG_FORMAT": "xml"})

    @pytest.mark.parametrize("value", ["none", "xhigh", ""])
    def test_invalid_reasoning_effort_raises(self, mocker, value):
        with pytest.raises(
            ValueError, match="CLASSIFY_REASONING_EFFORT must be one of"
        ):
            _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_REASONING_EFFORT": value})

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_max_retries_invalid_raises(self, mocker, value):
        with pytest.raises(ValueError, match="MAX_RETRIES must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, "MAX_RETRIES": value})

    @pytest.mark.parametrize("value", ["0", "-5"])
    def test_max_retry_backoff_invalid_raises(self, mocker, value):
        with pytest.raises(ValueError, match="MAX_RETRY_BACKOFF_SECONDS must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, "MAX_RETRY_BACKOFF_SECONDS": value})

    # COMMON-03: a handful of required numeric settings used to flow straight
    # through _get_int_env with no floor, so a typo'd negative was accepted and
    # only blew up later (a negative httpx timeout fails at request time, a
    # negative DPI corrupts rasterisation). §1.11 says fail closed and loud at
    # startup — each must reject a non-positive value naming the variable.
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
    """COMMON-20: a blanked numeric field (the Settings UI round-trips "")
    falls back to the coded default consistently, instead of crashing the
    required-int path while the optional-int path silently defaults."""

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
    """OCR_IMAGE_DETAIL is a validated {low, high, auto} enum, default high."""

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
    """OCR_REASONING_EFFORT is a validated {minimal, low, medium, high} enum,
    default medium (the OpenAI model default, so the default is a no-op)."""

    def test_defaults_to_medium(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.OCR_REASONING_EFFORT == "medium"

    @pytest.mark.parametrize("value", ["minimal", "low", "medium", "high"])
    def test_accepts_each_allowed_value(self, mocker, value):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_REASONING_EFFORT": value})
        assert s.OCR_REASONING_EFFORT == value

    def test_rejects_unknown_value(self, mocker):
        with pytest.raises(ValueError, match="OCR_REASONING_EFFORT must be"):
            _build(mocker, {**_MINIMAL_ENV, "OCR_REASONING_EFFORT": "ludicrous"})


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
    """Tags that accept only positive ints or None."""

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
    """SEARCH_KEY_DAILY_TOKEN_QUOTA defaults to 0 (disabled) and clamps negatives."""

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
        """Setting LLM_MAX_CONCURRENT=0 still selects unbounded, beating the default."""
        s = _build(mocker, {**_MINIMAL_ENV, "LLM_MAX_CONCURRENT": "0"})
        assert s.LLM_MAX_CONCURRENT == 0


class TestAppDbPath:
    """The APP_DB_PATH bootstrap setting (web-redesign spec §4.1)."""

    def test_app_db_path_defaults_to_data_app_db(self, mocker):
        """APP_DB_PATH defaults to /data/app.db when the env var is unset."""
        s = _build(mocker, _MINIMAL_ENV)
        assert s.APP_DB_PATH == "/data/app.db"

    def test_app_db_path_is_read_from_the_environment(self, mocker):
        """APP_DB_PATH is taken verbatim from the environment when set."""
        s = _build(mocker, {**_MINIMAL_ENV, "APP_DB_PATH": "/custom/accounts.db"})
        assert s.APP_DB_PATH == "/custom/accounts.db"


def test_bootstrap_keys_are_the_two_database_paths() -> None:
    """BOOTSTRAP_KEYS is exactly the two env-only database-path variables."""
    from common.config import BOOTSTRAP_KEYS

    assert BOOTSTRAP_KEYS == frozenset({"APP_DB_PATH", "INDEX_DB_PATH"})


def test_secret_keys_cover_the_two_secrets() -> None:
    """SECRET_KEYS names every secret-bearing config key — SEARCH_API_KEY is
    retired by Wave 3 and is not one of them."""
    from common.config import SECRET_KEYS

    assert SECRET_KEYS == frozenset({"OPENAI_API_KEY", "PAPERLESS_TOKEN"})


def test_ocr_detail_and_reasoning_are_config_keys_only() -> None:
    """Both OCR knobs are persisted via the Settings API but are neither
    secrets nor reindex keys — they change only the next OCR request."""
    from common.config import CONFIG_KEYS, REINDEX_KEYS, SECRET_KEYS

    for key in ("OCR_IMAGE_DETAIL", "OCR_REASONING_EFFORT"):
        assert key in CONFIG_KEYS
        assert key not in SECRET_KEYS
        assert key not in REINDEX_KEYS


def test_relevance_tier_keys_are_config_only() -> None:
    """The three tier cut-points are persisted via the Settings API but are
    neither secrets nor reindex keys — they change only how the next search
    badges its results, never how documents are chunked or embedded."""
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
    """SEARCH_IDENTITY_AWARE is persisted via the Settings API but is neither a
    secret nor a reindex key — it changes only the next search."""
    from common.config import CONFIG_KEYS, REINDEX_KEYS, SECRET_KEYS

    assert "SEARCH_IDENTITY_AWARE" in CONFIG_KEYS
    assert "SEARCH_IDENTITY_AWARE" not in SECRET_KEYS
    assert "SEARCH_IDENTITY_AWARE" not in REINDEX_KEYS


def test_config_keys_has_eighty_one_entries() -> None:
    """CONFIG_KEYS is the 81-key universe.

    SEARCH_JUDGE_KEEP_THRESHOLD was removed: the judge's boolean ``keep`` is now
    the sole gate; ``score`` is used only for source ranking (Phase 3A refactor).
    SEARCH_PLANNER_TAXONOMY_LIMIT was added to feed the planner the live taxonomy.
    STALE_LOCK_RECOVERY was added so a multi-replica deployment can disable the
    unconditional startup stale-lock sweep. EMBEDDING_PROVIDER was added so a
    fully-local deployment can embed via Ollama instead of always OpenAI.
    SEARCH_KEY_DAILY_TOKEN_QUOTA was added as the per-API-key daily LLM-spend cap.
    PRICING_REFRESH_URL and PRICING_REFRESH_INTERVAL_HOURS were added for the
    refreshable, locally-cached model-price book (default disabled = bundled seed).
    """
    from common.config import CONFIG_KEYS

    assert len(CONFIG_KEYS) == 81
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


def test_judge_keys_are_config_only() -> None:
    """The judge gate + model knobs are persisted via the Settings API but are
    neither secrets nor reindex keys — they change only the next search."""
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
    """SEARCH_JUDGE_RATIONALES defaults to True and parses the string "false"."""
    settings_default = _build(mocker, _MINIMAL_ENV)
    assert settings_default.SEARCH_JUDGE_RATIONALES is True

    settings_off = _build(mocker, {**_MINIMAL_ENV, "SEARCH_JUDGE_RATIONALES": "false"})
    assert settings_off.SEARCH_JUDGE_RATIONALES is False


class TestPricingRefreshConfig:
    """PRICING_REFRESH_URL / PRICING_REFRESH_INTERVAL_HOURS — the price-book knobs."""

    def test_defaults_are_disabled_and_daily(self, mocker) -> None:
        """The default is the behaviour-preserving one: no URL, 24h interval."""
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
        """Both keys persist via the Settings API but are neither secrets nor
        reindex keys."""
        from common.config import CONFIG_KEYS, REINDEX_KEYS, SECRET_KEYS

        for key in ("PRICING_REFRESH_URL", "PRICING_REFRESH_INTERVAL_HOURS"):
            assert key in CONFIG_KEYS
            assert key not in SECRET_KEYS
            assert key not in REINDEX_KEYS


def test_config_keys_excludes_the_bootstrap_keys() -> None:
    """The bootstrap keys are not config-table keys."""
    from common.config import BOOTSTRAP_KEYS, CONFIG_KEYS

    assert not (BOOTSTRAP_KEYS & CONFIG_KEYS)


def test_secret_keys_are_all_config_keys() -> None:
    """Every secret key is a real config-table key."""
    from common.config import CONFIG_KEYS, SECRET_KEYS

    assert SECRET_KEYS <= CONFIG_KEYS


def test_reindex_keys_are_the_chunking_and_embedding_keys() -> None:
    """REINDEX_KEYS is exactly the keys whose change needs a full re-index;
    every one is a real config key."""
    from common.config import CONFIG_KEYS, REINDEX_KEYS

    assert REINDEX_KEYS == frozenset(
        {"EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "CHUNK_SIZE", "CHUNK_OVERLAP"}
    )
    assert REINDEX_KEYS <= CONFIG_KEYS
