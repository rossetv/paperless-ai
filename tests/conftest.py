"""Root pytest configuration and process-singleton resets."""

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
    """Drop the process-wide login throttle so failed logins don't leak across tests."""
    from search.login_throttle import reset_login_throttle

    reset_login_throttle()
    yield


@pytest.fixture(autouse=True)
def _reset_search_result_cache():
    """Drop the process-wide search-result cache before each test.

    A warm entry left by one test would serve a later test's identical query from
    cache, skipping the pipeline and breaking its LLM-call-count assertions.
    """
    from search.cache import reset_search_result_cache

    reset_search_result_cache()
    yield


@pytest.fixture(autouse=True)
def _reset_current_price_book():
    """Restore the bundled-seed live price book before each test.

    The price book is a process singleton; a test that loads or refreshes it via
    ``create_app`` would otherwise leak a non-seed book into later tests that
    assert seed prices or ``prices_source == "bundled"``.
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
