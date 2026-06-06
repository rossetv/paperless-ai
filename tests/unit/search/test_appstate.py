"""Tests for search.appstate — the per-app account context.

Covers: AppState bundles the app.db path and the SetupState; get_app_state
reads the AppState stashed on a request's app.state and raises a clear error
when it is absent.
"""

from __future__ import annotations

import pytest

from search.appstate import AppState, get_app_state
from search.errors import AppStateNotAttachedError
from search.setup import SetupState


def test_app_state_carries_its_fields() -> None:
    setup_state = SetupState()
    state = AppState(
        app_db_path="/data/app.db",
        setup_state=setup_state,
    )
    assert state.app_db_path == "/data/app.db"
    assert state.setup_state is setup_state


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

    app = _FakeApp()
    state = AppState(app_db_path="/data/app.db", setup_state=SetupState())
    app.state.app_state = state
    request = _FakeRequest(app)
    assert get_app_state(request) is state  # type: ignore[arg-type]


def test_get_app_state_raises_when_state_is_missing() -> None:
    """A request with no AppState stashed yields a typed AppStateNotAttachedError."""

    class _FakeState:
        pass

    class _FakeApp:
        def __init__(self) -> None:
            self.state = _FakeState()

    class _FakeRequest:
        def __init__(self, app: _FakeApp) -> None:
            self.app = app

    request = _FakeRequest(_FakeApp())
    with pytest.raises(AppStateNotAttachedError, match="AppState"):
        get_app_state(request)  # type: ignore[arg-type]
