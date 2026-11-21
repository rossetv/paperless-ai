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

log = structlog.get_logger(__name__)


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
            StaticFiles(directory=str(assets_dir)),
            name="spa-assets",
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_catch_all(full_path: str) -> Response:
        """Serve a real file when one exists, else the SPA ``index.html``."""
        # Registered routes win, but never answer an API path with the shell.
        if full_path.startswith("api/") or full_path.startswith("mcp"):
            return Response(status_code=404)

        # The parents check stops a path from escaping dist_dir.
        candidate = (dist_dir / full_path).resolve()
        dist_root = dist_dir.resolve()
        if full_path and dist_root in candidate.parents and candidate.is_file():
            return FileResponse(candidate)

        if index_file.is_file():
            return FileResponse(index_file)
        return Response(status_code=404)

    log.info("search.spa_mounted", path=str(dist_dir))
