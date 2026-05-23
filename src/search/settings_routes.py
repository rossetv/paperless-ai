"""The admin-only Settings ``/api`` router for the search server (§5, Wave 4).

Three endpoints, all gated by :data:`search.deps.require_admin` (only an admin
may view or change configuration — web-redesign §4.3):

- ``GET  /api/settings``                 — every config key and its state.
- ``PUT  /api/settings``                 — apply configuration changes.
- ``POST /api/settings/test-connection`` — round-trip the Paperless API.

The handlers are thin: read/diff/re-index logic is in
:mod:`search.settings_service`, the ``config``-table I/O is :mod:`appdb.config`,
and the ``app.db`` connection is opened per-request by
:func:`~search.deps.get_app_db`. Saving config bumps ``config_version``, so
every daemon and the search server hot-load the change — no restart.

Secrets: a secret key's value is masked in ``GET /api/settings`` unless the
caller passes ``?reveal=true`` — the reveal mechanism. ``app.db`` is on the
protected ``/data`` volume, so masking is purely an API-surface defence
against shoulder-surfing the Settings screen, not encryption at rest. A
successful ``?reveal=true`` is audit-logged with the admin's username and the
set of secret keys whose values were revealed — the trail makes a leak
attributable.

Allowed deps: fastapi, structlog, os, sqlite3, appdb (config, connection),
common (config, paperless), search (deps, wire, settings_service).
"""

from __future__ import annotations

import os
import sqlite3

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException

from appdb import config as config_store
from appdb.connection import transaction
from common.config import REINDEX_KEYS, SECRET_KEYS, build_settings
from common.paperless import PaperlessClient
from search.deps import get_app_db, require_admin
from search.sessions import CurrentUser
from search.settings_service import (
    reindex_required,
    validate_change_set,
    view_settings,
)
from search.wire import (
    SettingItemResponse,
    SettingsResponse,
    TestConnectionRequest,
    TestConnectionResponse,
    UpdateSettingsRequest,
)

log = structlog.get_logger(__name__)

# The placeholder shown instead of a secret value when it is not revealed.
# A fixed non-empty string so the UI can tell "set but hidden" from "unset".
_SECRET_MASK = "********"


def build_settings_router() -> APIRouter:
    """Build the admin Settings ``/api`` router (web-redesign §5).

    The handlers reach the ``app.db`` connection through the per-request
    :func:`~search.deps.get_app_db` dependency; nothing is closed over, so
    the router is built once and is request-state-free.

    Returns:
        A configured :class:`~fastapi.APIRouter`. Every route is gated by
        :data:`~search.deps.require_admin`.
    """
    router = APIRouter()

    @router.get("/api/settings")
    def get_settings(
        reveal: bool = False,
        app_db: sqlite3.Connection = Depends(get_app_db),
        admin: CurrentUser = Depends(require_admin),
    ) -> SettingsResponse:
        """Return every config key, its effective value, source and flags.

        Secret values are masked unless *reveal* is true (the reveal
        mechanism; the route is already admin-gated). A successful reveal is
        audit-logged with the actor's username and the revealed key set, so
        the trail makes a leak attributable.
        """
        return _read_settings(app_db, reveal=reveal, admin=admin)

    @router.put("/api/settings", dependencies=[Depends(require_admin)])
    def put_settings(
        body: UpdateSettingsRequest,
        app_db: sqlite3.Connection = Depends(get_app_db),
    ) -> SettingsResponse:
        """Validate and apply configuration changes.

        400 when a key is unknown, a value is invalid, or a secret key
        carries the masked placeholder — the ``config`` table is left
        untouched in that case. On success the response is the full re-read
        settings list, so the UI refreshes from one response.
        """
        return _put_settings(body, app_db)

    @router.post(
        "/api/settings/test-connection",
        dependencies=[Depends(require_admin)],
    )
    def test_connection(
        body: TestConnectionRequest,
        app_db: sqlite3.Connection = Depends(get_app_db),
    ) -> TestConnectionResponse:
        """Round-trip the Paperless API (the design's "Test connection")."""
        return _test_connection(body, app_db)

    return router


def _read_settings(
    app_db: sqlite3.Connection,
    *,
    reveal: bool,
    admin: CurrentUser | None = None,
) -> SettingsResponse:
    """Build the settings list from the config table and the environment.

    Shared by GET /api/settings and the PUT response — the same list shape
    so the Settings screen has one model to consume. When *reveal* is true
    and *admin* is supplied (the GET path always supplies it), a
    ``search.settings_revealed`` audit event is emitted with the admin's
    username and the secret keys that were actually unmasked — the PUT
    response never reveals (``reveal=False`` is hard-wired) and so never
    audits.
    """
    config_table = config_store.get_all(app_db)

    items: list[SettingItemResponse] = []
    revealed_keys: list[str] = []
    for view in view_settings(config_table=config_table, environ=os.environ):
        value = view.effective_value
        if view.is_secret and value is not None:
            if reveal:
                revealed_keys.append(view.key)
            else:
                value = _SECRET_MASK
        items.append(
            SettingItemResponse(
                key=view.key,
                value=value,
                source=view.source,
                is_secret=view.is_secret,
                requires_reindex=view.key in REINDEX_KEYS,
                # Secrets never expose a default_value — their coded default
                # is either absent or a placeholder. Only non-secret keys
                # surface their coded default so the UI can display it.
                default_value=view.default_value if not view.is_secret else None,
            )
        )
    if reveal and admin is not None and revealed_keys:
        # rationale: never log the values themselves — only the *keys* whose
        # secrets the admin chose to reveal. The values are still secrets;
        # the audit is "who and what", not "what was it".
        log.warning(
            "search.settings_revealed",
            username=admin.username,
            keys=sorted(revealed_keys),
        )
    return SettingsResponse(settings=items)


def _put_settings(
    body: UpdateSettingsRequest, app_db: sqlite3.Connection
) -> SettingsResponse:
    """Validate and persist a change set; return the re-read settings list.

    The read-validate-write trio runs inside one ``BEGIN IMMEDIATE`` so two
    concurrent admin saves serialise on SQLite's write lock — the validation
    sees the same snapshot the write commits against, and no admin can
    persist a value that violates an invariant against another admin's
    concurrent change. Saving bumps ``config_version`` (inside
    :func:`appdb.config.set_many`, in the same transaction), so every daemon
    and the search server hot-load the change on their next check — no
    restart. The response is the full re-read list.

    The masked sentinel (``********``) is *never* accepted as a secret value:
    the frontend correctly omits an unchanged secret, but a buggy or
    compromised client could POST the mask and persist it. Reject it at the
    boundary as defence-in-depth.
    """
    masked_secrets = [
        key
        for key, val in body.changes.items()
        if key in SECRET_KEYS and val == _SECRET_MASK
    ]
    if masked_secrets:
        # rationale: the only way a secret arrives equal to the mask is a
        # client bug or a deliberate attempt to persist the placeholder as
        # the value. Either way: reject, the table is untouched.
        raise HTTPException(
            status_code=400,
            detail=(
                "the masked placeholder is not a valid secret value: "
                + ", ".join(sorted(masked_secrets))
            ),
        )

    # Read, validate, and write inside one BEGIN IMMEDIATE so the validation
    # runs against the exact snapshot the write commits against (CODE_GUIDELINES
    # §9 — transactions). Without this, two concurrent admins could each
    # validate against their own snapshot and commit a combined state that
    # violates an invariant of either snapshot (e.g. CHUNK_OVERLAP > CHUNK_SIZE
    # after one save changes the size and another changes the overlap).
    with transaction(app_db):
        config_table = config_store.get_all(app_db)
        try:
            changed = validate_change_set(
                changes=body.changes,
                config_table=config_table,
                environ=os.environ,
            )
        except ValueError as exc:
            # A bad key or value — a client error. The transaction rolls
            # back via the context manager's exception path, so the table is
            # untouched. raise HTTPException after escaping the transaction
            # block so structlog sees the failure cleanly.
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if changed:
            # Persist only the keys that genuinely changed. set_many_in_transaction
            # writes inside the outer BEGIN IMMEDIATE (SQLite forbids a nested
            # BEGIN, so the in-transaction variant exists for exactly this
            # case) and bumps config_version in the same transaction, so the
            # change hot-loads on every other process's next check.
            config_store.set_many_in_transaction(
                app_db, {k: body.changes[k] for k in changed}
            )

    log.info(
        "search.settings_updated",
        changed_count=len(changed),
        requires_reindex=reindex_required(changed),
    )
    # Re-read so the response reflects exactly what was persisted.
    return _read_settings(app_db, reveal=False)


def _test_connection(
    body: TestConnectionRequest, app_db: sqlite3.Connection
) -> TestConnectionResponse:
    """Round-trip the Paperless API with the stored or supplied credentials.

    Builds a throwaway :class:`Settings` from the current configuration with
    the request's URL/token applied — an empty string for either falls back
    to the stored value (the Settings screen sends an empty token when the
    user has not replaced the masked one). A 200 is success and reports the
    document count; any HTTP error or transport failure is a clean
    ``ok=False`` outcome — this endpoint never 500s on a bad token.
    """
    config_table = config_store.get_all(app_db)
    merged: dict[str, str] = dict(os.environ)
    merged.update(config_table)
    # An empty override means "keep the stored value" — the masked-token path.
    if body.paperless_url:
        merged["PAPERLESS_URL"] = body.paperless_url
    if body.paperless_token:
        merged["PAPERLESS_TOKEN"] = body.paperless_token
    # build_settings requires every SECRET_KEY to be non-empty. For the
    # test-connection probe we only care about the Paperless credentials; inject
    # sentinels for any other required keys so build_settings can parse the
    # mapping without failing on an unrelated missing key.
    _SENTINEL = "__test_connection_placeholder__"
    for req in SECRET_KEYS:
        merged.setdefault(req, _SENTINEL)

    try:
        probe_settings = build_settings(merged)
    except ValueError as exc:
        # The override or stored config is itself invalid (e.g. no token).
        return TestConnectionResponse(ok=False, document_count=0, detail=str(exc))

    client = PaperlessClient(probe_settings)
    try:
        count = client.count_documents()
    except httpx.HTTPStatusError as exc:
        return TestConnectionResponse(
            ok=False,
            document_count=0,
            detail=f"Paperless returned {exc.response.status_code}.",
        )
    except (httpx.HTTPError, OSError) as exc:
        # rationale: a connection/timeout failure is a normal "test failed"
        # outcome the admin must see, not a server fault — report it cleanly.
        return TestConnectionResponse(
            ok=False,
            document_count=0,
            detail=f"Could not reach Paperless: {exc}",
        )
    finally:
        client.close()

    return TestConnectionResponse(
        ok=True,
        document_count=count,
        detail="Connected to Paperless successfully.",
    )
