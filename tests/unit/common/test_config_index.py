"""Tests for common.config — indexer/index settings.

Split from test_config.py to stay within the §3.1 500-line ceiling.
Covers: INDEX_DB_PATH, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS,
EMBEDDING_MAX_CONCURRENT, RECONCILE_INTERVAL, DELETION_SWEEP_INTERVAL,
CHUNK_SIZE, CHUNK_OVERLAP.
"""

from __future__ import annotations

import os

import pytest

from common.config import Settings

_MINIMAL_ENV = {
    "PAPERLESS_TOKEN": "tok-123",
    "OPENAI_API_KEY": "sk-test",
}


def _build(mocker, env: dict[str, str]) -> Settings:
    """Build Settings with *only* the supplied env vars."""
    mocker.patch.dict(os.environ, env, clear=True)
    return Settings.from_environment()


_INDEX_DEFAULTS = [
    ("INDEX_DB_PATH", "/data/index.db"),
    ("EMBEDDING_MODEL", "text-embedding-3-small"),
    ("EMBEDDING_DIMENSIONS", 1536),
    ("EMBEDDING_MAX_CONCURRENT", 4),
    ("RECONCILE_INTERVAL", 300),
    ("DELETION_SWEEP_INTERVAL", 3600),
    ("CHUNK_SIZE", 2000),
    ("CHUNK_OVERLAP", 256),
]


class TestIndexSettingsDefaults:
    """Indexer settings load correct defaults when env vars are absent."""

    @pytest.mark.parametrize(
        "attr, expected",
        _INDEX_DEFAULTS,
        ids=[a for a, _ in _INDEX_DEFAULTS],
    )
    def test_default_value(self, mocker, attr, expected):
        s = _build(mocker, _MINIMAL_ENV)
        assert getattr(s, attr) == expected


_INDEX_CUSTOM = [
    ("INDEX_DB_PATH", "/mnt/store/search.db", "INDEX_DB_PATH", "/mnt/store/search.db"),
    ("EMBEDDING_MODEL", "text-embedding-3-large", "EMBEDDING_MODEL", "text-embedding-3-large"),
    ("EMBEDDING_DIMENSIONS", "3072", "EMBEDDING_DIMENSIONS", 3072),
    ("EMBEDDING_MAX_CONCURRENT", "8", "EMBEDDING_MAX_CONCURRENT", 8),
    ("RECONCILE_INTERVAL", "60", "RECONCILE_INTERVAL", 60),
    ("DELETION_SWEEP_INTERVAL", "7200", "DELETION_SWEEP_INTERVAL", 7200),
    ("CHUNK_SIZE", "1500", "CHUNK_SIZE", 1500),
    ("CHUNK_OVERLAP", "128", "CHUNK_OVERLAP", 128),
]


class TestIndexSettingsCustom:
    """Indexer settings parse set values correctly."""

    @pytest.mark.parametrize(
        "env_key, env_val, attr, expected",
        _INDEX_CUSTOM,
        ids=[e[0] for e in _INDEX_CUSTOM],
    )
    def test_custom_value(self, mocker, env_key, env_val, attr, expected):
        s = _build(mocker, {**_MINIMAL_ENV, env_key: env_val})
        assert getattr(s, attr) == expected


class TestIndexSettingsInvalidInts:
    """Non-integer values for integer indexer settings raise a contextful ValueError."""

    @pytest.mark.parametrize(
        "env_key",
        [
            "EMBEDDING_DIMENSIONS",
            "EMBEDDING_MAX_CONCURRENT",
            "RECONCILE_INTERVAL",
            "DELETION_SWEEP_INTERVAL",
            "CHUNK_SIZE",
            "CHUNK_OVERLAP",
        ],
    )
    def test_non_integer_raises(self, mocker, env_key):
        # The message must name the offending variable, not the opaque stdlib
        # 'invalid literal for int()' text (CODE_GUIDELINES §6.6).
        with pytest.raises(ValueError, match=f"{env_key} must be an integer"):
            _build(mocker, {**_MINIMAL_ENV, env_key: "not-an-int"})


class TestIndexSettingsBounds:
    """Out-of-range integer indexer settings raise a contextful ValueError."""

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_embedding_dimensions_must_be_positive(self, mocker, value):
        with pytest.raises(ValueError, match="EMBEDDING_DIMENSIONS must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, "EMBEDDING_DIMENSIONS": value})

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_chunk_size_must_be_positive(self, mocker, value):
        with pytest.raises(ValueError, match="CHUNK_SIZE must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, "CHUNK_SIZE": value})

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_reconcile_interval_must_be_positive(self, mocker, value):
        with pytest.raises(ValueError, match="RECONCILE_INTERVAL must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, "RECONCILE_INTERVAL": value})

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_deletion_sweep_interval_must_be_positive(self, mocker, value):
        with pytest.raises(ValueError, match="DELETION_SWEEP_INTERVAL must be >= 1"):
            _build(mocker, {**_MINIMAL_ENV, "DELETION_SWEEP_INTERVAL": value})

    def test_chunk_overlap_negative_raises(self, mocker):
        with pytest.raises(ValueError, match="CHUNK_OVERLAP must be"):
            _build(mocker, {**_MINIMAL_ENV, "CHUNK_OVERLAP": "-1"})

    def test_chunk_overlap_equal_to_chunk_size_raises(self, mocker):
        # Overlap must be strictly less than the chunk size.
        with pytest.raises(ValueError, match="CHUNK_OVERLAP must be"):
            _build(
                mocker,
                {**_MINIMAL_ENV, "CHUNK_SIZE": "1000", "CHUNK_OVERLAP": "1000"},
            )

    def test_chunk_overlap_greater_than_chunk_size_raises(self, mocker):
        with pytest.raises(ValueError, match="CHUNK_OVERLAP must be"):
            _build(
                mocker,
                {**_MINIMAL_ENV, "CHUNK_SIZE": "500", "CHUNK_OVERLAP": "600"},
            )

    def test_chunk_overlap_zero_is_allowed(self, mocker):
        s = _build(mocker, {**_MINIMAL_ENV, "CHUNK_OVERLAP": "0"})
        assert s.CHUNK_OVERLAP == 0

    @pytest.mark.parametrize("value", ["-1", "-4"])
    def test_embedding_max_concurrent_clamped_to_zero(self, mocker, value):
        s = _build(mocker, {**_MINIMAL_ENV, "EMBEDDING_MAX_CONCURRENT": value})
        assert s.EMBEDDING_MAX_CONCURRENT == 0
