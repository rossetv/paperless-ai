"""Tests for appdb.config — the config-table query functions.

Covers: get_all on an empty and a populated table; get hit and miss;
set_value insert and update (upsert); set_many writes a batch atomically;
updated_at is stamped on every write; an empty set_many is a no-op; and the
hot-load counter — get_config_version starts at 0 and every write bumps it.
"""

from __future__ import annotations

import pytest

from appdb import config as config_store
from appdb.connection import connect
from appdb.schema import ensure_schema


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def test_get_all_is_empty_for_a_fresh_table(conn) -> None:
    assert config_store.get_all(conn) == {}


def test_set_value_then_get_round_trips(conn) -> None:
    config_store.set_value(conn, "CHUNK_SIZE", "2000")
    assert config_store.get(conn, "CHUNK_SIZE") == "2000"


def test_get_returns_none_when_absent(conn) -> None:
    assert config_store.get(conn, "NOT_SET") is None


def test_set_value_updates_an_existing_key(conn) -> None:
    config_store.set_value(conn, "CHUNK_SIZE", "2000")
    config_store.set_value(conn, "CHUNK_SIZE", "4000")
    assert config_store.get(conn, "CHUNK_SIZE") == "4000"
    # The upsert must not create a second row.
    count = conn.execute(
        "SELECT COUNT(*) FROM config WHERE key = 'CHUNK_SIZE'"
    ).fetchone()[0]
    assert count == 1


def test_get_all_returns_every_pair(conn) -> None:
    config_store.set_value(conn, "CHUNK_SIZE", "2000")
    config_store.set_value(conn, "LOG_LEVEL", "DEBUG")
    assert config_store.get_all(conn) == {
        "CHUNK_SIZE": "2000",
        "LOG_LEVEL": "DEBUG",
    }


def test_set_many_writes_a_batch(conn) -> None:
    config_store.set_many(
        conn, {"CHUNK_SIZE": "2000", "LOG_LEVEL": "DEBUG", "OCR_DPI": "300"}
    )
    assert config_store.get_all(conn) == {
        "CHUNK_SIZE": "2000",
        "LOG_LEVEL": "DEBUG",
        "OCR_DPI": "300",
    }


def test_set_many_upserts_existing_keys(conn) -> None:
    config_store.set_value(conn, "CHUNK_SIZE", "2000")
    config_store.set_many(conn, {"CHUNK_SIZE": "8000", "OCR_DPI": "150"})
    assert config_store.get(conn, "CHUNK_SIZE") == "8000"
    assert config_store.get(conn, "OCR_DPI") == "150"


def test_set_many_with_an_empty_mapping_is_a_noop(conn) -> None:
    config_store.set_many(conn, {})
    assert config_store.get_all(conn) == {}


def test_set_value_stamps_updated_at(conn) -> None:
    config_store.set_value(conn, "CHUNK_SIZE", "2000")
    updated_at = conn.execute(
        "SELECT updated_at FROM config WHERE key = 'CHUNK_SIZE'"
    ).fetchone()[0]
    # An ISO-8601 UTC timestamp — non-empty and offset-aware.
    assert updated_at != ""
    assert updated_at.endswith("+00:00")


def test_config_version_starts_at_zero(conn) -> None:
    """A migrated database reports config_version 0 before any write."""
    assert config_store.get_config_version(conn) == 0


def test_set_value_bumps_the_config_version(conn) -> None:
    """Each set_value increments config_version by one."""
    config_store.set_value(conn, "CHUNK_SIZE", "2000")
    assert config_store.get_config_version(conn) == 1
    config_store.set_value(conn, "OCR_DPI", "300")
    assert config_store.get_config_version(conn) == 2


def test_set_many_bumps_the_config_version_once(conn) -> None:
    """A whole set_many batch is one config change — one bump, not one per key."""
    config_store.set_many(
        conn, {"CHUNK_SIZE": "2000", "LOG_LEVEL": "DEBUG", "OCR_DPI": "300"}
    )
    assert config_store.get_config_version(conn) == 1


def test_empty_set_many_does_not_bump_the_config_version(conn) -> None:
    """An empty set_many is a no-op — it writes nothing and bumps nothing."""
    config_store.set_many(conn, {})
    assert config_store.get_config_version(conn) == 0


def test_config_version_is_visible_with_the_written_value(conn) -> None:
    """The bump shares the write's transaction: a reader sees the new value
    and the new config_version together, never one without the other."""
    config_store.set_value(conn, "CHUNK_SIZE", "2000")
    assert config_store.get(conn, "CHUNK_SIZE") == "2000"
    assert config_store.get_config_version(conn) == 1


def test_seed_from_env_populates_an_empty_table(conn) -> None:
    """seed_from_env copies present env keys into an empty config table."""
    env = {"CHUNK_SIZE": "2000", "LOG_LEVEL": "DEBUG", "IRRELEVANT": "x"}
    seeded = config_store.seed_from_env(
        conn, environ=env, keys={"CHUNK_SIZE", "LOG_LEVEL", "OCR_DPI"}
    )
    assert seeded == 2
    assert config_store.get_all(conn) == {
        "CHUNK_SIZE": "2000",
        "LOG_LEVEL": "DEBUG",
    }


def test_seed_from_env_ignores_keys_absent_from_the_env(conn) -> None:
    """A catalogue key not present in the environment is not seeded."""
    seeded = config_store.seed_from_env(
        conn, environ={"CHUNK_SIZE": "2000"}, keys={"CHUNK_SIZE", "OCR_DPI"}
    )
    assert seeded == 1
    assert config_store.get(conn, "OCR_DPI") is None


def test_seed_from_env_ignores_env_keys_not_in_the_catalogue(conn) -> None:
    """An env var that is not a known config key is never seeded."""
    config_store.seed_from_env(
        conn,
        environ={"CHUNK_SIZE": "2000", "PATH": "/usr/bin", "HOME": "/root"},
        keys={"CHUNK_SIZE"},
    )
    assert set(config_store.get_all(conn)) == {"CHUNK_SIZE"}


def test_seed_from_env_is_a_noop_when_the_table_is_not_empty(conn) -> None:
    """seed_from_env never overwrites an already-populated config table."""
    config_store.set_value(conn, "CHUNK_SIZE", "8000")
    seeded = config_store.seed_from_env(
        conn, environ={"CHUNK_SIZE": "2000", "LOG_LEVEL": "DEBUG"},
        keys={"CHUNK_SIZE", "LOG_LEVEL"},
    )
    assert seeded == 0
    # The admin-edited value is untouched; the env value did not leak in.
    assert config_store.get(conn, "CHUNK_SIZE") == "8000"
    assert config_store.get(conn, "LOG_LEVEL") is None


def test_seed_from_env_returns_zero_for_an_empty_environment(conn) -> None:
    """An empty environment seeds nothing and reports zero."""
    seeded = config_store.seed_from_env(
        conn, environ={}, keys={"CHUNK_SIZE", "OCR_DPI"}
    )
    assert seeded == 0
    assert config_store.get_all(conn) == {}
