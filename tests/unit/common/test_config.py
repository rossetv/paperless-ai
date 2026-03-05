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

class TestDefaults:
    """Settings constructed with the minimal env should have correct defaults."""

    def test_paperless_url_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.PAPERLESS_URL == "http://paperless:8000"

    def test_llm_provider_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.LLM_PROVIDER == "openai"

    def test_ai_models_default_openai(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.AI_MODELS == ["gpt-5-mini", "gpt-5.2", "o4-mini"]

    def test_ocr_refusal_markers_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert "chatgpt refused to transcribe" in s.OCR_REFUSAL_MARKERS
        assert "i can't assist" in s.OCR_REFUSAL_MARKERS

    def test_ocr_include_page_models_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.OCR_INCLUDE_PAGE_MODELS is False

    def test_pre_tag_id_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.PRE_TAG_ID == 443

    def test_post_tag_id_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.POST_TAG_ID == 444

    def test_ocr_processing_tag_id_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.OCR_PROCESSING_TAG_ID is None

    def test_classify_pre_tag_id_defaults_to_post_tag_id(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_PRE_TAG_ID == s.POST_TAG_ID

    def test_classify_post_tag_id_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_POST_TAG_ID is None

    def test_classify_processing_tag_id_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_PROCESSING_TAG_ID is None

    def test_error_tag_id_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.ERROR_TAG_ID == 552

    def test_poll_interval_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.POLL_INTERVAL == 15

    def test_max_retries_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.MAX_RETRIES == 20

    def test_max_retry_backoff_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.MAX_RETRY_BACKOFF_SECONDS == 30

    def test_request_timeout_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.REQUEST_TIMEOUT == 180

    def test_llm_max_concurrent_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.LLM_MAX_CONCURRENT == 0

    def test_ocr_dpi_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.OCR_DPI == 300

    def test_ocr_max_side_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.OCR_MAX_SIDE == 1600

    def test_page_workers_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.PAGE_WORKERS == 8

    def test_document_workers_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.DOCUMENT_WORKERS == 4

    def test_log_level_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.LOG_LEVEL == "INFO"

    def test_log_format_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.LOG_FORMAT == "console"

    def test_classify_person_field_id_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_PERSON_FIELD_ID is None

    def test_classify_default_country_tag_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_DEFAULT_COUNTRY_TAG == ""

    def test_classify_max_chars_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_MAX_CHARS == 0

    def test_classify_max_tokens_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_MAX_TOKENS == 0

    def test_classify_tag_limit_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_TAG_LIMIT == 5

    def test_classify_taxonomy_limit_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_TAXONOMY_LIMIT == 100

    def test_classify_max_pages_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_MAX_PAGES == 3

    def test_classify_tail_pages_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_TAIL_PAGES == 2

    def test_classify_headerless_char_limit_default(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.CLASSIFY_HEADERLESS_CHAR_LIMIT == 15000

class TestCustomEnvVars:
    """Every env var can be overridden from its default."""

    def test_paperless_url(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "PAPERLESS_URL": "http://custom:9999"})
        assert s.PAPERLESS_URL == "http://custom:9999"

    def test_ai_models_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "AI_MODELS": "model-a, model-b"})
        assert s.AI_MODELS == ["model-a", "model-b"]

    def test_pre_tag_id_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "PRE_TAG_ID": "100"})
        assert s.PRE_TAG_ID == 100

    def test_post_tag_id_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "POST_TAG_ID": "200"})
        assert s.POST_TAG_ID == 200

    def test_poll_interval_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "POLL_INTERVAL": "60"})
        assert s.POLL_INTERVAL == 60

    def test_max_retries_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "MAX_RETRIES": "5"})
        assert s.MAX_RETRIES == 5

    def test_max_retry_backoff_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "MAX_RETRY_BACKOFF_SECONDS": "120"})
        assert s.MAX_RETRY_BACKOFF_SECONDS == 120

    def test_request_timeout_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "REQUEST_TIMEOUT": "60"})
        assert s.REQUEST_TIMEOUT == 60

    def test_llm_max_concurrent_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "LLM_MAX_CONCURRENT": "4"})
        assert s.LLM_MAX_CONCURRENT == 4

    def test_ocr_dpi_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_DPI": "600"})
        assert s.OCR_DPI == 600

    def test_ocr_max_side_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_MAX_SIDE": "2400"})
        assert s.OCR_MAX_SIDE == 2400

    def test_log_level_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "LOG_LEVEL": "debug"})
        assert s.LOG_LEVEL == "DEBUG"

    def test_log_format_json(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "LOG_FORMAT": "json"})
        assert s.LOG_FORMAT == "json"

    def test_classify_person_field_id_set(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_PERSON_FIELD_ID": "42"})
        assert s.CLASSIFY_PERSON_FIELD_ID == 42

    def test_classify_default_country_tag_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_DEFAULT_COUNTRY_TAG": " US "})
        assert s.CLASSIFY_DEFAULT_COUNTRY_TAG == "US"

    def test_classify_max_chars_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_MAX_CHARS": "5000"})
        assert s.CLASSIFY_MAX_CHARS == 5000

    def test_classify_max_tokens_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_MAX_TOKENS": "2048"})
        assert s.CLASSIFY_MAX_TOKENS == 2048

    def test_classify_tag_limit_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_TAG_LIMIT": "10"})
        assert s.CLASSIFY_TAG_LIMIT == 10

    def test_classify_taxonomy_limit_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_TAXONOMY_LIMIT": "50"})
        assert s.CLASSIFY_TAXONOMY_LIMIT == 50

    def test_classify_max_pages_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_MAX_PAGES": "10"})
        assert s.CLASSIFY_MAX_PAGES == 10

    def test_classify_tail_pages_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_TAIL_PAGES": "5"})
        assert s.CLASSIFY_TAIL_PAGES == 5

    def test_classify_headerless_char_limit_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_HEADERLESS_CHAR_LIMIT": "8000"})
        assert s.CLASSIFY_HEADERLESS_CHAR_LIMIT == 8000

    def test_error_tag_id_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "ERROR_TAG_ID": "999"})
        assert s.ERROR_TAG_ID == 999

    def test_ocr_processing_tag_id_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_PROCESSING_TAG_ID": "77"})
        assert s.OCR_PROCESSING_TAG_ID == 77

    def test_classify_pre_tag_id_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_PRE_TAG_ID": "555"})
        assert s.CLASSIFY_PRE_TAG_ID == 555

    def test_classify_post_tag_id_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_POST_TAG_ID": "666"})
        assert s.CLASSIFY_POST_TAG_ID == 666

    def test_classify_processing_tag_id_custom(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_PROCESSING_TAG_ID": "777"})
        assert s.CLASSIFY_PROCESSING_TAG_ID == 777

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
        env = {**_MINIMAL_OLLAMA_ENV, "OLLAMA_BASE_URL": "http://gpu:11434/v1/"}
        s = _build(mocker, env)
        assert s.OLLAMA_BASE_URL == "http://gpu:11434/v1/"

    def test_ollama_no_api_key(self, mocker):
        s = _build(mocker, _MINIMAL_OLLAMA_ENV)
        assert s.OPENAI_API_KEY is None

    def test_openai_provider_ollama_base_url_is_none(self, mocker):
        s = _build(mocker, _MINIMAL_ENV)
        assert s.OLLAMA_BASE_URL is None

class TestInvalidLLMProvider:

    def test_invalid_provider_raises(self, mocker):
        env = {**_MINIMAL_ENV, "LLM_PROVIDER": "anthropic"}
        with pytest.raises(ValueError, match="LLM_PROVIDER must be"):
            _build(mocker, env)

class TestInvalidLogFormat:

    def test_invalid_log_format_raises(self, mocker):
        env = {**_MINIMAL_ENV, "LOG_FORMAT": "xml"}
        with pytest.raises(ValueError, match="LOG_FORMAT must be"):
            _build(mocker, env)

class TestInvalidMaxRetries:

    def test_max_retries_zero_raises(self, mocker):
        env = {**_MINIMAL_ENV, "MAX_RETRIES": "0"}
        with pytest.raises(ValueError, match="MAX_RETRIES must be >= 1"):
            _build(mocker, env)

    def test_max_retries_negative_raises(self, mocker):
        env = {**_MINIMAL_ENV, "MAX_RETRIES": "-1"}
        with pytest.raises(ValueError, match="MAX_RETRIES must be >= 1"):
            _build(mocker, env)

class TestInvalidMaxRetryBackoff:

    def test_backoff_zero_raises(self, mocker):
        env = {**_MINIMAL_ENV, "MAX_RETRY_BACKOFF_SECONDS": "0"}
        with pytest.raises(ValueError, match="MAX_RETRY_BACKOFF_SECONDS must be >= 1"):
            _build(mocker, env)

    def test_backoff_negative_raises(self, mocker):
        env = {**_MINIMAL_ENV, "MAX_RETRY_BACKOFF_SECONDS": "-5"}
        with pytest.raises(ValueError, match="MAX_RETRY_BACKOFF_SECONDS must be >= 1"):
            _build(mocker, env)

class TestWorkerClamping:

    def test_page_workers_clamped_to_1(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "PAGE_WORKERS": "0"})
        assert s.PAGE_WORKERS == 1

    def test_page_workers_negative_clamped_to_1(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "PAGE_WORKERS": "-5"})
        assert s.PAGE_WORKERS == 1

    def test_document_workers_clamped_to_1(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "DOCUMENT_WORKERS": "0"})
        assert s.DOCUMENT_WORKERS == 1

    def test_document_workers_negative_clamped_to_1(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "DOCUMENT_WORKERS": "-3"})
        assert s.DOCUMENT_WORKERS == 1

class TestOcrProcessingTagId:

    def test_negative_becomes_none(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_PROCESSING_TAG_ID": "-1"})
        assert s.OCR_PROCESSING_TAG_ID is None

    def test_zero_becomes_none(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_PROCESSING_TAG_ID": "0"})
        assert s.OCR_PROCESSING_TAG_ID is None

    def test_empty_string_becomes_none(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_PROCESSING_TAG_ID": ""})
        assert s.OCR_PROCESSING_TAG_ID is None

    def test_positive_value_kept(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "OCR_PROCESSING_TAG_ID": "42"})
        assert s.OCR_PROCESSING_TAG_ID == 42

class TestClassifyPostTagId:

    def test_negative_becomes_none(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_POST_TAG_ID": "-1"})
        assert s.CLASSIFY_POST_TAG_ID is None

    def test_zero_becomes_none(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_POST_TAG_ID": "0"})
        assert s.CLASSIFY_POST_TAG_ID is None

class TestClassifyProcessingTagId:

    def test_negative_becomes_none(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_PROCESSING_TAG_ID": "-5"})
        assert s.CLASSIFY_PROCESSING_TAG_ID is None

class TestErrorTagId:

    def test_negative_becomes_none(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "ERROR_TAG_ID": "-1"})
        assert s.ERROR_TAG_ID is None

    def test_zero_becomes_none(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "ERROR_TAG_ID": "0"})
        assert s.ERROR_TAG_ID is None

    def test_positive_kept(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "ERROR_TAG_ID": "99"})
        assert s.ERROR_TAG_ID == 99

class TestAiModelsValidation:

    def test_all_commas_raises(self, mocker):
        env = {**_MINIMAL_ENV, "AI_MODELS": ",,, ,"}
        with pytest.raises(ValueError, match="AI_MODELS must contain at least one model"):
            _build(mocker, env)

    def test_empty_string_raises(self, mocker):
        env = {**_MINIMAL_ENV, "AI_MODELS": ""}
        with pytest.raises(ValueError, match="AI_MODELS must contain at least one model"):
            _build(mocker, env)

    def test_single_model(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "AI_MODELS": "model-a"})
        assert s.AI_MODELS == ["model-a"]

    def test_whitespace_stripped(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "AI_MODELS": " model-a , model-b "})
        assert s.AI_MODELS == ["model-a", "model-b"]

class TestOcrRefusalMarkers:

    def test_custom_markers(self, mocker):
        env = {**_MINIMAL_ENV, "OCR_REFUSAL_MARKERS": "forbidden,blocked, nope "}
        s = _build(mocker, env)
        assert s.OCR_REFUSAL_MARKERS == ["forbidden", "blocked", "nope"]

    def test_custom_markers_lowered(self, mocker):
        env = {**_MINIMAL_ENV, "OCR_REFUSAL_MARKERS": "FORBIDDEN,Blocked"}
        s = _build(mocker, env)
        assert s.OCR_REFUSAL_MARKERS == ["forbidden", "blocked"]

    def test_empty_markers_returns_empty(self, mocker):
        env = {**_MINIMAL_ENV, "OCR_REFUSAL_MARKERS": ",,,"}
        s = _build(mocker, env)
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
        env = {**_MINIMAL_ENV, "OCR_INCLUDE_PAGE_MODELS": "maybe"}
        with pytest.raises(ValueError, match="must be a boolean value"):
            _build(mocker, env)

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

class TestClassifyClamping:

    def test_classify_max_tokens_negative_clamped(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_MAX_TOKENS": "-10"})
        assert s.CLASSIFY_MAX_TOKENS == 0

    def test_classify_tag_limit_negative_clamped(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_TAG_LIMIT": "-1"})
        assert s.CLASSIFY_TAG_LIMIT == 0

    def test_classify_taxonomy_limit_negative_clamped(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_TAXONOMY_LIMIT": "-1"})
        assert s.CLASSIFY_TAXONOMY_LIMIT == 0

    def test_classify_max_pages_negative_clamped(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_MAX_PAGES": "-1"})
        assert s.CLASSIFY_MAX_PAGES == 0

    def test_classify_tail_pages_negative_clamped(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_TAIL_PAGES": "-1"})
        assert s.CLASSIFY_TAIL_PAGES == 0

    def test_classify_headerless_char_limit_negative_clamped(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CLASSIFY_HEADERLESS_CHAR_LIMIT": "-5"})
        assert s.CLASSIFY_HEADERLESS_CHAR_LIMIT == 0

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
