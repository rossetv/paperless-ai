"""Tests for search.appstate — the per-app account context.

Covers: AppState bundles the app.db connection, the SetupState, and the
legacy API key; get_app_state reads the AppState stashed on a request's
app.state and raises a clear error when it is absent.
"""

from __future__ import annotations

import sqlite3

import pytest

from search.appstate import AppState, get_app_state
from search.setup import SetupState


def test_app_state_carries_its_three_fields() -> None:
    conn = sqlite3.connect(":memory:")
    setup_state = SetupState()
    state = AppState(app_db=conn, setup_state=setup_state, legacy_api_key="key-1")
    assert state.app_db is conn
    assert state.setup_state is setup_state
    assert state.legacy_api_key == "key-1"
    conn.close()


def test_get_app_state_returns_the_stashed_state() -> None:
    """get_app_state retrieves the AppState placed on request.app.state."""

    class _FakeState:
        pass

    class _FakeApp:
        def __init__(self) -> None:
            self.state = _FakeState()

    class _FakeRequest:
        def __init__(self, app: _FakeApp) -> None:
            self.app = app

    conn = sqlite3.connect(":memory:")
    app = _FakeApp()
    state = AppState(app_db=conn, setup_state=SetupState(), legacy_api_key="")
    app.state.app_state = state
    request = _FakeRequest(app)
    assert get_app_state(request) is state  # type: ignore[arg-type]
    conn.close()


def test_get_app_state_raises_when_state_is_missing() -> None:
    """A request with no AppState stashed yields a clear RuntimeError."""

    class _FakeState:
        pass

    class _FakeApp:
        def __init__(self) -> None:
            self.state = _FakeState()

    class _FakeRequest:
        def __init__(self, app: _FakeApp) -> None:
            self.app = app

    request = _FakeRequest(_FakeApp())
    with pytest.raises(RuntimeError, match="AppState"):
        get_app_state(request)  # type: ignore[arg-type]
