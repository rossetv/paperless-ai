"""API-key and signed-cookie authentication for the search server.

The search server is network-facing and holds the operator's personal
documents, so authentication fails closed (spec §7.3, §9.2;
``CODE_GUIDELINES.md`` §10.1):

- **Programmatic and MCP access** present ``Authorization: Bearer
  <SEARCH_API_KEY>``; :func:`verify_api_key` checks it in constant time.
- **The Web UI** never embeds the key. The browser is served the static SPA
  shell unauthenticated, the user enters the key once on a login screen, and
  the server issues a **stateless** signed session cookie. There is no
  server-side session store: the token carries its own ``issued_at``
  timestamp and TTL, both covered by an HMAC-SHA256 signature keyed by
  ``SEARCH_API_KEY``.

:func:`is_request_authenticated` is the single gate reused by both the
FastAPI dependency and the MCP middleware: a request is authenticated on a
valid bearer token *or* a valid, unexpired session cookie.

Security invariants enforced here:

- Every secret comparison uses :func:`hmac.compare_digest` — constant-time,
  no early-exit on the first differing byte.
- Any malformed or garbage token yields ``False``; a verify function never
  raises to its caller.
- No secret — the API key, a session token, or a signature — is ever logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from common.config import Settings

# A session token is ``issued_at.ttl_seconds.signature``; the signed payload
# is the ``issued_at.ttl_seconds`` prefix, so neither the timestamp nor the
# TTL can be tampered without invalidating the signature.
_TOKEN_FIELD_SEPARATOR = "."
_TOKEN_FIELD_COUNT = 3

# The session-cookie name and its security attributes (spec §7.3).
SESSION_COOKIE_NAME = "search_session"
_COOKIE_SAMESITE = "strict"
_COOKIE_PATH = "/"


class AuthError(Exception):
    """Raised when an authentication operation cannot be completed.

    This is a configuration-shaped failure — for example, issuing a session
    token from an empty signing key. A *failed* credential check is not an
    error: :func:`verify_api_key`, :func:`verify_session_token`, and
    :func:`is_request_authenticated` return ``False`` rather than raising, so
    a malformed or hostile request never produces an unhandled exception.
    """


def verify_api_key(provided: str, configured: str) -> bool:
    """Return whether *provided* equals *configured*, compared in constant time.

    Uses :func:`hmac.compare_digest` so the comparison takes the same time
    regardless of where the two values first differ — an ``==`` comparison
    leaks the length of the matching prefix through a timing side channel.
    """
    return hmac.compare_digest(provided, configured)


def issue_session_token(api_key: str, *, ttl_seconds: int, now: float) -> str:
    """Issue a stateless signed session token valid for *ttl_seconds*.

    The token is ``issued_at.ttl_seconds.signature``, URL-safe base64-encoded
    without padding. ``signature`` is the HMAC-SHA256 of the
    ``issued_at.ttl_seconds`` payload keyed by *api_key*; both the timestamp
    and the TTL are therefore tamper-evident. Expiry is enforced at
    verification time (:func:`verify_session_token`), keeping the server
    stateless — no session store.

    Args:
        api_key: The signing key (``SEARCH_API_KEY``).
        ttl_seconds: Token lifetime; the token expires ``ttl_seconds`` after
            ``issued_at``.
        now: The current Unix time, injected for testability.

    Raises:
        AuthError: If *api_key* is empty — a token signed with no key offers
            no security and must never be issued (fail closed).
    """
    if not api_key:
        raise AuthError("Cannot issue a session token without a signing key.")

    issued_at = int(now)
    payload = f"{issued_at}{_TOKEN_FIELD_SEPARATOR}{ttl_seconds}"
    signature = _sign(payload, api_key)
    raw = f"{payload}{_TOKEN_FIELD_SEPARATOR}{signature}"
    return _encode(raw)


def verify_session_token(token: str, api_key: str, *, now: float) -> bool:
    """Return whether *token* is a valid, unexpired session token.

    Returns ``True`` only when the signature verifies (constant-time, keyed
    by *api_key*) **and** the token is within its lifetime relative to *now*
    — that is, ``issued_at <= now <= issued_at + ttl_seconds``. Any malformed
    token — bad base64, wrong field count, non-numeric timestamp or TTL — and
    any token signed with a different key returns ``False``. This function
    never raises.

    Args:
        token: The URL-safe base64 token from the session cookie.
        api_key: The signing key the token must verify against.
        now: The current Unix time, injected for testability.
    """
    fields = _decode_token_fields(token)
    if fields is None:
        return False
    issued_at, ttl_seconds, signature = fields

    payload = f"{issued_at}{_TOKEN_FIELD_SEPARATOR}{ttl_seconds}"
    expected_signature = _sign(payload, api_key)
    if not hmac.compare_digest(signature, expected_signature):
        return False

    # The signature is valid, so issued_at and ttl_seconds are trustworthy:
    # honour the token only within [issued_at, issued_at + ttl_seconds].
    return issued_at <= now <= issued_at + ttl_seconds


def cookie_attributes(settings: Settings) -> dict[str, object]:
    """Return the session-cookie attributes for the login response.

    The cookie is ``HttpOnly`` (unreadable by JavaScript, so an XSS bug
    cannot steal the session), ``Secure`` (sent only over HTTPS),
    ``SameSite=Strict`` (not sent on cross-site requests, blunting CSRF),
    scoped to ``Path=/``, and given a ``Max-Age`` of ``SEARCH_SESSION_TTL``
    so the browser drops it in step with server-side expiry (spec §7.3).

    The keys match the keyword arguments of FastAPI's
    ``Response.set_cookie``, so a caller can splat the dict straight in.
    """
    return {
        "httponly": True,
        "secure": True,
        "samesite": _COOKIE_SAMESITE,
        "path": _COOKIE_PATH,
        "max_age": settings.SEARCH_SESSION_TTL,
    }


def is_request_authenticated(
    bearer: str | None,
    cookie: str | None,
    settings: Settings,
    *,
    now: float | None = None,
) -> bool:
    """Return whether a request carries a valid credential.

    The shared authentication gate for both the FastAPI dependency and the
    MCP middleware. A request is authenticated when **either**:

    - *bearer* is present and is a valid API key (:func:`verify_api_key`
      against ``settings.SEARCH_API_KEY``), **or**
    - *cookie* is present and is a valid, unexpired session token
      (:func:`verify_session_token` against ``settings.SEARCH_API_KEY``).

    Both credentials absent, or both present-but-invalid, returns ``False``
    (fail closed). An invalid bearer never aborts the check — a valid cookie
    is still honoured, and vice versa.

    Args:
        bearer: The ``Authorization: Bearer`` token, or ``None`` if absent.
        cookie: The session-cookie value, or ``None`` if absent.
        settings: Configuration carrying ``SEARCH_API_KEY``.
        now: The current Unix time; defaults to the wall clock. Injected for
            testability so cookie-expiry can be exercised deterministically.
    """
    api_key = settings.SEARCH_API_KEY

    if bearer is not None and verify_api_key(bearer, api_key):
        return True

    if cookie is not None:
        current_time = time.time() if now is None else now
        if verify_session_token(cookie, api_key, now=current_time):
            return True

    return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sign(payload: str, api_key: str) -> str:
    """Return the hex HMAC-SHA256 of *payload* keyed by *api_key*."""
    return hmac.new(
        api_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _encode(raw: str) -> str:
    """URL-safe base64-encode *raw*, stripping ``=`` padding for a clean cookie."""
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii").rstrip("=")


def _decode_token_fields(token: str) -> tuple[int, int, str] | None:
    """Decode *token* into ``(issued_at, ttl_seconds, signature)``.

    Returns ``None`` for any malformed token — non-base64 input, the wrong
    number of fields, or a non-numeric timestamp or TTL — so callers never
    have to handle a decode exception. The signature is *not* verified here;
    that is :func:`verify_session_token`'s job.
    """
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + padding).decode("ascii")
    except ValueError:
        # binascii.Error (bad base64) and UnicodeDecodeError (non-ASCII
        # bytes) are both ValueError subclasses; either means a junk token.
        return None

    fields = raw.split(_TOKEN_FIELD_SEPARATOR)
    if len(fields) != _TOKEN_FIELD_COUNT:
        return None

    issued_at_text, ttl_text, signature = fields
    try:
        issued_at = int(issued_at_text)
        ttl_seconds = int(ttl_text)
    except ValueError:
        return None

    return issued_at, ttl_seconds, signature
