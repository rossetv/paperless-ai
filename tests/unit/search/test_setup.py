"""Tests for search.setup — first-run setup token and setup-mode detection.

Covers: generate_setup_token yields a non-empty high-entropy token; the
SetupState holder stores it; verify_setup_token is a constant-time compare
that accepts the held token and rejects anything else (including when no
token is set); is_setup_needed reflects whether the users table is empty.
"""

from __future__ import annotations

import pytest

from appdb.connection import connect
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from search.setup import (
    SetupState,
    generate_setup_token,
    is_setup_needed,
    verify_setup_token,
)


@pytest.fixture()
def conn(tmp_path):
    """A migrated app.db connection."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def test_generate_setup_token_is_non_empty() -> None:
    assert len(generate_setup_token()) > 0


def test_generate_setup_token_has_entropy() -> None:
    """A 24-byte token base64-encodes to at least 30 characters."""
    assert len(generate_setup_token()) >= 30


def test_two_generated_tokens_differ() -> None:
    assert generate_setup_token() != generate_setup_token()


def test_setup_state_starts_with_no_token() -> None:
    state = SetupState()
    assert state.token is None


def test_setup_state_holds_an_assigned_token() -> None:
    state = SetupState()
    state.token = "the-setup-token"
    assert state.token == "the-setup-token"


def test_verify_setup_token_accepts_the_held_token() -> None:
    state = SetupState()
    state.token = "correct-token"
    assert verify_setup_token(state, "correct-token") is True


def test_verify_setup_token_rejects_a_wrong_token() -> None:
    state = SetupState()
    state.token = "correct-token"
    assert verify_setup_token(state, "wrong-token") is False


def test_verify_setup_token_rejects_when_no_token_is_set() -> None:
    """With setup already complete (token is None) every value is rejected."""
    state = SetupState()
    assert verify_setup_token(state, "anything") is False
    assert verify_setup_token(state, "") is False


def test_verify_setup_token_rejects_an_empty_candidate() -> None:
    state = SetupState()
    state.token = "correct-token"
    assert verify_setup_token(state, "") is False


def test_is_setup_needed_true_when_no_users(conn) -> None:
    assert is_setup_needed(conn) is True


def test_is_setup_needed_false_when_a_user_exists(conn) -> None:
    create_user(conn, username="admin", password_hash="h", role="admin")
    assert is_setup_needed(conn) is False
