"""Single-page-app static serving for the search server.

The frontend is a React-Router SPA. A plain ``StaticFiles(html=True)`` mount
serves ``index.html`` only at ``/`` and ``404``s on any other path — so a
deep link such as ``/login`` or ``/setup``, opened or refreshed directly in
the browser, breaks. :func:`register_spa` fixes that:

- real files under ``web/dist`` are served as themselves (the hashed JS/CSS
  bundles, ``favicon.ico``, etc.);
- any other ``GET`` that is **not** an ``/api`` or ``/mcp`` path serves
  ``index.html``, so the client router resolves the route.

It is registered **after** the ``/api`` and ``/mcp`` routes so those always
win; an unknown ``/api`` path therefore still ``404``s rather than being
masked by ``index.html``.

A missing ``web/dist`` directory (unit tests, a pre-build container) makes
:func:`register_spa` a no-op — the server still starts.

Allowed deps: fastapi, starlette, structlog. Forbidden: sqlite3, store.
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

    Mounts the built assets and adds a catch-all ``GET`` route that returns
    ``index.html`` for any non-API path with no matching file, so client-side
    routes resolve on a hard refresh. A no-op when *dist_dir* does not exist.

    Call this **after** every ``/api`` and ``/mcp`` route is registered.

    Args:
        app: The FastAPI application.
        dist_dir: The built-frontend directory (``web/dist``).
    """
    if not dist_dir.is_dir():
        log.info(
            "search.spa_not_mounted",
            path=str(dist_dir),
            reason="dist directory not found",
        )
        return

    index_file = dist_dir / "index.html"
    # The hashed assets live under dist/assets in a Vite build; mounting the
    # whole dist directory at /assets-style sub-paths is simplest done by
    # serving real files via the catch-all below and a StaticFiles for the
    # assets subtree if present.
    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="spa-assets",
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_catch_all(full_path: str) -> Response:
        """Serve a real file when one exists, else the SPA ``index.html``.

        ``/api`` and ``/mcp`` paths never reach here — their routers are
        registered first and take precedence — so an unknown ``/api`` path
        ``404``s instead of being masked by ``index.html``. As a defensive
        measure this handler also refuses to serve ``index.html`` for an
        ``api/``-prefixed path.
        """
        # Defensive: never answer an API path with the SPA shell.
        if full_path.startswith("api/") or full_path.startswith("mcp"):
            return Response(status_code=404)

        # Serve a real, in-tree file if the path resolves to one.
        candidate = (dist_dir / full_path).resolve()
        dist_root = dist_dir.resolve()
        if (
            full_path
            and dist_root in candidate.parents
            and candidate.is_file()
        ):
            return FileResponse(candidate)

        # Otherwise hand the SPA shell to the client router.
        if index_file.is_file():
            return FileResponse(index_file)
        return Response(status_code=404)

    log.info("search.spa_mounted", path=str(dist_dir))
