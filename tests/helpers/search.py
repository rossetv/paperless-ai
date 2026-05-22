"""Helpers for constructing search-pipeline objects in tests.

The search ``core`` is assembled the same way in the unit tests (over mock
store / embedding clients) and the integration tests (over a real temporary
store): real planner, retriever, and synthesiser stages with the LLM transport
patched by a scripted driver.  :func:`build_search_core` is that one wiring
point, so neither the unit nor the integration tests re-hand-roll it
(CODE_GUIDELINES §11.5) — it mirrors :mod:`tests.helpers.store`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from search.core import SearchCore
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

    The planner and synthesiser are real — their ``_create_completion`` is
    patched with the scripted driver's router, mirroring
    ``tests/unit/classifier`` — and the retriever is real.  The *store_reader*
    and *embedding_client* may be mocks (unit tests) or real objects
    (integration tests); this helper does not care which.

    Args:
        settings: A Settings-like object (mock or real).
        llm_client: The scripted driver routing planner vs synthesiser calls.
        store_reader: The StoreReader the retriever and core query.
        embedding_client: The EmbeddingClient the retriever uses.

    Returns:
        A ready-to-exercise :class:`~search.core.SearchCore`.
    """
    planner = QueryPlanner(settings)
    planner._create_completion = llm_client.route  # type: ignore[method-assign]
    retriever = Retriever(settings, store_reader, embedding_client)
    synthesizer = Synthesizer(settings)
    synthesizer._create_completion = llm_client.route  # type: ignore[method-assign]
    return SearchCore(
        settings=settings,
        store_reader=store_reader,
        planner=planner,
        retriever=retriever,
        synthesizer=synthesizer,
    )


def seed_user_and_login(
    app_db: object,
    client: object,
    *,
    username: str = "tester",
    password: str = "test-password",
    role: str = "admin",
) -> None:
    """Create a user in *app_db* and log *client* in as them.

    A convenience for tests that need an authenticated session against a
    protected route. Creates the user directly through ``appdb`` (bypassing
    the setup flow) and then drives ``POST /api/auth/login`` so the client's
    cookie jar holds a real session cookie.

    Args:
        app_db: The app.db connection the test app is using.
        client: A ``fastapi.testclient.TestClient`` over the app.
        username: The username to create and log in as.
        password: The password to set and authenticate with.
        role: The role for the created user.
    """
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
