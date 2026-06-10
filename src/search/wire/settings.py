"""Pydantic wire models for the Settings API (web-redesign §5, Wave 4).

The request/response shapes for ``GET``/``PUT /api/settings`` and
``POST /api/settings/test-connection``, with the payload-size bounds that keep a
buggy or hostile save from pinning the SQLite write lock. A boundary module of
the :mod:`search.wire` package (``CODE_GUIDELINES.md`` §5.6).

Allowed deps: pydantic, stdlib.
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Bounds on the ``PUT /api/settings`` body. These are deliberately generous
# for legitimate use — an admin save changes a handful of keys, never a 100k
# blob — and narrow enough that an over-large or buggy payload cannot fill
# the SQLite write or pin out other writers for the busy-timeout window.
MAX_SETTINGS_KEYS = 100
MAX_SETTINGS_VALUE_LENGTH = 8 * 1024

# Bound on the ``POST /api/settings/test-connection`` URL. 2K is long enough
# for any legitimate Paperless URL (the standard caps URIs at 2048) and short
# enough that a paste-bombed value is rejected at the boundary.
MAX_PAPERLESS_URL_LENGTH = 2048


class SettingItemResponse(BaseModel):
    """One configuration key as returned by ``GET``/``PUT /api/settings``.

    A secret key's *value* is masked by the route handler before this model
    is built — this model never does the masking itself.

    Attributes:
        key: The canonical config key (an env-var name).
        value: The effective string value, or ``None`` when the key is on its
            coded default. For a secret key this is the masked placeholder.
            Always a string on the wire — the frontend parses it per the
            field's type (number / bool / CSV list).
        source: ``database`` / ``environment`` / ``default``.
        is_secret: Whether the key holds a secret (the UI offers a reveal).
        requires_reindex: Whether changing this key requires re-indexing every
            document — true for the chunking / embedding-model keys
            (:data:`common.config.REINDEX_KEYS`). The UI shows a re-index
            warning for exactly these keys. There is no restart concept:
            Wave 4 hot-loads every config change.
        default_value: The coded default as a string, or ``None`` for secrets
            and optional keys that have no meaningful coded default. The
            frontend uses this to display the default when ``source`` is
            ``"default"`` and ``value`` is ``None``.
    """

    key: str
    value: str | None
    source: str
    is_secret: bool
    requires_reindex: bool
    default_value: str | None = None


class SettingsResponse(BaseModel):
    """Body of ``GET /api/settings`` and ``PUT /api/settings``.

    The full list of config keys and their state. ``PUT`` returns this same
    shape — the re-read configuration — so the Settings screen refreshes
    itself from the one response with no second fetch.

    ``reindex_triggered`` is set by ``PUT`` when the save changed a
    :data:`common.config.REINDEX_KEYS` key and therefore forced a full index
    rebuild (re-embedding every document). It is always ``false`` on ``GET``.
    """

    settings: list[SettingItemResponse]
    reindex_triggered: bool = False


class UpdateSettingsRequest(BaseModel):
    """Body of ``PUT /api/settings`` — the configuration changes to apply.

    Every value is a string: the ``config`` table stores raw strings and
    ``common.config`` parses them. ``changes`` may be empty (a no-op save).

    The mapping itself is bounded by :data:`MAX_SETTINGS_KEYS`; each value is
    bounded by :data:`MAX_SETTINGS_VALUE_LENGTH`. An over-large payload is
    rejected at the boundary rather than reaching the SQLite write — a
    defence against an accidentally-pasted 10MB blob or a compromised admin
    session DoS-ing the write lock for the busy-timeout window.
    """

    changes: dict[str, str] = Field(max_length=MAX_SETTINGS_KEYS)

    @field_validator("changes")
    @classmethod
    def _bound_value_lengths(cls, value: dict[str, str]) -> dict[str, str]:
        """Reject any single value longer than :data:`MAX_SETTINGS_VALUE_LENGTH`.

        Pydantic ``Field(max_length=...)`` on ``dict[str, str]`` bounds the
        *number of keys*, not the length of each value — that has to be done
        in a validator. We reject as a 422 rather than truncate; silently
        truncating a configuration value would be far worse than refusing it.
        """
        for key, val in value.items():
            if len(val) > MAX_SETTINGS_VALUE_LENGTH:
                raise ValueError(
                    f"value for {key!r} exceeds the {MAX_SETTINGS_VALUE_LENGTH}-"
                    "character limit"
                )
        return value


class TestConnectionRequest(BaseModel):
    """Body of ``POST /api/settings/test-connection``.

    The Settings screen sends the *live form values* so an admin can verify a
    connection before saving it.

    Attributes:
        service: Which service to probe.  ``"paperless"`` is the default and
            the only service that was supported before this field was added —
            omitting it preserves existing behaviour.
        paperless_url: The Paperless base URL to probe. An empty string means
            "use the stored URL". Must be ``http://`` or ``https://`` when
            non-empty; user-info in the URL (``http://user:pw@host``) is
            rejected so a probe cannot be tricked into smuggling credentials
            through the URL.
        paperless_token: The Paperless API token to probe with. An empty
            string means "use the stored token" — the Settings screen sends
            an empty token when the user has not replaced the masked one.
        openai_api_key: The OpenAI API key to probe with when
            ``service="openai"``. An empty string means "use the stored key".
        ollama_base_url: The Ollama base URL to probe when
            ``service="ollama"``. An empty string means "use the stored URL".
    """

    service: Literal["paperless", "openai", "ollama"] = "paperless"
    paperless_url: str = Field(default="", max_length=MAX_PAPERLESS_URL_LENGTH)
    paperless_token: str = Field(default="", max_length=MAX_SETTINGS_VALUE_LENGTH)
    openai_api_key: str = Field(default="", max_length=MAX_SETTINGS_VALUE_LENGTH)
    ollama_base_url: str = Field(default="", max_length=MAX_PAPERLESS_URL_LENGTH)

    @field_validator("paperless_url")
    @classmethod
    def _check_paperless_url(cls, value: str) -> str:
        """Require ``http(s)://`` and reject userinfo on a non-empty URL.

        An empty string is the documented "use the stored URL" sentinel and
        passes through untouched. Non-empty values must be an absolute
        ``http``/``https`` URL — file://, ftp://, gopher:// and similar
        schemes are not Paperless, and a userinfo segment would otherwise let
        a compromised admin smuggle a stored credential into a probe target.
        """
        if not value:
            return value
        # rationale: a deliberately narrow scheme check rather than a full
        # URL parser; the test-connection probe is admin-only and we only
        # care that the value targets HTTP(S) and carries no userinfo.
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("paperless_url must start with http:// or https://")
        # urllib.parse imported here so the module keeps a flat top-of-module —
        # the validator is only hit on a non-empty URL.
        from urllib.parse import urlparse  # noqa: PLC0415

        parsed = urlparse(value)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("paperless_url must not contain credentials")
        if not parsed.hostname:
            raise ValueError("paperless_url must include a host")
        return value

    @field_validator("ollama_base_url")
    @classmethod
    def _check_ollama_base_url(cls, value: str) -> str:
        """Require ``http(s)://`` and reject userinfo on a non-empty Ollama URL.

        Mirrors the same checks applied to ``paperless_url``: an empty string
        is the "use the stored value" sentinel and passes through untouched.
        """
        if not value:
            return value
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("ollama_base_url must start with http:// or https://")
        from urllib.parse import urlparse  # noqa: PLC0415

        parsed = urlparse(value)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("ollama_base_url must not contain credentials")
        if not parsed.hostname:
            raise ValueError("ollama_base_url must include a host")
        return value


class TestConnectionResponse(BaseModel):
    """Body of ``POST /api/settings/test-connection`` — the round-trip result.

    Attributes:
        ok: Whether the probed service responded successfully.
        document_count: The document count reported on a successful Paperless
            probe; 0 for OpenAI/Ollama probes and on any failure.
        detail: A human-readable outcome — a success note or the failure
            reason (an HTTP status, a connection error, an auth failure).
    """

    ok: bool
    document_count: int
    detail: str
