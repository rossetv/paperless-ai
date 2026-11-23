"""Tests for the usage_sink parameter on _complete_with_model_fallback."""

from types import SimpleNamespace

import pytest

from common.llm import LlmCallUsage, OpenAIChatMixin


class _Stub(OpenAIChatMixin):
    _STAT_KEYS = ()

    def __init__(self, completion):
        self.settings = SimpleNamespace(MAX_RETRIES=0, MAX_RETRY_BACKOFF_SECONDS=0)
        self._init_stats()
        self._completion = completion

    def _create_with_compat(self, params, model):
        return self._completion  # ignore fallback, return the scripted completion


def _completion(text, *, prompt, completion, reasoning, total):
    usage = SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning),
    )
    msg = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)


def test_usage_sink_records_served_model_and_reasoning():
    sink: list[LlmCallUsage] = []
    stub = _Stub(_completion("ok", prompt=11, completion=22, reasoning=7, total=33))
    out = stub._complete_with_model_fallback(
        primary_model="gpt-5.4-mini",
        messages=[],
        fallback_models=[],
        log_event_prefix="judge",
        usage_sink=sink,
    )
    assert out == "ok"
    assert sink == [
        LlmCallUsage(
            model="gpt-5.4-mini",
            provider="openai",
            prompt=11,
            completion=22,
            reasoning=7,
            total=33,
        )
    ]


def test_no_sink_means_no_capture_and_unchanged_return():
    stub = _Stub(_completion("ok", prompt=1, completion=2, reasoning=0, total=3))
    out = stub._complete_with_model_fallback(
        primary_model="m",
        messages=[],
        fallback_models=[],
        log_event_prefix="x",
    )
    assert out == "ok"


def test_absent_usage_records_zeros():
    sink: list[LlmCallUsage] = []
    completion = _completion("ok", prompt=0, completion=0, reasoning=0, total=0)
    completion.usage = None
    stub = _Stub(completion)
    stub._complete_with_model_fallback(
        primary_model="m",
        messages=[],
        fallback_models=[],
        log_event_prefix="x",
        usage_sink=sink,
    )
    assert sink == [
        LlmCallUsage(
            model="m", provider="openai", prompt=0, completion=0, reasoning=0, total=0
        )
    ]


class _PerModelStub(_Stub):
    def __init__(self, by_model):
        super().__init__(None)
        self._by_model = by_model

    def _create_with_compat(self, params, model):
        return self._by_model[model]


def _no_choices(total):
    usage = SimpleNamespace(
        prompt_tokens=1,
        completion_tokens=0,
        total_tokens=total,
        completion_tokens_details=None,
    )
    return SimpleNamespace(choices=[], usage=usage)


def test_reply_without_choices_falls_back_to_next_model_and_keeps_usage():
    sink: list[LlmCallUsage] = []
    stub = _PerModelStub(
        {
            "a": _no_choices(5),
            "b": _completion("from b", prompt=2, completion=3, reasoning=0, total=5),
        }
    )
    out = stub._complete_with_model_fallback(
        primary_model="a",
        messages=[],
        fallback_models=["b"],
        log_event_prefix="x",
        usage_sink=sink,
    )
    assert out == "from b"
    assert [u.model for u in sink] == ["a", "b"]


def test_reply_without_choices_and_no_fallback_ends_like_exhausted_chain():
    sink: list[LlmCallUsage] = []
    stub = _PerModelStub({"a": _no_choices(5)})
    out = stub._complete_with_model_fallback(
        primary_model="a",
        messages=[],
        fallback_models=[],
        log_event_prefix="x",
        usage_sink=sink,
    )
    assert out is None
    assert len(sink) == 1


def _unusable_message(content, *, message_missing):
    reply = _completion("", prompt=1, completion=0, reasoning=0, total=5)
    reply.choices[0].message = (
        None if message_missing else SimpleNamespace(content=content)
    )
    return reply


@pytest.mark.parametrize(
    ("content", "message_missing"),
    [(None, True), ([{"type": "text", "text": "parts"}], False)],
    ids=["message-missing", "content-not-a-string"],
)
def test_reply_without_usable_message_falls_back_to_next_model_and_keeps_usage(
    content, message_missing
):
    sink: list[LlmCallUsage] = []
    stub = _PerModelStub(
        {
            "a": _unusable_message(content, message_missing=message_missing),
            "b": _completion("from b", prompt=2, completion=3, reasoning=0, total=5),
        }
    )
    out = stub._complete_with_model_fallback(
        primary_model="a",
        messages=[],
        fallback_models=["b"],
        log_event_prefix="x",
        usage_sink=sink,
    )
    assert out == "from b"
    assert [u.model for u in sink] == ["a", "b"]


def test_reply_without_usable_message_and_no_fallback_returns_none():
    stub = _PerModelStub({"a": _unusable_message(None, message_missing=True)})
    out = stub._complete_with_model_fallback(
        primary_model="a",
        messages=[],
        fallback_models=[],
        log_event_prefix="x",
    )
    assert out is None
