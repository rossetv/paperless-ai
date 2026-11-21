"""Shared fixtures and helpers for the search unit tests.

``build_search_core`` is re-exported from :mod:`tests.helpers.search`, which the
integration tests also use.
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


def build_planner(settings: MagicMock, response_content: str | None) -> QueryPlanner:
    """Build a QueryPlanner whose ``_create_completion`` returns *response_content*.

    For multi-call ``side_effect`` scenarios (model fallback), build a bare
    ``QueryPlanner`` and assign ``_create_completion`` directly.
    """
    planner = QueryPlanner(settings)
    planner._create_completion = MagicMock(  # type: ignore[method-assign]
        return_value=make_chat_completion(response_content)
    )
    return planner


def build_synthesizer(settings: MagicMock, response_content: str | None) -> Synthesizer:
    """Build a Synthesizer whose ``_create_completion`` returns *response_content*."""
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

    The core and store reader default to mocks. The base URL is HTTPS so the
    ``Secure`` session cookie is sent on follow-up requests. ``app.db`` is the
    unique-per-call path from ``make_search_settings``, so each app starts in
    first-run setup mode with no users.
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
    # The /api/search handler reads ``SEARCH_MAX_CONCURRENT`` off the live core's
    # settings; a test that wants a different cap overrides ``core.settings``.
    core.settings = settings
    if store_reader is None:
        store_reader = MagicMock()
        store_reader.list_facets.return_value = make_facet_set()
        store_reader.get_stats.return_value = make_index_stats()
        store_reader.quick_check.return_value = True

    app = create_app(settings, core=core, store_reader=store_reader)
    return TestClient(app, raise_server_exceptions=False, base_url="https://testserver")
