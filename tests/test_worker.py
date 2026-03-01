import os
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from common.config import Settings
from ocr.worker import DocumentProcessor


@pytest.fixture
def settings(mocker):
    mocker.patch.dict(
        os.environ,
        {
            "PAPERLESS_TOKEN": "test_token",
            "OPENAI_API_KEY": "test_api_key",
            "PRE_TAG_ID": "10",
            "POST_TAG_ID": "11",
        },
        clear=True,
    )
    return Settings()


@pytest.fixture
def mock_doc(settings):
    return {"id": 1, "title": "Test Document", "tags": [settings.PRE_TAG_ID]}


def _png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _tiff_bytes(frames: list[Image.Image]) -> bytes:
    buffer = BytesIO()
    frames[0].save(
        buffer,
        format="TIFF",
        save_all=True,
        append_images=frames[1:],
    )
    return buffer.getvalue()


def create_test_image(color: str = "black") -> Image.Image:
    return Image.new("RGB", (50, 50), color)


@patch("ocr.image_converter.convert_from_bytes")
def test_process_document_success(
    mock_convert,
    settings,
    mock_doc,
):
    paperless = MagicMock()
    paperless.get_document.return_value = {"id": 1, "title": "Test Document", "tags": [10]}
    paperless.download_content.return_value = (b"file_content", "application/pdf")

    ocr_provider = MagicMock()
    ocr_provider.transcribe_image.side_effect = [
        ("Page 1 text", "model-a"),
        ("Page 2 text", "model-b"),
    ]

    mock_convert.return_value = [create_test_image(), create_test_image()]

    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)
    processor.process()

    paperless.download_content.assert_called_once_with(1)
    mock_convert.assert_called_once_with(b"file_content", dpi=settings.OCR_DPI)
    assert ocr_provider.transcribe_image.call_count == 2

    paperless.update_document.assert_called_once()
    args, _ = paperless.update_document.call_args
    assert args[0] == 1
    assert "--- Page 1 ---" in args[1]
    assert "--- Page 2 ---" in args[1]
    assert "Transcribed by model: model-a, model-b" in args[1]
    assert set(args[2]) == {settings.POST_TAG_ID}


@patch("ocr.image_converter.convert_from_bytes", return_value=[])
def test_process_document_with_no_images(
    mock_convert,
    settings,
    mock_doc,
):
    paperless = MagicMock()
    paperless.get_document.return_value = {"id": 1, "title": "Test Document", "tags": [10]}
    paperless.download_content.return_value = (b"file_content", "application/pdf")
    ocr_provider = MagicMock()

    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)
    processor.process()

    paperless.download_content.assert_called_once_with(1)
    mock_convert.assert_called_once_with(b"file_content", dpi=settings.OCR_DPI)
    ocr_provider.transcribe_image.assert_not_called()
    paperless.update_document.assert_not_called()


@patch("ocr.image_converter.convert_from_bytes")
def test_process_closes_images_when_pages_fail(mock_convert, settings, mock_doc):
    paperless = MagicMock()
    paperless.get_document.return_value = {"id": 1, "title": "Test Document", "tags": [10]}
    paperless.download_content.return_value = (b"file_content", "application/pdf")

    img1 = MagicMock()
    img2 = MagicMock()
    mock_convert.return_value = [img1, img2]

    ocr_provider = MagicMock()

    def side_effect(image, *args, **kwargs):
        if image is img2:
            raise RuntimeError("ocr failed")
        return ("ok", "model-a")

    ocr_provider.transcribe_image.side_effect = side_effect

    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)
    processor.process()

    assert img1.close.called
    assert img2.close.called

    paperless.update_document.assert_called_once()
    args, _ = paperless.update_document.call_args
    assert args[0] == 1
    assert "[OCR ERROR]" in args[1]
    assert set(args[2]) == {settings.ERROR_TAG_ID}


def test_bytes_to_images_non_pdf_single_frame(settings, mock_doc):
    paperless = MagicMock()
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    image = create_test_image()
    images = processor._bytes_to_images(_png_bytes(image), "image/png")

    assert len(images) == 1
    assert images[0].size == image.size


def test_bytes_to_images_non_pdf_multi_frame_tiff(settings, mock_doc):
    paperless = MagicMock()
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    frames = [create_test_image("black"), create_test_image("white")]
    images = processor._bytes_to_images(_tiff_bytes(frames), "image/tiff")

    assert len(images) == 2


def test_bytes_to_images_invalid_image_raises(settings, mock_doc):
    paperless = MagicMock()
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    with pytest.raises(RuntimeError, match="Unable to open image"):
        processor._bytes_to_images(b"not an image", "image/png")


def test_ocr_pages_in_parallel_handles_errors_and_order(settings, mock_doc):
    paperless = MagicMock()
    ocr_provider = MagicMock()

    settings.PAGE_WORKERS = 2
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    images = [create_test_image(), create_test_image(), create_test_image()]
    for index, image in enumerate(images):
        image.info["index"] = index

    def side_effect(image, *args, **kwargs):
        index = image.info["index"]
        if index == 1:
            raise RuntimeError("ocr failed")
        return (f"text-{index}", f"model-{index}")

    ocr_provider.transcribe_image.side_effect = side_effect

    results, failed_pages = processor._ocr_pages_in_parallel(images)

    assert results[0] == ("text-0", "model-0")
    assert results[1][0].startswith("[OCR ERROR]")
    assert results[2] == ("text-2", "model-2")
    assert failed_pages == [2]


def test_assemble_full_text_skips_blank_pages(settings, mock_doc):
    paperless = MagicMock()
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    images = [create_test_image(), create_test_image(), create_test_image()]
    page_results = [
        ("Page 1 text", "model-a"),
        ("   ", ""),
        ("Page 3 text", "model-b"),
    ]

    full_text, models_used = processor._assemble_full_text(len(images), page_results)

    expected = (
        "--- Page 1 ---\n"
        "Page 1 text\n\n"
        "--- Page 3 ---\n"
        "Page 3 text\n\n"
        "Transcribed by model: model-a, model-b"
    )
    assert full_text == expected
    assert models_used == {"model-a", "model-b"}


def test_assemble_full_text_includes_page_models(settings, mock_doc):
    paperless = MagicMock()
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    settings.OCR_INCLUDE_PAGE_MODELS = True
    images = [create_test_image(), create_test_image()]
    page_results = [
        ("Page 1 text", "model-a"),
        ("Page 2 text", ""),
    ]

    full_text, models_used = processor._assemble_full_text(len(images), page_results)

    expected = (
        "--- Page 1 (model-a) ---\n"
        "Page 1 text\n\n"
        "--- Page 2 ---\n"
        "Page 2 text\n\n"
        "Transcribed by model: model-a"
    )
    assert full_text == expected
    assert models_used == {"model-a"}


def test_update_paperless_document_tags(settings, mock_doc):
    paperless = MagicMock()
    paperless.get_document.return_value = {"id": 1, "tags": [settings.PRE_TAG_ID, 42, 42]}
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    processor._update_paperless_document("text", {"model-a"})

    args, _ = paperless.update_document.call_args
    assert args[0] == 1
    assert args[1] == "text"
    assert set(args[2]) == {settings.POST_TAG_ID, 42}


def test_update_paperless_document_marks_error_on_refusal(settings, mock_doc):
    paperless = MagicMock()
    paperless.get_document.return_value = {"id": 1, "tags": [settings.PRE_TAG_ID, 42]}
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    processor._update_paperless_document(settings.REFUSAL_MARK, set())

    args, _ = paperless.update_document.call_args
    assert args[0] == 1
    assert args[1] == settings.REFUSAL_MARK
    assert set(args[2]) == {settings.ERROR_TAG_ID, 42}


def test_update_paperless_document_marks_error_on_empty_text(settings, mock_doc):
    paperless = MagicMock()
    paperless.get_document.return_value = {"id": 1, "tags": [settings.PRE_TAG_ID, 42]}
    ocr_provider = MagicMock()
    processor = DocumentProcessor(mock_doc, paperless, ocr_provider, settings)

    processor._update_paperless_document("", set())

    args, _ = paperless.update_document.call_args
    assert args[0] == 1
    assert args[1] == ""
    assert set(args[2]) == {settings.ERROR_TAG_ID, 42}
