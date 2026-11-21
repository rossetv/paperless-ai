"""Admin-only Settings router: view, change and test the configuration.

- ``GET  /api/settings``                 — every config key and its state.
- ``PUT  /api/settings``                 — apply configuration changes.
- ``POST /api/settings/test-connection`` — probe Paperless, OpenAI or Ollama.

Saving bumps ``config_version``, so every process hot-loads the change.
Secret values are masked unless the caller passes ``?reveal=true``; the mask
only guards against shoulder-surfing (``app.db`` is not encrypted), and each
reveal is audit-logged.
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


class _ReindexScheduleError(Exception):
    """Scheduling the index rebuild failed mid-save.

    Raised inside the config-write transaction so it rolls back: a re-index
    key must never persist without its rebuild scheduled. Becomes a 503.
    """


def build_settings_router(settings: Settings) -> APIRouter:
    """Build the admin Settings router.

    Only *settings* is closed over: its ``INDEX_DB_PATH`` is where a
    re-index-forcing save drops the rebuild sentinel, and it never changes at
    runtime.
    """
    router = APIRouter()

    @router.get("/api/settings")
    def get_settings(
        reveal: bool = False,
        app_db: sqlite3.Connection = Depends(get_app_db),
        admin: CurrentUser = Depends(require_admin),
    ) -> SettingsResponse:
        """Return every config key with its effective value, source and flags.

        Secret values are masked unless *reveal* is true.
        """
        return _read_settings(app_db, reveal=reveal, admin=admin)

    @router.put("/api/settings", dependencies=[Depends(require_admin)])
    def put_settings(
        body: UpdateSettingsRequest,
        app_db: sqlite3.Connection = Depends(get_app_db),
    ) -> SettingsResponse:
        """Validate and apply configuration changes.

        400 (table untouched) when a key is unknown, a value is invalid, or a
        secret carries the masked placeholder. Returns the full re-read list.
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
        """Probe the service named in the request with the given credentials."""
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

    Shared by GET and the PUT response. A reveal with *admin* supplied emits a
    ``search.settings_revealed`` audit event naming the unmasked keys.
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
                # A secret's coded default is absent or a placeholder.
                default_value=view.default_value if not view.is_secret else None,
            )
        )
    if reveal and admin is not None and revealed_keys:
        # Log only the keys, never the secret values.
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

    A change to a re-index key (embedding model or chunking) schedules a full
    index rebuild, because old and new vectors cannot coexist.

    The mask (``********``) is never accepted as a secret value: the frontend
    omits an unchanged secret, but a buggy or hostile client could post it.
    """
    masked_secrets = [
        key
        for key, val in body.changes.items()
        if key in SECRET_KEYS and val == _SECRET_MASK
    ]
    if masked_secrets:
        raise HTTPException(
            status_code=400,
            detail=(
                "the masked placeholder is not a valid secret value: "
                + ", ".join(sorted(masked_secrets))
            ),
        )

    # Read, validate and write inside one BEGIN IMMEDIATE so validation sees
    # the snapshot the write commits against. Otherwise two concurrent saves
    # could combine into an invalid state (e.g. CHUNK_OVERLAP > CHUNK_SIZE
    # after one changes the size and the other the overlap).
    reindex_triggered = False
    try:
        with transaction(app_db):
            config_table = config_store.get_all(app_db)
            try:
                changed = validate_change_set(
                    changes=body.changes,
                    config_table=config_table,
                    environ=os.environ,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            # A re-index key change makes every vector stale (one
            # mismatched-width row breaks every vector search). Drop the
            # rebuild sentinel before committing, so the new value can never
            # persist without its wipe scheduled; the indexer does the wipe.
            if changed and reindex_required(
                changes=body.changes, config_table=config_table, environ=os.environ
            ):
                try:
                    request_index_rebuild(settings.INDEX_DB_PATH)
                except OSError as exc:
                    log.error(
                        "search.settings_reindex_trigger_failed",
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                    # Raising here rolls the config change back.
                    raise _ReindexScheduleError from exc
                reindex_triggered = True

            if changed:
                # SQLite forbids a nested BEGIN, hence the in-transaction
                # variant; it also bumps config_version.
                config_store.set_many_in_transaction(
                    app_db, {k: body.changes[k] for k in changed}
                )
    except _ReindexScheduleError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Could not schedule the index rebuild required by this change; "
                "the configuration was not saved. Check the index data "
                "directory is writable and retry."
            ),
        ) from exc

    log.info(
        "search.settings_updated",
        changed_count=len(changed),
        requires_reindex=reindex_triggered,
        reindex_triggered=reindex_triggered,
    )
    return _read_settings(app_db, reveal=False, reindex_triggered=reindex_triggered)


def _probe_openai(probe_settings: Settings) -> None:
    """Check the OpenAI key by calling ``models.list()``, the cheapest call.

    Raises an :exc:`openai.APIError` subclass on failure. Both the SDK and its
    ``httpx`` client are bounded by ``REQUEST_TIMEOUT``: the SDK's default
    600s read timeout would let a hung endpoint pin a threadpool worker.
    """
    client = openai.OpenAI(
        api_key=probe_settings.OPENAI_API_KEY,
        http_client=httpx.Client(
            trust_env=False, timeout=probe_settings.REQUEST_TIMEOUT
        ),
        timeout=probe_settings.REQUEST_TIMEOUT,
    )
    try:
        client.models.list()
    finally:
        client.close()


def _probe_ollama(probe_settings: Settings) -> None:
    """Check that the Ollama server answers ``GET {base_url}/models``.

    Ollama returns 404 for the bare ``/v1/`` base URL, so ``/models`` is the
    liveness check. Raises :exc:`httpx.HTTPError` or :exc:`OSError` on failure.
    """
    base_url = (probe_settings.OLLAMA_BASE_URL or "").rstrip("/")
    models_url = f"{base_url}/models"
    with httpx.Client(trust_env=False) as client:
        client.get(models_url, timeout=10).raise_for_status()


def _test_connection(
    body: TestConnectionRequest, app_db: sqlite3.Connection
) -> TestConnectionResponse:
    """Probe ``body.service`` with the stored config plus any request overrides.

    Always returns 200; a failure is ``ok=False``. Only the Paperless probe
    fills ``document_count``.
    """
    config_table = config_store.get_all(app_db)
    merged: dict[str, str] = dict(os.environ)
    merged.update(config_table)
    # An empty override means "keep the stored value".
    if body.paperless_url:
        merged["PAPERLESS_URL"] = body.paperless_url
    if body.paperless_token:
        merged["PAPERLESS_TOKEN"] = body.paperless_token
    if body.openai_api_key:
        merged["OPENAI_API_KEY"] = body.openai_api_key
    if body.ollama_base_url:
        merged["OLLAMA_BASE_URL"] = body.ollama_base_url
    # build_settings requires every SECRET_KEY; fill the missing ones so
    # validation passes whichever service is probed.
    _SENTINEL = "__test_connection_placeholder__"
    for req in SECRET_KEYS:
        merged.setdefault(req, _SENTINEL)

    # Check the merged dict, not the built Settings: build_settings discards
    # values by LLM_PROVIDER (OLLAMA_BASE_URL is None when it is openai).
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
