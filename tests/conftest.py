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
    config.addinivalue_line("markers", "integration: Integration tests (module boundaries)")
    config.addinivalue_line("markers", "e2e: End-to-end tests (full workflows)")

def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        path = str(item.fspath)
        if "/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/e2e/" in path:
            item.add_marker(pytest.mark.e2e)

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
