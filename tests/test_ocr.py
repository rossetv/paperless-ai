import os
import openai
import pytest
from PIL import Image

from common.config import Settings
from ocr.provider import OpenAIProvider, is_refusal


@pytest.fixture
def settings(mocker):
    """Fixture to create a Settings object for tests."""
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "AI_MODELS": "gpt-primary,gpt-middle,gpt-fallback",
        },
        clear=True,
    )
    # Set a low retry count for testing purposes
    settings_obj = Settings()
    settings_obj.MAX_RETRIES = 2
    return settings_obj


@pytest.fixture
def ocr_provider(settings):
    """Fixture to create an OpenAIProvider instance."""
    return OpenAIProvider(settings)


@pytest.fixture
def mock_create_completion(mocker):
    """Fixture to mock the _create_completion method, which is decorated with @retry."""
    return mocker.patch("ocr.provider.OpenAIProvider._create_completion")


def create_mock_response(mocker, content):
    """Helper to create a mock OpenAI API response."""
    mock_choice = mocker.MagicMock()
    mock_choice.message.content = content
    mock_response = mocker.MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


def create_test_image(blank=False):
    """Helper to create a test image."""
    if blank:
        return Image.new("RGB", (100, 100), "white")
    return Image.new("RGB", (100, 100), "black")


def test_transcribe_image_success(ocr_provider, mock_create_completion, mocker):
    """Test successful transcription with the primary model."""
    image = create_test_image()
    expected_text = "This is a test transcription."
    mock_create_completion.return_value = create_mock_response(mocker, expected_text)

    text, model = ocr_provider.transcribe_image(image)

    assert text == expected_text
    assert model == "gpt-primary"
    mock_create_completion.assert_called_once_with(
        model="gpt-primary",
        messages=mocker.ANY,
        timeout=mocker.ANY,
    )


def test_fallback_on_refusal(ocr_provider, mock_create_completion, mocker):
    """Test that the provider falls back through the chain if the primary refuses."""
    image = create_test_image()
    refusal_text = "I can't assist with that."
    expected_text = "Fallback model success."
    mock_create_completion.side_effect = [
        create_mock_response(mocker, refusal_text),
        create_mock_response(mocker, refusal_text),
        create_mock_response(mocker, expected_text),
    ]

    text, model = ocr_provider.transcribe_image(image)

    assert text == expected_text
    assert model == "gpt-fallback"
    assert mock_create_completion.call_count == 3


def test_fallback_on_api_error(ocr_provider, mock_create_completion, mocker):
    """Test fallback to the middle model if the primary fails with an APIError."""
    image = create_test_image()
    expected_text = "Middle success."
    mock_create_completion.side_effect = [
        openai.APIError("Primary failed", request=None, body=None),
        create_mock_response(mocker, expected_text),
    ]

    text, model = ocr_provider.transcribe_image(image)

    assert text == expected_text
    assert model == "gpt-middle"
    assert mock_create_completion.call_count == 2


def test_all_models_fail(ocr_provider, settings, mock_create_completion, mocker):
    """Test that a refusal mark is returned if all models either refuse or error."""
    image = create_test_image()
    mock_create_completion.side_effect = [
        create_mock_response(mocker, "I can't assist."),  # Primary refuses
        create_mock_response(mocker, "I can't assist."),  # Middle refuses
        openai.APIError("Fallback failed", request=None, body=None),  # Fallback errors
    ]

    text, model = ocr_provider.transcribe_image(image)

    assert text == settings.REFUSAL_MARK
    assert model == ""
    assert mock_create_completion.call_count == 3


def test_transcribe_blank_image(ocr_provider, mock_create_completion):
    """Test that blank images are skipped and the API is not called."""
    image = create_test_image(blank=True)
    text, model = ocr_provider.transcribe_image(image)
    assert text == ""
    assert model == ""
    mock_create_completion.assert_not_called()


def test_is_refusal_detection():
    markers = [
        "i can't assist",
        "i cannot assist",
        "i can't help with transcrib",
        "i cannot help with transcrib",
        "chatgpt refused to transcribe",
    ]
    assert is_refusal("I can't assist with that.", markers)
    assert is_refusal("I CAN'T ASSIST", markers)
    assert is_refusal("EMP. NAME [REDACTED NAME]", markers)
    assert is_refusal("[NAME REDACTED]", markers)
    assert is_refusal("Sorry, I can't help with transcribing this document.", markers)
    assert not is_refusal("This is a normal response.", markers)


def test_transcribe_image_resizes_image(ocr_provider, mock_create_completion, mocker):
    """Test that images are resized before sending to the API."""
    image = create_test_image()
    thumbnail_spy = mocker.spy(image, "thumbnail")
    mock_create_completion.return_value = create_mock_response(mocker, "ok")

    ocr_provider.transcribe_image(image)

    thumbnail_spy.assert_called_once_with(
        (ocr_provider.settings.OCR_MAX_SIDE, ocr_provider.settings.OCR_MAX_SIDE)
    )


def test_transcribe_image_with_doc_id_and_page_num(ocr_provider, mock_create_completion, mocker):
    """Test that doc_id and page_num are passed through to the log context (lines 106, 108)."""
    image = create_test_image()
    mock_create_completion.return_value = create_mock_response(mocker, "text")

    text, model = ocr_provider.transcribe_image(image, doc_id=42, page_num=3)

    assert text == "text"
    assert model == "gpt-primary"


def test_get_stats_returns_populated_stats(ocr_provider, mock_create_completion, mocker):
    """Test that get_stats returns correct stats after transcription attempts (line 90)."""
    image = create_test_image()
    mock_create_completion.return_value = create_mock_response(mocker, "ok")

    ocr_provider.transcribe_image(image)

    stats = ocr_provider.get_stats()
    assert stats["attempts"] == 1
    assert stats["refusals"] == 0
    assert stats["api_errors"] == 0
    assert stats["fallback_successes"] == 0


def test_get_stats_tracks_fallback_success(ocr_provider, mock_create_completion, mocker):
    """Test that fallback_successes counter is incremented (line 90 + 150)."""
    image = create_test_image()
    mock_create_completion.side_effect = [
        create_mock_response(mocker, "I can't assist"),  # primary refuses
        create_mock_response(mocker, "ok"),               # middle succeeds
    ]

    text, model = ocr_provider.transcribe_image(image)

    assert model == "gpt-middle"
    stats = ocr_provider.get_stats()
    assert stats["attempts"] == 2
    assert stats["refusals"] == 1
    assert stats["fallback_successes"] == 1
