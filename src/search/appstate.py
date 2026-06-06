"""The per-app account context for the search server.

The account endpoints and auth dependencies need two things at request time:
where ``app.db`` lives and the in-memory first-run
:class:`~search.setup.SetupState`. Bundling them into one :class:`AppState` —
created once by the app factory and stashed on ``app.state`` — keeps every
route signature free of plumbing arguments.

:class:`AppState` holds the ``app.db`` **path**, not a live connection. The
connection is opened *per request* by the :func:`~search.deps.get_app_db`
dependency and closed when the request ends: a ``sqlite3.Connection`` is not
safe to share across the request threads FastAPI serves on, so one connection
must never outlive a single request.

:func:`get_app_state` is the FastAPI dependency that reads the bundle back off
the incoming request.

``Request`` is imported at runtime, not under ``TYPE_CHECKING``: FastAPI
introspects :func:`get_app_state`'s signature at app-build time to recognise
the special ``Request`` parameter — a string forward reference would be
mis-read as a query parameter (a spurious 422).

Depends on: starlette Request, search.setup, search.errors. Forbidden:
FastAPI route decorators, sqlite3 SQL.
"""

from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request

from search.errors import AppStateNotAttachedError
from search.setup import SetupState

# The attribute name under which the AppState is stored on app.state.
_APP_STATE_ATTR = "app_state"


@dataclass(frozen=True, slots=True)
class AppState:
    """The account-subsystem context shared by every request.

    Attributes:
        app_db_path: The filesystem path to ``app.db``. The connection is
            opened per request by :func:`~search.deps.get_app_db` and closed
            when the request ends — a ``sqlite3.Connection`` is never shared
            across requests, because it is not safe to drive from the multiple
            threads FastAPI serves concurrent requests on.
        setup_state: The in-memory first-run setup-token holder.
    """

    app_db_path: str
    setup_state: SetupState


def attach_app_state(app_state_target: object, state: AppState) -> None:
    """Stash *state* on a FastAPI ``app.state`` object.

    Args:
        app_state_target: The ``app.state`` object (a Starlette ``State``).
        state: The :class:`AppState` to store.
    """
    setattr(app_state_target, _APP_STATE_ATTR, state)


def get_app_state(request: Request) -> AppState:
    """Return the :class:`AppState` stashed on the request's application.

    The FastAPI dependency every account route and auth dependency uses to
    reach the ``app.db`` path, the setup state, and the legacy key.

    Args:
        request: The incoming request.

    Returns:
        The application's :class:`AppState`.

    Raises:
        AppStateNotAttachedError: No :class:`AppState` was attached — the app
            was built without the account wiring. This is a programming error,
            surfaced loudly rather than as a confusing ``AttributeError`` deep
            in a handler.
    """
    state = getattr(request.app.state, _APP_STATE_ATTR, None)
    if not isinstance(state, AppState):
        raise AppStateNotAttachedError(
            "No AppState attached to the application — the search app was "
            "built without the account wiring (search.appstate.attach_app_state)."
        )
    return state
