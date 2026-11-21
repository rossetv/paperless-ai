"""Helpers for building search-pipeline objects and authenticated clients in tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from search.core import SearchCore
from search.judge import RelevanceJudge
from search.planner import QueryPlanner
from search.retriever import Retriever
from search.synthesizer import Synthesizer

if TYPE_CHECKING:
    from tests.helpers.llm import ScriptedLLMClient


def build_search_core(
    *,
    settings: Any,
    llm_client: ScriptedLLMClient,
    store_reader: Any,
    embedding_client: Any,
) -> SearchCore:
    """Assemble a SearchCore with real pipeline stages over the given collaborators.

    Every LLM stage's ``_create_completion`` is routed to *llm_client*; the
    store reader and embedding client may be mocks or real objects.
    """
    planner = QueryPlanner(settings)
    planner._create_completion = llm_client.route  # type: ignore[method-assign]
    retriever = Retriever(settings, store_reader, embedding_client)
    synthesizer = Synthesizer(settings)
    synthesizer._create_completion = llm_client.route  # type: ignore[method-assign]
    judge = RelevanceJudge(settings)
    judge._create_completion = llm_client.route  # type: ignore[method-assign]
    return SearchCore(
        settings=settings,
        store_reader=store_reader,
        planner=planner,
        retriever=retriever,
        synthesizer=synthesizer,
        judge=judge,
    )


def mint_api_key(
    app_db: object,
    *,
    owner_user_id: int,
    scopes: str = "api",
    name: str = "test-key",
) -> str:
    """Generate, hash and store an API key in *app_db*; return the raw key.

    The owning user must already exist. Send the key as a Bearer token.
    """
    from appdb.api_keys import create as create_key
    from search.api_keys import generate_raw_key, hash_key, key_display_prefix

    raw = generate_raw_key()
    create_key(
        app_db,
        key_hash=hash_key(raw),
        key_prefix=key_display_prefix(raw),
        name=name,
        owner_user_id=owner_user_id,
        scopes=scopes,
    )
    return raw


def seed_user_and_login(
    app_db: object,
    client: object,
    *,
    username: str = "tester",
    password: str = "test-password",
    role: str = "admin",
) -> None:
    """Create a user directly in *app_db*, then log *client* in through the API."""
    from appdb.passwords import hash_password
    from appdb.users import create as create_user

    create_user(
        app_db,
        username=username,
        password_hash=hash_password(password),
        role=role,
    )
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
