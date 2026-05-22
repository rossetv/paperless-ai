"""Tests for search.cookies — session-cookie set and clear.

Covers: set_session_cookie writes the token under the documented name with
HttpOnly, SameSite=Strict, Path=/ and the supplied Max-Age; the Secure flag
is set when secure=True (HTTPS) and absent when secure=False (HTTP);
clear_session_cookie removes it. A starlette Response is used directly — no
HTTP server needed.
"""

from __future__ import annotations

from starlette.responses import Response

from search.cookies import clear_session_cookie, set_session_cookie

_COOKIE_NAME = "search_session"


def _set_cookie_header(response: Response) -> str:
    """Return the single Set-Cookie header value from *response*."""
    headers = [value for key, value in response.raw_headers if key == b"set-cookie"]
    assert len(headers) == 1
    return headers[0].decode("latin-1")


def test_set_session_cookie_writes_the_token() -> None:
    response = Response()
    set_session_cookie(response, token="opaque-token", max_age=3600, secure=True)
    header = _set_cookie_header(response)
    assert f"{_COOKIE_NAME}=opaque-token" in header


def test_set_session_cookie_is_httponly() -> None:
    response = Response()
    set_session_cookie(response, token="t", max_age=3600, secure=True)
    assert "HttpOnly" in _set_cookie_header(response)


def test_set_session_cookie_is_secure_over_https() -> None:
    """Secure flag is present when the request arrived over HTTPS."""
    response = Response()
    set_session_cookie(response, token="t", max_age=3600, secure=True)
    assert "Secure" in _set_cookie_header(response)


def test_set_session_cookie_is_not_secure_over_http() -> None:
    """Secure flag is absent when the request arrived over plain HTTP.

    A Secure cookie is silently dropped by the browser over HTTP — making
    login appear to succeed (200) but leaving no session cookie, so the next
    request is 401. When the scheme is HTTP (e.g. direct LAN/IP access),
    omit the flag so the cookie is actually stored.
    """
    response = Response()
    set_session_cookie(response, token="t", max_age=3600, secure=False)
    assert "Secure" not in _set_cookie_header(response)


def test_set_session_cookie_is_samesite_strict() -> None:
    response = Response()
    set_session_cookie(response, token="t", max_age=3600, secure=True)
    assert "samesite=strict" in _set_cookie_header(response).lower()


def test_set_session_cookie_is_path_root() -> None:
    response = Response()
    set_session_cookie(response, token="t", max_age=3600, secure=True)
    assert "Path=/" in _set_cookie_header(response)


def test_set_session_cookie_carries_the_max_age() -> None:
    response = Response()
    set_session_cookie(response, token="t", max_age=604800, secure=True)
    assert "Max-Age=604800" in _set_cookie_header(response)


def test_clear_session_cookie_expires_the_cookie() -> None:
    response = Response()
    clear_session_cookie(response)
    header = _set_cookie_header(response)
    assert _COOKIE_NAME in header
    # A deletion sets Max-Age=0 (starlette's delete_cookie).
    assert "Max-Age=0" in header
