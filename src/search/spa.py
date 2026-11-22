"""Serve the built single-page app, with a catch-all for client-side routes.

``StaticFiles(html=True)`` serves ``index.html`` only at ``/``, so a deep link
such as ``/login`` would 404 on a refresh. Real files under ``web/dist`` are
served as themselves; any other non-``/api``, non-``/mcp`` ``GET`` gets
``index.html`` so the client router resolves it.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import FastAPI
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

log = structlog.get_logger(__name__)

# The shell must be revalidated so an upgrade never leaves a browser holding an
# index.html that names bundles which no longer exist.
_INDEX_HEADERS = {"Cache-Control": "no-cache"}
_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"


class _ImmutableStaticFiles(StaticFiles):
    """Static files whose names carry a content hash, so they never change."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = _ASSET_CACHE_CONTROL
        return response


def register_spa(app: FastAPI, dist_dir: Path) -> None:
    """Register SPA static serving and the deep-link catch-all on *app*.

    Call this after every ``/api`` and ``/mcp`` route is registered, so those
    win and an unknown ``/api`` path still 404s. A no-op when *dist_dir* does
    not exist (unit tests, a container without a frontend build).
    """
    if not dist_dir.is_dir():
        log.info(
            "search.spa_not_mounted",
            path=str(dist_dir),
            reason="dist directory not found",
        )
        return

    index_file = dist_dir / "index.html"
    # Vite puts the hashed bundles under dist/assets; other real files are
    # served by the catch-all below.
    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            _ImmutableStaticFiles(directory=str(assets_dir)),
            name="spa-assets",
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_catch_all(full_path: str) -> Response:
        """Serve a real file when one exists, else the SPA ``index.html``."""
        # Registered routes win, but never answer an API path with the shell.
        if full_path.startswith("api/") or full_path.startswith("mcp"):
            return Response(status_code=404)

        # The parents check stops a path from escaping dist_dir.
        try:
            candidate = (dist_dir / full_path).resolve()
            is_real_file = (
                bool(full_path)
                and dist_dir.resolve() in candidate.parents
                and candidate.is_file()
            )
        except (ValueError, OSError):
            # An embedded NUL or an over-long name is not a file, so serve the shell.
            is_real_file = False
        if is_real_file:
            is_index = candidate == index_file.resolve()
            return FileResponse(candidate, headers=_INDEX_HEADERS if is_index else None)

        if index_file.is_file():
            return FileResponse(index_file, headers=_INDEX_HEADERS)
        return Response(status_code=404)

    log.info("search.spa_mounted", path=str(dist_dir))
