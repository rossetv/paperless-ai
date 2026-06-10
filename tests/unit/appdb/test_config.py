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
        conn,
        environ={"CHUNK_SIZE": "2000", "LOG_LEVEL": "DEBUG"},
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


# ---------------------------------------------------------------------------
# AI_MODELS → OCR_MODELS / CLASSIFY_MODELS migration tests
# ---------------------------------------------------------------------------


def test_migration_copies_ai_models_to_both_new_keys(conn) -> None:
    """When AI_MODELS exists in the config table the migration creates
    OCR_MODELS and CLASSIFY_MODELS with the same value and deletes AI_MODELS."""
    from appdb.migrations import _migrate_v6

    config_store.set_value(conn, "AI_MODELS", "gpt-5.4-mini,gpt-5.4")

    _migrate_v6(conn)

    stored = config_store.get_all(conn)
    assert stored.get("OCR_MODELS") == "gpt-5.4-mini,gpt-5.4"
    assert stored.get("CLASSIFY_MODELS") == "gpt-5.4-mini,gpt-5.4"
    assert "AI_MODELS" not in stored


def test_migration_does_not_overwrite_existing_ocr_models(conn) -> None:
    """When OCR_MODELS already exists the migration leaves it untouched."""
    from appdb.migrations import _migrate_v6

    config_store.set_value(conn, "AI_MODELS", "old-model")
    config_store.set_value(conn, "OCR_MODELS", "vision-model")

    _migrate_v6(conn)

    stored = config_store.get_all(conn)
    assert stored.get("OCR_MODELS") == "vision-model"
    assert stored.get("CLASSIFY_MODELS") == "old-model"
    assert "AI_MODELS" not in stored


def test_migration_is_a_noop_when_ai_models_absent(conn) -> None:
    """When no AI_MODELS row exists the migration does nothing — config_version
    must also be unchanged."""
    from appdb.migrations import _migrate_v6

    config_store.set_value(conn, "CHUNK_SIZE", "2000")
    version_before = config_store.get_config_version(conn)

    _migrate_v6(conn)

    stored = config_store.get_all(conn)
    assert "OCR_MODELS" not in stored
    assert "CLASSIFY_MODELS" not in stored
    assert stored.get("CHUNK_SIZE") == "2000"
    # No changes — the hot-load counter must not move.
    assert config_store.get_config_version(conn) == version_before


def test_migration_bumps_config_version(conn) -> None:
    """The migration bumps config_version when it makes changes."""
    from appdb.migrations import _migrate_v6

    version_before = config_store.get_config_version(conn)
    config_store.set_value(conn, "AI_MODELS", "gpt-5.4-mini")

    _migrate_v6(conn)

    assert config_store.get_config_version(conn) > version_before


def test_run_migrations_e2e_v5_to_v6_splits_ai_models(tmp_path) -> None:
    """End-to-end: run_migrations on a v5 DB with AI_MODELS advances to v6,
    creates OCR_MODELS and CLASSIFY_MODELS with the legacy value, and removes
    AI_MODELS."""
    from appdb.migrations import MIGRATIONS, run_migrations

    # Build a DB at schema version 5 by running only the first five migrations.
    conn = connect(str(tmp_path / "e2e.db"))
    try:
        v5_migrations = [(v, fn) for v, fn in MIGRATIONS if v <= 5]
        for version, migration_fn in v5_migrations:
            conn.execute("BEGIN")
            migration_fn(conn)
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(version),),
            )
            conn.commit()

        # Seed an AI_MODELS row as a legacy deployment would have.
        legacy_value = "gpt-5.4-mini,gpt-5.4"
        conn.execute(
            "INSERT INTO config (key, value, updated_at) VALUES (?, ?, '2026-01-01T00:00:00+00:00')",
            ("AI_MODELS", legacy_value),
        )
        conn.commit()

        # Confirm the DB is genuinely at v5 before the run.
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        assert int(row[0]) == 5

        # Run all migrations — only v6 is pending.
        run_migrations(conn)

        # schema_version must now be 6.
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        assert int(row[0]) == 6

        # Both new keys must carry the legacy value; AI_MODELS must be gone.
        stored = config_store.get_all(conn)
        assert stored.get("OCR_MODELS") == legacy_value
        assert stored.get("CLASSIFY_MODELS") == legacy_value
        assert "AI_MODELS" not in stored
    finally:
        conn.close()
