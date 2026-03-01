"""Extended tests for classifier.provider — compatibility handling."""

import json
import os

import httpx
import openai
import pytest

from classifier.provider import ClassificationProvider
from common.config import Settings


def create_mock_response(mocker, content):
    mock_choice = mocker.MagicMock()
    mock_choice.message.content = content
    mock_response = mocker.MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


def create_bad_request_error(message: str) -> openai.BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "https://example.com"))
    return openai.BadRequestError(message, response=response, body=None)


def create_api_error(message: str) -> openai.APIError:
    request = httpx.Request("POST", "https://example.com")
    return openai.APIError(message, request=request, body=None)


@pytest.fixture
def settings(mocker):
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "AI_MODELS": "primary-model,fallback-model",
        },
        clear=True,
    )
    s = Settings()
    s.MAX_RETRIES = 1
    return s


VALID_JSON = json.dumps({
    "title": "Ok", "correspondent": "", "tags": [],
    "document_date": "2025-05-01", "document_type": "Invoice",
    "language": "en", "person": "",
})


def test_response_format_error_retries_without_it(settings, mocker):
    provider = ClassificationProvider(settings)
    mock_create = mocker.patch(
        "classifier.provider.ClassificationProvider._create_completion"
    )
    err = create_bad_request_error("response_format is not supported for this model")
    mock_create.side_effect = [err, create_mock_response(mocker, VALID_JSON)]

    result, model = provider.classify_text("text", ["A"], ["B"], ["C"])
    assert result is not None
    assert model == "primary-model"


def test_max_tokens_error_retries_without_it(settings, mocker):
    settings.CLASSIFY_MAX_TOKENS = 100
    provider = ClassificationProvider(settings)
    mock_create = mocker.patch(
        "classifier.provider.ClassificationProvider._create_completion"
    )
    err = create_bad_request_error("max_tokens is not supported")
    mock_create.side_effect = [err, create_mock_response(mocker, VALID_JSON)]

    result, model = provider.classify_text("text", ["A"], ["B"], ["C"])
    assert result is not None


def test_api_error_falls_through_to_next_model(settings, mocker):
    provider = ClassificationProvider(settings)
    mock_create = mocker.patch(
        "classifier.provider.ClassificationProvider._create_completion"
    )
    err = create_api_error("server error")
    mock_create.side_effect = [err, create_mock_response(mocker, VALID_JSON)]

    result, model = provider.classify_text("text", ["A"], ["B"], ["C"])
    assert result is not None
    assert model == "fallback-model"


def test_all_models_fail_returns_none(settings, mocker):
    provider = ClassificationProvider(settings)
    mock_create = mocker.patch(
        "classifier.provider.ClassificationProvider._create_completion"
    )
    err = create_api_error("server error")
    mock_create.side_effect = [err, err]

    result, model = provider.classify_text("text", ["A"], ["B"], ["C"])
    assert result is None
    assert model == ""


def test_empty_text_returns_none(settings):
    provider = ClassificationProvider(settings)
    result, model = provider.classify_text("", ["A"], ["B"], ["C"])
    assert result is None
    assert model == ""


def test_whitespace_text_returns_none(settings):
    provider = ClassificationProvider(settings)
    result, model = provider.classify_text("   ", ["A"], ["B"], ["C"])
    assert result is None
    assert model == ""


def test_bad_request_unrelated_falls_through(settings, mocker):
    provider = ClassificationProvider(settings)
    mock_create = mocker.patch(
        "classifier.provider.ClassificationProvider._create_completion"
    )
    err = create_bad_request_error("some other bad request error")
    mock_create.side_effect = [err, create_mock_response(mocker, VALID_JSON)]

    result, model = provider.classify_text("text", ["A"], ["B"], ["C"])
    # First model returned None, fallback succeeds
    assert result is not None
    assert model == "fallback-model"


def test_response_format_for_ollama(settings, mocker):
    settings.LLM_PROVIDER = "ollama"
    provider = ClassificationProvider(settings)
    assert provider._response_format() is None


def test_response_format_for_openai(settings, mocker):
    settings.LLM_PROVIDER = "openai"
    provider = ClassificationProvider(settings)
    fmt = provider._response_format()
    assert fmt is not None
    assert fmt["type"] == "json_schema"


def test_truncation_note_passed_to_user_message(settings, mocker):
    provider = ClassificationProvider(settings)
    mock_create = mocker.patch(
        "classifier.provider.ClassificationProvider._create_completion"
    )
    mock_create.return_value = create_mock_response(mocker, VALID_JSON)

    provider.classify_text(
        "text", ["A"], ["B"], ["C"],
        truncation_note="Document was truncated.",
    )

    call_kwargs = mock_create.call_args[1]
    user_msg = call_kwargs["messages"][1]["content"]
    assert "Document was truncated." in user_msg


def test_get_stats_returns_copy(settings):
    provider = ClassificationProvider(settings)
    provider._reset_stats()
    stats = provider.get_stats()
    stats["attempts"] = 999
    assert provider.get_stats()["attempts"] == 0


def test_content_none_handled(settings, mocker):
    """When API returns content=None, it should not crash."""
    provider = ClassificationProvider(settings)
    mock_create = mocker.patch(
        "classifier.provider.ClassificationProvider._create_completion"
    )
    mock_resp = create_mock_response(mocker, None)
    mock_resp.choices[0].message.content = None
    good_resp = create_mock_response(mocker, VALID_JSON)
    mock_create.side_effect = [mock_resp, good_resp]

    result, model = provider.classify_text("text", ["A"], ["B"], ["C"])
    # None content on primary → parse error → fallback succeeds
    assert result is not None
    assert model == "fallback-model"


# ---------------------------------------------------------------------------
# Lines 127-131: _create_with_compat hitting _MAX_COMPAT_RETRIES bound
# ---------------------------------------------------------------------------


def test_create_with_compat_exhausts_all_params_then_rejects(settings, mocker):
    """After stripping all 3 compat params, a 4th error falls through to rejection."""
    settings.CLASSIFY_MAX_TOKENS = 100
    settings.LLM_PROVIDER = "openai"
    provider = ClassificationProvider(settings)
    provider._reset_stats()

    mock_create = mocker.patch(
        "classifier.provider.ClassificationProvider._create_completion"
    )
    # Each error strips one param: temperature, then response_format, then max_tokens.
    # The 4th error is unrecognised (the stripped param is no longer in the dict),
    # so it falls through to "Classification request rejected".
    err_temp = create_bad_request_error("temperature unsupported for this model")
    err_fmt = create_bad_request_error("response_format is not supported")
    err_max = create_bad_request_error("max_tokens is not supported")
    err_final = create_bad_request_error("something else entirely")

    mock_create.side_effect = [err_temp, err_fmt, err_max, err_final]

    params = provider._build_params("test-model", [{"role": "user", "content": "hi"}])
    result = provider._create_with_compat(params, "test-model")

    assert result is None
    assert provider._stats["api_errors"] == 1
    assert provider._stats["temperature_retries"] == 1
    assert provider._stats["response_format_retries"] == 1
    assert provider._stats["max_tokens_retries"] == 1


def test_create_with_compat_bound_prevents_further_retries(settings, mocker):
    """When _MAX_COMPAT_RETRIES is reached, compat adjustments stop even if recognisable."""
    settings.CLASSIFY_MAX_TOKENS = 100
    settings.LLM_PROVIDER = "openai"
    provider = ClassificationProvider(settings)
    provider._reset_stats()
    # Lower the bound to 1 so we can hit it without exhausting all params.
    provider._MAX_COMPAT_RETRIES = 1

    mock_create = mocker.patch(
        "classifier.provider.ClassificationProvider._create_completion"
    )
    err_temp = create_bad_request_error("temperature unsupported for this model")
    # Second error is also a compat error (response_format) but bound is already hit.
    err_fmt = create_bad_request_error("response_format is not supported")

    mock_create.side_effect = [err_temp, err_fmt]

    params = provider._build_params("test-model", [{"role": "user", "content": "hi"}])
    result = provider._create_with_compat(params, "test-model")

    assert result is None
    # Only 1 compat retry happened (temperature), then bound prevented the second.
    assert provider._stats["temperature_retries"] == 1
    assert provider._stats["response_format_retries"] == 0
    assert provider._stats["api_errors"] == 1


# ---------------------------------------------------------------------------
# Line 248: _build_params with non-gpt-5 model and CLASSIFY_MAX_TOKENS=0
# ---------------------------------------------------------------------------


def test_build_params_temperature_included_max_tokens_excluded(settings, mocker):
    """Non-gpt-5 model supports temperature; CLASSIFY_MAX_TOKENS=0 means no max_tokens."""
    settings.CLASSIFY_MAX_TOKENS = 0
    settings.LLM_PROVIDER = "ollama"  # no response_format for ollama
    provider = ClassificationProvider(settings)

    messages = [{"role": "user", "content": "test"}]
    params = provider._build_params("claude-3", messages)

    # temperature IS present (non-gpt-5 model)
    assert "temperature" in params
    # max_tokens is NOT present (CLASSIFY_MAX_TOKENS=0)
    assert "max_tokens" not in params
    # response_format is NOT present (ollama provider)
    assert "response_format" not in params


# ---------------------------------------------------------------------------
# Line 248: _build_user_message when CLASSIFY_TAG_LIMIT == 0
# ---------------------------------------------------------------------------


def test_build_user_message_zero_tag_limit(settings, mocker):
    """When CLASSIFY_TAG_LIMIT is 0, the user message includes the zero-tag guidance (line 248)."""
    settings.CLASSIFY_TAG_LIMIT = 0
    provider = ClassificationProvider(settings)

    message = provider._build_user_message(
        "some document text", ["ACME"], ["Invoice"], ["Bills"], None
    )

    assert "return no optional tags" in message
    assert "no more than" not in message


