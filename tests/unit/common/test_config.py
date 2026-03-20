"""Tests for common.config."""

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
    "LLM_PROVIDER": "ollama",
}


def _build(mocker, env: dict[str, str]) -> Settings:
    """Build Settings with *only* the supplied env vars."""
    mocker.patch.dict(os.environ, env, clear=True)
    return Settings()


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
    ("MAX_RETRIES", 20),
    ("MAX_RETRY_BACKOFF_SECONDS", 30),
    ("REQUEST_TIMEOUT", 180),
    ("LLM_MAX_CONCURRENT", 0),
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
    ("CLASSIFY_TAXONOMY_LIMIT", 100),
    ("CLASSIFY_MAX_PAGES", 3),
    ("CLASSIFY_TAIL_PAGES", 2),
    ("CLASSIFY_HEADERLESS_CHAR_LIMIT", 15000),
]


class TestDefaults:
    """Settings constructed with the minimal env should have correct defaults."""

    @pytest.mark.parametrize("attr, expected", _SIMPLE_DEFAULTS, ids=[a for a, _ in _SIMPLE_DEFAULTS])
    def test_default_value(self, mocker, attr, expected):
        s = _build(mocker, _MINIMAL_ENV)
        assert getattr(s, attr) == expected

    def test_ai_models_default_openai(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.AI_MODELS == ["gpt-5.4-mini", "gpt-5.4", "o4-mini"]

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

    def test_ai_models_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "AI_MODELS": "model-a, model-b"})
        assert s.AI_MODELS == ["model-a", "model-b"]


class TestMissingRequired:

    def test_missing_paperless_token(self, mocker):
        with pytest.raises(ValueError, match="PAPERLESS_TOKEN"):
            _build(mocker, {"OPENAI_API_KEY": "sk-test"})

    def test_missing_openai_api_key_for_openai_provider(self, mocker):
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            _build(mocker, {"PAPERLESS_TOKEN": "tok"})

    def test_ollama_does_not_require_openai_api_key(self, mocker):
        s = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert s.OPENAI_API_KEY is None


class TestOllamaConfig:

    def test_ollama_default_models(self, mocker):
        s = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert s.AI_MODELS == ["gemma3:27b", "gemma3:12b"]

    def test_ollama_default_base_url(self, mocker):
        s = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert s.OLLAMA_BASE_URL == "http://localhost:11434/v1/"

    def test_ollama_custom_base_url(self, mocker):
        s = _build(mocker, {**_MINIMAL_OLLAMA_ENV, "OLLAMA_BASE_URL": "http://gpu:11434/v1/"})
        assert s.OLLAMA_BASE_URL == "http://gpu:11434/v1/"

    def test_ollama_no_api_key(self, mocker):
        s = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert s.OPENAI_API_KEY is None

    def test_openai_provider_ollama_base_url_is_none(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.OLLAMA_BASE_URL is None


class TestValidation:
    """Invalid config values raise ValueError."""

    def test_invalid_provider_raises(self, mocker):
        with pytest.raises(ValueError, match="LLM_PROVIDER must be"):
            _build(mocker, {**_MINIMAL_ENV, "LLM_PROVIDER": "anthropic"})

    def test_invalid_log_format_raises(self, mocker):
        with pytest.raises(ValueError, match="LOG_FORMAT must be"):
            _build(mocker, {**_MINIMAL_ENV, "LOG_FORMAT": "xml"})

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_max_retries_invalid_raises(self, mocker, value):
        with pytest.raises(ValueError, match="MAX_RETRIES must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, "MAX_RETRIES": value})

    @pytest.mark.parametrize("value", ["0", "-5"])
    def test_max_retry_backoff_invalid_raises(self, mocker, value):
        with pytest.raises(ValueError, match="MAX_RETRY_BACKOFF_SECONDS must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, "MAX_RETRY_BACKOFF_SECONDS": value})


_CLAMPED_TO_ONE = [
    ("PAGE_WORKERS", "0"),
    ("PAGE_WORKERS", "-5"),
    ("DOCUMENT_WORKERS", "0"),
    ("DOCUMENT_WORKERS", "-3"),
]


class TestWorkerClamping:

    @pytest.mark.parametrize("env_key, env_val", _CLAMPED_TO_ONE, ids=[f"{k}={v}" for k, v in _CLAMPED_TO_ONE])
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
    ("CLASSIFY_MAX_TOKENS", "-10"),
    ("CLASSIFY_TAG_LIMIT", "-1"),
    ("CLASSIFY_TAXONOMY_LIMIT", "-1"),
    ("CLASSIFY_MAX_PAGES", "-1"),
    ("CLASSIFY_TAIL_PAGES", "-1"),
    ("CLASSIFY_HEADERLESS_CHAR_LIMIT", "-5"),
]


class TestClassifyClamping:

    @pytest.mark.parametrize("env_key, env_val", _CLAMPED_TO_ZERO, ids=[f"{k}={v}" for k, v in _CLAMPED_TO_ZERO])
    def test_clamped_to_zero(self, mocker, env_key, env_val):
        s = _build(mocker, {**_MINIMAL_ENV, env_key: env_val})
        assert getattr(s, env_key) == 0


class TestAiModelsValidation:

    def test_all_commas_raises(self, mocker):
        with pytest.raises(ValueError, match="AI_MODELS must contain at least one model"):
            _build(mocker, {**_MINIMAL_ENV, "AI_MODELS": ",,, ,"})

    def test_empty_string_raises(self, mocker):
        with pytest.raises(ValueError, match="AI_MODELS must contain at least one model"):
            _build(mocker, {**_MINIMAL_ENV, "AI_MODELS": ""})

    def test_single_model(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "AI_MODELS": "model-a"})
        assert s.AI_MODELS == ["model-a"]

    def test_whitespace_stripped(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "AI_MODELS": " model-a , model-b "})
        assert s.AI_MODELS == ["model-a", "model-b"]


class TestOcrRefusalMarkers:

    def test_custom_markers(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_REFUSAL_MARKERS": "forbidden,blocked, nope "})
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

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", "n", "off"])
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


class TestClassifyPreTagIdDefault:

    def test_defaults_to_post_tag_id(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "POST_TAG_ID": "999"})
        assert s.CLASSIFY_PRE_TAG_ID == 999

    def test_can_be_overridden(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_PRE_TAG_ID": "111"})
        assert s.CLASSIFY_PRE_TAG_ID == 111

    def test_empty_string_falls_back_to_post_tag_id(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_PRE_TAG_ID": "", "POST_TAG_ID": "888"})
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
