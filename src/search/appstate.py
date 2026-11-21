"""The account context (``app.db`` path and setup state) stored on ``app.state``.

``Request`` is imported at runtime, not under ``TYPE_CHECKING``: FastAPI reads
:func:`get_app_state`'s signature at build time, and a string forward reference
would be mistaken for a query parameter (a spurious 422).
"""

from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request

from search.errors import AppStateNotAttachedError
from search.setup import SetupState

_APP_STATE_ATTR = "app_state"


@dataclass(frozen=True, slots=True)
class AppState:
    """The account-subsystem context shared by every request.

    It holds the ``app.db`` path, not a connection: a ``sqlite3.Connection`` is
    not safe across FastAPI's request threads, so each request opens its own.
    """

    app_db_path: str
    setup_state: SetupState


def attach_app_state(app_state_target: object, state: AppState) -> None:
    """Stash *state* on a FastAPI ``app.state`` object."""
    setattr(app_state_target, _APP_STATE_ATTR, state)


def get_app_state(request: Request) -> AppState:
    """Return the :class:`AppState` stashed on the request's application.

    Raises:
        AppStateNotAttachedError: The app was built without the account wiring.
    """
    state = getattr(request.app.state, _APP_STATE_ATTR, None)
    if not isinstance(state, AppState):
        raise AppStateNotAttachedError(
            "No AppState attached to the application — the search app was "
            "built without the account wiring (search.appstate.attach_app_state)."
        )
    return state
