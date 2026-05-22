"""Tests for the SPA catch-all route in the search app.

The frontend is a React-Router single-page app; deep links such as /login
and /setup must serve index.html so the client router can take over. A real
asset (a .js file) must still be served as itself, and /api and /mcp paths
must never be swallowed by the catch-all.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from search.spa import register_spa


def _app_with_dist(tmp_path):
    """Build a FastAPI app whose SPA is a tmp_path 'dist' directory."""
    from fastapi import FastAPI

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "app.js").write_text("console.log('app');")
    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict:
        return {"pong": True}

    register_spa(app, dist)
    return app


def test_index_is_served_at_root(tmp_path) -> None:
    client = TestClient(_app_with_dist(tmp_path))
    response = client.get("/")
    assert response.status_code == 200
    assert "id=root" in response.text


def test_deep_link_serves_index_html(tmp_path) -> None:
    """A client-router path with no file serves index.html (200, not 404)."""
    client = TestClient(_app_with_dist(tmp_path))
    for path in ("/login", "/setup", "/users/42"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "id=root" in response.text


def test_a_real_asset_is_served_as_itself(tmp_path) -> None:
    client = TestClient(_app_with_dist(tmp_path))
    response = client.get("/app.js")
    assert response.status_code == 200
    assert "console.log" in response.text


def test_api_paths_are_not_swallowed(tmp_path) -> None:
    """An /api route still resolves to its handler, not to index.html."""
    client = TestClient(_app_with_dist(tmp_path))
    response = client.get("/api/ping")
    assert response.status_code == 200
    assert response.json() == {"pong": True}


def test_unknown_api_path_404s_not_index(tmp_path) -> None:
    """An unknown /api path 404s — it must not fall through to the SPA."""
    client = TestClient(_app_with_dist(tmp_path))
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert "id=root" not in response.text


def test_missing_dist_directory_is_a_no_op(tmp_path) -> None:
    """register_spa on an absent dist directory does not raise or mount."""
    from fastapi import FastAPI

    app = FastAPI()
    register_spa(app, tmp_path / "nonexistent-dist")
    client = TestClient(app)
    # No SPA mounted — root 404s rather than crashing.
    assert client.get("/").status_code == 404
