"""Tests for pytest root configuration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _ensure_src_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    src_dir_str = str(src_dir)
    if src_dir_str not in sys.path:
        sys.path.insert(0, src_dir_str)


_ensure_src_on_path()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "unit: Unit tests (fast, no I/O)")
    config.addinivalue_line(
        "markers", "integration: Integration tests (module boundaries)"
    )
    config.addinivalue_line("markers", "e2e: End-to-end tests (full workflows)")
    config.addinivalue_line(
        "markers",
        "anyio: Async test run on the anyio event loop (search API and MCP tests)",
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        path = str(item.fspath)
        if "/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/e2e/" in path:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """Drop the process-wide login throttle before each test.

    The throttle is a process singleton (one per single-process server); left
    standing, failed-login counts from one test would leak into the next. Reset
    it up front so every test starts from a clean throttle.
    """
    from search.login_throttle import reset_login_throttle

    reset_login_throttle()
    yield


@pytest.fixture(autouse=True)
def _reset_search_result_cache():
    """Drop the process-wide search-result cache before each test.

    The result cache is a process singleton keyed by query + config version. A
    test that runs a cacheable query with a live TTL leaves a warm entry that a
    later test issuing the *same* query (same config version) would be served
    from cache — short-circuiting the pipeline and breaking its LLM-call-count
    assertions (e.g. ``test_search_pipeline`` expecting two calls). The unit
    search tests reset it by hand; doing it here as an autouse fixture makes
    every test — unit, integration, e2e — start from a cold cache, closing the
    cross-suite leak at source rather than per file.
    """
    from search.cache import reset_search_result_cache

    reset_search_result_cache()
    yield


@pytest.fixture(autouse=True)
def _reset_current_price_book():
    """Restore the bundled-seed live price book before each test.

    The live price book is a process singleton (one per server process). A test
    that loads an app.db cache or runs a refresh into it via ``create_app``
    leaves a non-seed book standing; a later test that asserts seed-identical
    dollars or ``prices_source == "bundled"`` would then read the leaked book.
    Reset to the seed up front so every test starts from the behaviour-preserving
    default, closing the cross-suite leak at source.
    """
    from search.pricing_book import reset_current_price_book

    reset_current_price_book()
    yield


@pytest.fixture
def settings():
    """A real Settings instance with minimal valid configuration."""
    from tests.helpers.factories import make_settings

    return make_settings()


@pytest.fixture
def settings_obj():
    """A MagicMock Settings with all attributes pre-populated."""
    from tests.helpers.factories import make_settings_obj

    return make_settings_obj()


@pytest.fixture
def mock_paperless():
    """A MagicMock PaperlessClient with sane defaults."""
    from tests.helpers.mocks import make_mock_paperless

    return make_mock_paperless()


@pytest.fixture
def sample_document():
    """A Paperless document dict with default fields."""
    from tests.helpers.factories import make_document

    return make_document()
