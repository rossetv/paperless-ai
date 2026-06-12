"""Tests for appdb.key_usage — the per-API-key daily LLM-spend table.

Covers: get_tokens_used returns 0 for an absent bucket and the stored total
for a present one; add_usage inserts a fresh bucket then upserts in place
(summing tokens and calls); a zero-delta add records nothing; usage is keyed
per (api_key_id, usage_date) so different keys and dates are independent; and
deleting the owning api_keys row cascades the usage rows away.
"""

from __future__ import annotations

import pytest

from appdb.connection import connect
from appdb.key_usage import add_usage, get_tokens_used, utc_today
from appdb.schema import ensure_schema


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection with one api_keys row to reference."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    # A user and a key the usage rows can reference (FK is enforced).
    c.execute(
        "INSERT INTO users "
        "(id, username, password_hash, role, created_at, updated_at) "
        "VALUES (1, 'u', 'h', 'member', 'now', 'now')"
    )
    c.execute(
        "INSERT INTO api_keys "
        "(id, key_hash, key_prefix, name, owner_user_id, scopes, created_at) "
        "VALUES (7, 'hash7', 'sk-pls-7', 'k7', 1, 'api', 'now')"
    )
    c.commit()
    yield c
    c.close()


def test_get_tokens_used_is_zero_for_an_absent_bucket(conn) -> None:
    """A key with no row for the date has used zero tokens."""
    assert get_tokens_used(conn, 7, utc_today()) == 0


def test_add_usage_inserts_a_fresh_bucket(conn) -> None:
    """The first add for a key/date inserts the bucket with the given totals."""
    today = utc_today()
    add_usage(conn, 7, today, tokens=120, calls=1)
    assert get_tokens_used(conn, 7, today) == 120


def test_add_usage_upserts_in_place_summing_both_counters(conn) -> None:
    """A second add for the same key/date sums tokens and calls, not stacks rows."""
    today = utc_today()
    add_usage(conn, 7, today, tokens=100, calls=1)
    add_usage(conn, 7, today, tokens=55, calls=1)
    assert get_tokens_used(conn, 7, today) == 155
    row = conn.execute(
        "SELECT tokens, calls FROM api_key_usage "
        "WHERE api_key_id = 7 AND usage_date = ?",
        (today,),
    ).fetchone()
    assert (row["tokens"], row["calls"]) == (155, 2)
    # Exactly one row — the upsert grew the bucket in place.
    count = conn.execute(
        "SELECT COUNT(*) FROM api_key_usage WHERE api_key_id = 7"
    ).fetchone()[0]
    assert count == 1


def test_add_usage_with_zero_delta_records_nothing(conn) -> None:
    """A zero-token, zero-call add never inserts an empty bucket."""
    today = utc_today()
    add_usage(conn, 7, today, tokens=0, calls=0)
    count = conn.execute(
        "SELECT COUNT(*) FROM api_key_usage WHERE api_key_id = 7"
    ).fetchone()[0]
    assert count == 0


def test_usage_is_independent_per_date(conn) -> None:
    """A different usage_date is a separate bucket — the day resets the count."""
    add_usage(conn, 7, "2026-06-11", tokens=900, calls=3)
    add_usage(conn, 7, "2026-06-12", tokens=10, calls=1)
    assert get_tokens_used(conn, 7, "2026-06-11") == 900
    assert get_tokens_used(conn, 7, "2026-06-12") == 10


def test_usage_is_independent_per_key(conn) -> None:
    """A second key's bucket does not affect the first key's total."""
    conn.execute(
        "INSERT INTO api_keys "
        "(id, key_hash, key_prefix, name, owner_user_id, scopes, created_at) "
        "VALUES (8, 'hash8', 'sk-pls-8', 'k8', 1, 'api', 'now')"
    )
    conn.commit()
    today = utc_today()
    add_usage(conn, 7, today, tokens=100, calls=1)
    add_usage(conn, 8, today, tokens=500, calls=1)
    assert get_tokens_used(conn, 7, today) == 100
    assert get_tokens_used(conn, 8, today) == 500


def test_deleting_a_key_cascades_its_usage_rows(conn) -> None:
    """ON DELETE CASCADE drops a key's usage when the key is hard-deleted."""
    today = utc_today()
    add_usage(conn, 7, today, tokens=300, calls=2)
    assert get_tokens_used(conn, 7, today) == 300
    with conn:
        conn.execute("DELETE FROM api_keys WHERE id = 7")
    count = conn.execute(
        "SELECT COUNT(*) FROM api_key_usage WHERE api_key_id = 7"
    ).fetchone()[0]
    assert count == 0


def test_utc_today_is_an_iso_date(conn) -> None:
    """utc_today returns a YYYY-MM-DD string the table keys on."""
    today = utc_today()
    assert len(today) == 10
    assert today.count("-") == 2
