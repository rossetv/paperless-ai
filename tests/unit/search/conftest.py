"""Shared fixtures and helpers for the search unit tests.

Several ``search`` test files are split across two modules for the 500-line
ceiling (CODE_GUIDELINES §3.1) — ``test_core`` / ``test_core_sources``,
``test_planner`` / ``test_planner_model_fallback``,
``test_synthesizer`` / ``test_synthesizer_model_fallback``,
``test_api`` / ``test_api_healthz``.  The construct helpers each split-pair
shares live here so every test file imports one definition rather than
redeclaring it:

- :func:`build_search_core` — re-exported from :mod:`tests.helpers.search`,
  since the integration tests need the same wiring.
- :func:`build_planner` — a ``QueryPlanner`` whose ``_create_completion`` is
  patched with a scripted response (or ``side_effect``).
- :func:`build_synthesizer` — the same for a ``Synthesizer``.
- :func:`build_test_client` — a FastAPI ``TestClient`` over the real
  ``create_app`` with mock core and store reader.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from search.planner import QueryPlanner
from search.synthesizer import Synthesizer
from tests.helpers.llm import make_chat_completion
from tests.helpers.search import build_search_core

__all__ = [
    "build_planner",
    "build_search_core",
    "build_synthesizer",
    "build_test_client",
]


def build_planner(
    settings: MagicMock, response_content: str | None
) -> QueryPlanner:
    """Build a QueryPlanner whose ``_create_completion`` returns *response_content*.

    Patches the instance's ``_create_completion`` with a single-return mock —
    the planner takes only ``settings``, so its LLM transport is patched on the
    instance, mirroring ``tests/unit/classifier``.  For multi-call ``side_effect``
    scenarios (model fallback), build a bare ``QueryPlanner`` and assign
    ``_create_completion`` directly.

    Args:
        settings: A Settings-like mock (use ``make_search_settings``).
        response_content: The raw LLM content the single call returns.
    """
    planner = QueryPlanner(settings)
    planner._create_completion = MagicMock(  # type: ignore[method-assign]
        return_value=make_chat_completion(response_content)
    )
    return planner


def build_synthesizer(
    settings: MagicMock, response_content: str | None
) -> Synthesizer:
    """Build a Synthesizer whose ``_create_completion`` returns *response_content*.

    The synthesiser counterpart of :func:`build_planner`.

    Args:
        settings: A Settings-like mock (use ``make_search_settings``).
        response_content: The raw LLM content the single call returns.
    """
    synthesizer = Synthesizer(settings)
    synthesizer._create_completion = MagicMock(  # type: ignore[method-assign]
        return_value=make_chat_completion(response_content)
    )
    return synthesizer


def build_test_client(
    settings: MagicMock,
    *,
    core: MagicMock | None = None,
    store_reader: MagicMock | None = None,
) -> Any:
    """Build a FastAPI TestClient over the real ``create_app``.

    Mocks the core and the store reader by default; a test that needs scripted
    behaviour passes its own.  The base URL is ``https://testserver`` so the
    ``Secure`` session cookie is forwarded on follow-up requests — the real
    server always runs behind HTTPS (spec §7.3).

    Args:
        settings: A Settings-like mock (use ``make_search_settings``).
        core: An optional pre-built SearchCore stub; defaults to a MagicMock
            whose ``answer`` returns ``make_search_result()``.
        store_reader: An optional pre-built StoreReader stub; defaults to a
            MagicMock with a populated facet set, index stats, and a passing
            ``quick_check``.

    Returns:
        A ``fastapi.testclient.TestClient`` wrapping the configured app.
    """
    from fastapi.testclient import TestClient

    from search.api import create_app
    from tests.helpers.factories import (
        make_facet_set,
        make_index_stats,
        make_search_result,
    )

    if core is None:
        core = MagicMock()
        core.answer.return_value = make_search_result()
    if store_reader is None:
        store_reader = MagicMock()
        store_reader.list_facets.return_value = make_facet_set()
        store_reader.get_stats.return_value = make_index_stats()
        store_reader.quick_check.return_value = True

    app = create_app(settings, core=core, store_reader=store_reader)
    return TestClient(
        app, raise_server_exceptions=False, base_url="https://testserver"
    )
