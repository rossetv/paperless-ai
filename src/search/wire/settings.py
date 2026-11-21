"""Wire models for the Settings endpoints, with their payload-size bounds."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Generous for a real save, yet small enough that an oversized payload cannot
# hold the SQLite write lock and block other writers.
MAX_SETTINGS_KEYS = 100
MAX_SETTINGS_VALUE_LENGTH = 8 * 1024

MAX_PAPERLESS_URL_LENGTH = 2048


class SettingItemResponse(BaseModel):
    """One configuration key as returned by ``GET``/``PUT /api/settings``.

    Attributes:
        value: The effective value, or ``None`` on the coded default; already
            masked for a secret by the route. The frontend parses it by type.
        source: ``database``, ``environment`` or ``default``.
        requires_reindex: True for the :data:`common.config.REINDEX_KEYS`.
        default_value: The coded default, or ``None`` for secrets and keys
            without one.
    """

    key: str
    value: str | None
    source: str
    is_secret: bool
    requires_reindex: bool
    default_value: str | None = None


class SettingsResponse(BaseModel):
    """Body of ``GET /api/settings`` and ``PUT /api/settings``.

    ``reindex_triggered`` is true when a ``PUT`` scheduled a full index
    rebuild; always false on ``GET``.
    """

    settings: list[SettingItemResponse]
    reindex_triggered: bool = False


class UpdateSettingsRequest(BaseModel):
    """Body of ``PUT /api/settings``.

    Values are raw strings, as the ``config`` table stores them;
    ``common.config`` parses them.
    """

    changes: dict[str, str] = Field(max_length=MAX_SETTINGS_KEYS)

    @field_validator("changes")
    @classmethod
    def _bound_value_lengths(cls, value: dict[str, str]) -> dict[str, str]:
        """Reject any value longer than :data:`MAX_SETTINGS_VALUE_LENGTH`.

        ``Field(max_length=...)`` on a dict bounds only the number of keys.
        Rejecting beats truncating: a silently cut config value is far worse.
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

    Carries the unsaved form values, so an admin can verify a connection
    before saving it. An empty field means "use the stored value"; the screen
    sends an empty token when the masked one was not replaced.
    """

    service: Literal["paperless", "openai", "ollama"] = "paperless"
    paperless_url: str = Field(default="", max_length=MAX_PAPERLESS_URL_LENGTH)
    paperless_token: str = Field(default="", max_length=MAX_SETTINGS_VALUE_LENGTH)
    openai_api_key: str = Field(default="", max_length=MAX_SETTINGS_VALUE_LENGTH)
    ollama_base_url: str = Field(default="", max_length=MAX_PAPERLESS_URL_LENGTH)

    @field_validator("paperless_url")
    @classmethod
    def _check_paperless_url(cls, value: str) -> str:
        """Require ``http(s)://`` and a host, and reject userinfo.

        Userinfo would let a compromised admin session smuggle a stored
        credential to a probe target.
        """
        if not value:
            return value
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("paperless_url must start with http:// or https://")
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
        """Apply the ``paperless_url`` checks to a non-empty Ollama URL."""
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
    """Body of ``POST /api/settings/test-connection``.

    ``document_count`` is set only by a successful Paperless probe, else 0.
    """

    ok: bool
    document_count: int
    detail: str
