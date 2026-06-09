"""Tests for the usage_sink parameter on _complete_with_model_fallback (Task 3)."""

from types import SimpleNamespace

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
            model="gpt-5.4-mini", prompt=11, completion=22, reasoning=7, total=33
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
        LlmCallUsage(model="m", prompt=0, completion=0, reasoning=0, total=0)
    ]
