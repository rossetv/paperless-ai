"""The per-app account context for the search server.

Wave 1's account endpoints and auth dependencies all need three things at
request time: the open ``app.db`` connection, the in-memory first-run
:class:`~search.setup.SetupState`, and the configured legacy
``SEARCH_API_KEY``. Bundling them into one :class:`AppState` — created once by
the app factory and stashed on ``app.state`` — keeps every route signature
free of plumbing arguments.

:func:`get_app_state` is the FastAPI dependency that reads the bundle back
off the incoming request.

``Request`` is imported at runtime, not under ``TYPE_CHECKING``: FastAPI
introspects :func:`get_app_state`'s signature at app-build time to recognise
the special ``Request`` parameter — a string forward reference would be
mis-read as a query parameter (a spurious 422).

Depends on: starlette Request, search.setup. Forbidden: FastAPI route
decorators, sqlite3 SQL.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from starlette.requests import Request

from search.setup import SetupState

# The attribute name under which the AppState is stored on app.state.
_APP_STATE_ATTR = "app_state"


@dataclass(frozen=True, slots=True)
class AppState:
    """The account-subsystem context shared by every request.

    Attributes:
        app_db: The open connection to ``app.db``. One connection is shared
            across the server's request threads; ``check_same_thread=False``
            and appdb's per-statement commits make that safe.
        setup_state: The in-memory first-run setup-token holder.
        legacy_api_key: The configured ``SEARCH_API_KEY``; an empty string
            when no legacy key is set.
    """

    app_db: sqlite3.Connection
    setup_state: SetupState
    legacy_api_key: str


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
    reach the ``app.db`` connection, the setup state, and the legacy key.

    Args:
        request: The incoming request.

    Returns:
        The application's :class:`AppState`.

    Raises:
        RuntimeError: No :class:`AppState` was attached — the app was built
            without the account wiring. This is a programming error, surfaced
            loudly rather than as a confusing ``AttributeError`` deep in a
            handler.
    """
    state = getattr(request.app.state, _APP_STATE_ATTR, None)
    if not isinstance(state, AppState):
        raise RuntimeError(
            "No AppState attached to the application — the search app was "
            "built without the account wiring (search.appstate.attach_app_state)."
        )
    return state
