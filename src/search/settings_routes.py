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
common (config, paperless), search (deps, index_sentinel, wire,
settings_service).
"""

from __future__ import annotations

import os
import sqlite3

import httpx
import openai
import structlog
from fastapi import APIRouter, Depends, HTTPException

from appdb import config as config_store
from appdb.connection import transaction
from common.config import REINDEX_KEYS, SECRET_KEYS, Settings, build_settings
from common.paperless import PaperlessClient
from search.deps import get_app_db, require_admin
from search.index_sentinel import request_index_rebuild
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


def build_settings_router(settings: Settings) -> APIRouter:
    """Build the admin Settings ``/api`` router (web-redesign §5).

    The handlers reach the ``app.db`` connection through the per-request
    :func:`~search.deps.get_app_db` dependency. Only the static *settings* is
    closed over — its ``INDEX_DB_PATH`` is where a re-index-forcing save drops
    the rebuild sentinel (the path never changes at runtime).

    Args:
        settings: Application settings; ``INDEX_DB_PATH`` locates the index
            data directory the rebuild sentinels are written into.

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
        settings list, so the UI refreshes from one response. When the change
        touches a re-index key the response's ``reindex_triggered`` is true.
        """
        return _put_settings(body, app_db, settings)

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
    reindex_triggered: bool = False,
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
    return SettingsResponse(settings=items, reindex_triggered=reindex_triggered)


def _put_settings(
    body: UpdateSettingsRequest, app_db: sqlite3.Connection, settings: Settings
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

    When the change touches a re-index key (the embedding model or chunking),
    the save forces a full index rebuild — the indexer wipes every chunk and
    re-embeds the archive with the new config — because old and new vectors
    cannot coexist. ``reindex_triggered`` in the response reports whether that
    rebuild was scheduled.

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

    # A change to a re-index key (the embedding model or the chunking) makes the
    # existing vectors stale, so force a full rebuild: the indexer wipes every
    # chunk and re-embeds the archive with the new config. Without it the old
    # and new vectors coexist and search silently degrades. We only drop the
    # sentinel; the indexer (sole writer) does the wipe. Best-effort: a save
    # that already persisted must not 500 because the data dir is unwritable —
    # log it and report reindex_triggered=False so the UI can prompt a manual
    # rebuild from the Index page.
    reindex_triggered = False
    if reindex_required(changed):
        try:
            request_index_rebuild(settings.INDEX_DB_PATH)
            reindex_triggered = True
        except OSError as exc:
            log.error(
                "search.settings_reindex_trigger_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )

    log.info(
        "search.settings_updated",
        changed_count=len(changed),
        requires_reindex=reindex_required(changed),
        reindex_triggered=reindex_triggered,
    )
    # Re-read so the response reflects exactly what was persisted.
    return _read_settings(app_db, reveal=False, reindex_triggered=reindex_triggered)


def _probe_openai(probe_settings: Settings) -> None:
    """Verify that the OpenAI API key in *probe_settings* is accepted.

    Builds a throwaway :class:`openai.OpenAI` client (mirroring the
    construction in :mod:`common.library_setup`) and calls ``models.list()``
    — the cheapest authenticated endpoint. Raises an :exc:`openai.APIError`
    subclass on any authentication or connectivity failure.

    Args:
        probe_settings: A fully-built :class:`Settings` instance whose
            ``OPENAI_API_KEY`` is the key under test.
    """
    client = openai.OpenAI(
        api_key=probe_settings.OPENAI_API_KEY,
        http_client=httpx.Client(trust_env=False),
    )
    try:
        client.models.list()
    finally:
        client.close()


def _probe_ollama(probe_settings: Settings) -> None:
    """Verify that the Ollama daemon at *probe_settings.OLLAMA_BASE_URL* is reachable.

    Issues a GET to the OpenAI-compatible ``/models`` endpoint
    (``{base_url.rstrip('/')}/models``).  A real Ollama server returns 404 for
    the bare ``/v1/`` base URL, so probing that directly would always fail; the
    ``/models`` list endpoint is the right liveness check.  Any 2xx response is
    "up".  Raises :exc:`httpx.HTTPError` or :exc:`OSError` on failure (matching
    the transport-layer exceptions already handled for the Paperless probe).

    Args:
        probe_settings: A fully-built :class:`Settings` instance whose
            ``OLLAMA_BASE_URL`` is the endpoint under test.
    """
    base_url = (probe_settings.OLLAMA_BASE_URL or "").rstrip("/")
    models_url = f"{base_url}/models"
    with httpx.Client(trust_env=False) as client:
        client.get(models_url, timeout=10).raise_for_status()


def _test_connection(
    body: TestConnectionRequest, app_db: sqlite3.Connection
) -> TestConnectionResponse:
    """Probe one of three services with the stored or supplied credentials.

    Builds a throwaway :class:`Settings` from the current configuration with
    any non-empty request overrides applied, then delegates to the appropriate
    probe helper based on ``body.service``.  A 200 is always returned — any
    failure is a clean ``ok=False`` outcome; this endpoint never 500s.

    Service dispatch:
    - ``"paperless"`` (default) — unchanged path, populates ``document_count``.
    - ``"openai"`` — calls :func:`_probe_openai`; ``document_count`` is 0.
    - ``"ollama"`` — calls :func:`_probe_ollama`; ``document_count`` is 0.
    """
    config_table = config_store.get_all(app_db)
    merged: dict[str, str] = dict(os.environ)
    merged.update(config_table)
    # An empty override means "keep the stored value" — the masked-token path.
    if body.paperless_url:
        merged["PAPERLESS_URL"] = body.paperless_url
    if body.paperless_token:
        merged["PAPERLESS_TOKEN"] = body.paperless_token
    if body.openai_api_key:
        merged["OPENAI_API_KEY"] = body.openai_api_key
    if body.ollama_base_url:
        merged["OLLAMA_BASE_URL"] = body.ollama_base_url
    # build_settings requires every SECRET_KEY to be non-empty. Inject
    # sentinels for any missing required keys so validation passes regardless
    # of which service is being probed.
    _SENTINEL = "__test_connection_placeholder__"
    for req in SECRET_KEYS:
        merged.setdefault(req, _SENTINEL)

    # Short-circuit BEFORE building Settings: if the credential we would actually
    # use is absent or only a sentinel, there is no point attempting the probe.
    # We check the merged dict here (not the built Settings) because build_settings
    # may normalise or discard values based on LLM_PROVIDER — e.g. OLLAMA_BASE_URL
    # is set to None by Settings when LLM_PROVIDER=openai regardless of the
    # value in merged.
    if body.service == "openai":
        effective_key = merged.get("OPENAI_API_KEY", "")
        if not effective_key or effective_key == _SENTINEL:
            return TestConnectionResponse(
                ok=False, document_count=0, detail="Not configured"
            )

    if body.service == "ollama":
        effective_url = merged.get("OLLAMA_BASE_URL", "")
        if not effective_url or effective_url == _SENTINEL:
            return TestConnectionResponse(
                ok=False, document_count=0, detail="Not configured"
            )

    try:
        probe_settings = build_settings(merged)
    except ValueError as exc:
        # The override or stored config is itself invalid (e.g. no token).
        return TestConnectionResponse(ok=False, document_count=0, detail=str(exc))

    if body.service == "openai":
        try:
            _probe_openai(probe_settings)
        except Exception as exc:
            return TestConnectionResponse(ok=False, document_count=0, detail=str(exc))
        return TestConnectionResponse(
            ok=True, document_count=0, detail="Connected to OpenAI successfully."
        )

    if body.service == "ollama":
        try:
            _probe_ollama(probe_settings)
        except Exception as exc:
            return TestConnectionResponse(ok=False, document_count=0, detail=str(exc))
        return TestConnectionResponse(
            ok=True, document_count=0, detail="Connected to Ollama successfully."
        )

    # Default: paperless
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
