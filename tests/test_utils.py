from types import SimpleNamespace
from unittest.mock import call

import pytest
from PIL import Image

from common.retry import _sleep_backoff, retry
from common.utils import is_blank


class DummyWorker:
    def __init__(self, max_retries: int):
        self.settings = SimpleNamespace(
            MAX_RETRIES=max_retries, MAX_RETRY_BACKOFF_SECONDS=30
        )
        self.calls = 0

    @retry(retryable_exceptions=(ValueError,))
    def flaky(self) -> str:
        self.calls += 1
        if self.calls < 3:
            raise ValueError("boom")
        return "ok"


class AlwaysFailWorker:
    def __init__(self, max_retries: int):
        self.settings = SimpleNamespace(
            MAX_RETRIES=max_retries, MAX_RETRY_BACKOFF_SECONDS=30
        )
        self.calls = 0

    @retry(retryable_exceptions=(ValueError,))
    def fail(self) -> None:
        self.calls += 1
        raise ValueError("nope")


class ZeroRetryWorker:
    def __init__(self):
        self.settings = SimpleNamespace(MAX_RETRIES=0, MAX_RETRY_BACKOFF_SECONDS=30)
        self.calls = 0

    @retry(retryable_exceptions=(ValueError,))
    def never_called(self) -> None:
        self.calls += 1
        raise ValueError("should not run")


def test_retry_succeeds_after_retries(mocker):
    sleep_spy = mocker.patch("common.retry._sleep_backoff")
    worker = DummyWorker(max_retries=3)

    assert worker.flaky() == "ok"
    assert worker.calls == 3
    sleep_spy.assert_has_calls(
        [call(1, worker.settings), call(2, worker.settings)]
    )


def test_retry_raises_after_max_retries(mocker):
    sleep_spy = mocker.patch("common.retry._sleep_backoff")
    worker = AlwaysFailWorker(max_retries=2)

    with pytest.raises(ValueError, match="nope"):
        worker.fail()

    assert worker.calls == 2
    sleep_spy.assert_called_once_with(1, worker.settings)


def test_retry_zero_retries_raises_value_error():
    worker = ZeroRetryWorker()

    with pytest.raises(ValueError, match="MAX_RETRIES must be >= 1"):
        worker.never_called()

    assert worker.calls == 0


def test_sleep_backoff_uses_exponential_delay(mocker):
    settings = SimpleNamespace(MAX_RETRIES=5, MAX_RETRY_BACKOFF_SECONDS=30)
    mocker.patch("common.retry.random.uniform", return_value=1.0)
    sleep_mock = mocker.patch("common.retry.time.sleep")

    _sleep_backoff(2, settings)

    sleep_mock.assert_called_once_with(4.0)


def test_sleep_backoff_caps_delay(mocker):
    settings = SimpleNamespace(MAX_RETRIES=5, MAX_RETRY_BACKOFF_SECONDS=10)
    mocker.patch("common.retry.random.uniform", return_value=1.0)
    sleep_mock = mocker.patch("common.retry.time.sleep")

    _sleep_backoff(6, settings)

    sleep_mock.assert_called_once_with(10.0)


def test_is_blank_detects_white_and_near_white():
    white = Image.new("RGB", (5, 5), "white")
    assert is_blank(white)

    almost_white = white.copy()
    almost_white.putpixel((0, 0), (0, 0, 0))
    assert is_blank(almost_white, threshold=5)
    assert not is_blank(almost_white, threshold=0)

    black = Image.new("RGB", (5, 5), "black")
    assert not is_blank(black)
