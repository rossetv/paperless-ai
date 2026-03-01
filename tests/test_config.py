import os

import pytest
from common.config import Settings
from common.library_setup import setup_libraries


def test_settings_default_values(mocker):
    """
    Test that the Settings class loads default values correctly when no
    environment variables are set.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
        },
        clear=True,
    )

    settings = Settings()

    assert settings.PAPERLESS_URL == "http://paperless:8000"
    assert settings.LLM_PROVIDER == "openai"
    assert settings.AI_MODELS == ["gpt-5-mini", "gpt-5.2", "o4-mini"]
    assert settings.OCR_REFUSAL_MARKERS == [
        "i can't assist",
        "i cannot assist",
        "i can't help with transcrib",
        "i cannot help with transcrib",
        "chatgpt refused to transcribe",
    ]
    assert settings.OCR_INCLUDE_PAGE_MODELS is False
    assert settings.OCR_PROCESSING_TAG_ID is None
    assert settings.POLL_INTERVAL == 15
    assert settings.MAX_RETRY_BACKOFF_SECONDS == 30
    assert settings.OCR_DPI == 300
    assert settings.CLASSIFY_PRE_TAG_ID == settings.POST_TAG_ID
    assert settings.CLASSIFY_POST_TAG_ID is None
    assert settings.CLASSIFY_PROCESSING_TAG_ID is None
    assert settings.CLASSIFY_MAX_TOKENS == 0
    assert settings.CLASSIFY_TAG_LIMIT == 5
    assert settings.CLASSIFY_TAXONOMY_LIMIT == 100
    assert settings.CLASSIFY_MAX_PAGES == 3
    assert settings.CLASSIFY_TAIL_PAGES == 2
    assert settings.CLASSIFY_HEADERLESS_CHAR_LIMIT == 15000
    assert settings.ERROR_TAG_ID == 552


def test_settings_from_environment_variables(mocker):
    """
    Test that the Settings class correctly loads values from environment variables.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_URL": "http://test-paperless:1234/",
            "PAPERLESS_TOKEN": "env_token",
            "OPENAI_API_KEY": "env_api_key",
            "LLM_PROVIDER": "ollama",
            "OLLAMA_BASE_URL": "http://ollama:11434/v1",
            "PRE_TAG_ID": "101",
            "OCR_PROCESSING_TAG_ID": "333",
            "POLL_INTERVAL": "30",
            "AI_MODELS": "model-a, model-b , model-c",
            "OCR_REFUSAL_MARKERS": "nope, nope again",
            "OCR_INCLUDE_PAGE_MODELS": "true",
            "MAX_RETRY_BACKOFF_SECONDS": "12",
            "CLASSIFY_PRE_TAG_ID": "555",
            "CLASSIFY_POST_TAG_ID": "556",
            "CLASSIFY_PROCESSING_TAG_ID": "777",
            "CLASSIFY_DEFAULT_COUNTRY_TAG": "Ireland",
            "CLASSIFY_MAX_PAGES": "2",
            "CLASSIFY_TAIL_PAGES": "3",
            "CLASSIFY_MAX_TOKENS": "250",
            "CLASSIFY_TAXONOMY_LIMIT": "45",
            "ERROR_TAG_ID": "999",
            "CLASSIFY_HEADERLESS_CHAR_LIMIT": "1200",
        },
        clear=True,
    )

    settings = Settings()

    assert settings.PAPERLESS_URL == "http://test-paperless:1234"
    assert settings.PAPERLESS_TOKEN == "env_token"
    assert settings.LLM_PROVIDER == "ollama"
    assert settings.OLLAMA_BASE_URL == "http://ollama:11434/v1"
    assert settings.AI_MODELS == ["model-a", "model-b", "model-c"]
    assert settings.OCR_REFUSAL_MARKERS == ["nope", "nope again"]
    assert settings.OCR_INCLUDE_PAGE_MODELS is True
    assert settings.PRE_TAG_ID == 101
    assert settings.OCR_PROCESSING_TAG_ID == 333
    assert settings.POLL_INTERVAL == 30
    assert settings.MAX_RETRY_BACKOFF_SECONDS == 12
    assert settings.CLASSIFY_PRE_TAG_ID == 555
    assert settings.CLASSIFY_POST_TAG_ID == 556
    assert settings.CLASSIFY_PROCESSING_TAG_ID == 777
    assert settings.CLASSIFY_DEFAULT_COUNTRY_TAG == "Ireland"
    assert settings.CLASSIFY_MAX_PAGES == 2
    assert settings.CLASSIFY_TAIL_PAGES == 3
    assert settings.CLASSIFY_MAX_TOKENS == 250
    assert settings.CLASSIFY_TAXONOMY_LIMIT == 45
    assert settings.CLASSIFY_HEADERLESS_CHAR_LIMIT == 1200
    assert settings.ERROR_TAG_ID == 999


def test_settings_missing_required_env_vars(mocker):
    """
    Test that the Settings class raises a ValueError if a required environment
    variable is not set.
    """
    mocker.patch.dict(os.environ, {}, clear=True)

    with pytest.raises(
        ValueError, match="Required environment variable 'PAPERLESS_TOKEN' is not set."
    ):
        Settings()

    mocker.patch.dict(os.environ, {"PAPERLESS_TOKEN": "some-token"}, clear=True)

    with pytest.raises(
        ValueError, match="Required environment variable 'OPENAI_API_KEY' is not set."
    ):
        Settings()


def test_ollama_configuration(mocker):
    """
    Test that the settings for the Ollama provider are configured correctly.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "LLM_PROVIDER": "ollama",
        },
        clear=True,
    )

    settings = Settings()
    setup_libraries(settings)  # This should configure the openai client

    import openai

    assert settings.LLM_PROVIDER == "ollama"
    assert settings.AI_MODELS == ["gemma3:27b", "gemma3:12b"]
    assert openai.base_url == "http://localhost:11434/v1/"
    assert openai.api_key == "dummy"


def test_invalid_llm_provider(mocker):
    """
    Test that an invalid LLM_PROVIDER value raises a ValueError.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "LLM_PROVIDER": "invalid_provider",
        },
        clear=True,
    )

    with pytest.raises(ValueError, match="LLM_PROVIDER must be 'openai' or 'ollama'"):
        Settings()


def test_invalid_log_format(mocker):
    """
    Test that an invalid LOG_FORMAT value raises a ValueError.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "LOG_FORMAT": "xml",
        },
        clear=True,
    )

    with pytest.raises(ValueError, match="LOG_FORMAT must be 'json' or 'console'"):
        Settings()


def test_invalid_max_retries(mocker):
    """
    Test that MAX_RETRIES must be at least 1.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "MAX_RETRIES": "0",
        },
        clear=True,
    )

    with pytest.raises(ValueError, match="MAX_RETRIES must be >= 1"):
        Settings()


def test_invalid_max_retry_backoff_seconds(mocker):
    """
    Test that MAX_RETRY_BACKOFF_SECONDS must be at least 1.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "MAX_RETRY_BACKOFF_SECONDS": "0",
        },
        clear=True,
    )

    with pytest.raises(ValueError, match="MAX_RETRY_BACKOFF_SECONDS must be >= 1"):
        Settings()


def test_minimum_worker_counts(mocker):
    """
    Test that worker counts are clamped to a minimum of 1.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "PAGE_WORKERS": "0",
            "DOCUMENT_WORKERS": "-5",
        },
        clear=True,
    )

    settings = Settings()

    assert settings.PAGE_WORKERS == 1
    assert settings.DOCUMENT_WORKERS == 1


def test_ocr_processing_tag_id_negative_becomes_none(mocker):
    """
    Test that OCR_PROCESSING_TAG_ID is set to None when given a negative value.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "OCR_PROCESSING_TAG_ID": "-1",
        },
        clear=True,
    )

    settings = Settings()

    assert settings.OCR_PROCESSING_TAG_ID is None


def test_classify_post_tag_id_negative_becomes_none(mocker):
    """
    Test that CLASSIFY_POST_TAG_ID is set to None when given a negative value.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "CLASSIFY_POST_TAG_ID": "-1",
        },
        clear=True,
    )

    settings = Settings()

    assert settings.CLASSIFY_POST_TAG_ID is None


def test_classify_processing_tag_id_negative_becomes_none(mocker):
    """
    Test that CLASSIFY_PROCESSING_TAG_ID is set to None when given a negative value.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "CLASSIFY_PROCESSING_TAG_ID": "-1",
        },
        clear=True,
    )

    settings = Settings()

    assert settings.CLASSIFY_PROCESSING_TAG_ID is None


def test_error_tag_id_negative_becomes_none(mocker):
    """
    Test that ERROR_TAG_ID is set to None when given a negative value.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "ERROR_TAG_ID": "-1",
        },
        clear=True,
    )

    settings = Settings()

    assert settings.ERROR_TAG_ID is None


def test_ai_models_all_commas_raises_value_error(mocker):
    """
    Test that AI_MODELS set to only commas raises a ValueError because no
    valid model names are present after splitting.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "AI_MODELS": ",,,",
        },
        clear=True,
    )

    with pytest.raises(ValueError, match="AI_MODELS must contain at least one model name"):
        Settings()


def test_get_list_env_with_custom_ocr_refusal_markers(mocker):
    """
    Test that _get_list_env returns parsed values when the OCR_REFUSAL_MARKERS
    environment variable is set to a custom comma-separated list.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "OCR_REFUSAL_MARKERS": "marker one, marker two, marker three",
        },
        clear=True,
    )

    settings = Settings()

    assert settings.OCR_REFUSAL_MARKERS == ["marker one", "marker two", "marker three"]


def test_get_optional_int_env_empty_string_returns_default(mocker):
    """
    Test that _get_optional_int_env returns the default when the env var is set
    to an empty (whitespace-only) string.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "OCR_PROCESSING_TAG_ID": "   ",
        },
        clear=True,
    )

    settings = Settings()

    assert settings.OCR_PROCESSING_TAG_ID is None


def test_get_bool_env_false_string(mocker):
    """
    Test that _get_bool_env correctly returns False when the env var is set to
    a recognized falsey string like "0".
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "OCR_INCLUDE_PAGE_MODELS": "0",
        },
        clear=True,
    )

    settings = Settings()

    assert settings.OCR_INCLUDE_PAGE_MODELS is False


def test_get_bool_env_invalid_value_raises_value_error(mocker):
    """
    Test that _get_bool_env raises a ValueError when the env var is set to a
    value that is not a recognized boolean string.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "OCR_INCLUDE_PAGE_MODELS": "maybe",
        },
        clear=True,
    )

    with pytest.raises(
        ValueError, match="OCR_INCLUDE_PAGE_MODELS must be a boolean value"
    ):
        Settings()


def test_setup_libraries_restores_proxies(mocker):
    """
    Test that proxy environment variables are restored after setup.
    """
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "HTTP_PROXY": "http://proxy.local",
            "HTTPS_PROXY": "https://proxy.local",
        },
        clear=True,
    )

    settings = Settings()
    setup_libraries(settings)

    assert os.environ.get("HTTP_PROXY") == "http://proxy.local"
    assert os.environ.get("HTTPS_PROXY") == "https://proxy.local"
