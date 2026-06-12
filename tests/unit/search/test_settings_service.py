"""Tests for search.settings_service — read/diff/re-index-impact logic.

Covers: effective-value resolution with the correct source label; secret
flagging; validate_change_set rejects unknown keys and values that break
Settings; reindex_required is true exactly when a re-index key changed; an
empty change set needs no re-index.
"""

from __future__ import annotations

import pytest

from search.settings_service import (
    SettingView,
    reindex_required,
    validate_change_set,
    view_settings,
)


def test_view_reports_a_database_value_as_database_sourced() -> None:
    views = view_settings(config_table={"OCR_DPI": "175"}, environ={"OCR_DPI": "150"})
    by_key = {v.key: v for v in views}
    assert by_key["OCR_DPI"].effective_value == "175"
    assert by_key["OCR_DPI"].source == "database"


def test_view_reports_an_environment_value_when_not_in_the_table() -> None:
    views = view_settings(config_table={}, environ={"OCR_DPI": "150"})
    by_key = {v.key: v for v in views}
    assert by_key["OCR_DPI"].effective_value == "150"
    assert by_key["OCR_DPI"].source == "environment"


def test_view_reports_a_default_when_neither_set() -> None:
    views = view_settings(config_table={}, environ={})
    by_key = {v.key: v for v in views}
    # OCR_DPI is not set anywhere — it falls to the coded default.
    assert by_key["OCR_DPI"].source == "default"


def test_view_carries_coded_default_for_default_sourced_keys() -> None:
    """A key on its coded default gets a non-None default_value string."""
    views = view_settings(config_table={}, environ={})
    by_key = {v.key: v for v in views}
    # OCR_DPI coded default is 300.
    assert by_key["OCR_DPI"].default_value == "300"
    # CHUNK_SIZE coded default is 2000.
    assert by_key["CHUNK_SIZE"].default_value == "2000"
    # EMBEDDING_MODEL coded default is text-embedding-3-small.
    assert by_key["EMBEDDING_MODEL"].default_value == "text-embedding-3-small"


def test_view_carries_none_default_value_for_secret_keys() -> None:
    """Secret keys never expose a coded default — default_value is None."""
    views = view_settings(config_table={}, environ={})
    by_key = {v.key: v for v in views}
    assert by_key["OPENAI_API_KEY"].default_value is None
    assert by_key["PAPERLESS_TOKEN"].default_value is None


def test_view_flags_secret_keys() -> None:
    views = view_settings(config_table={}, environ={})
    by_key = {v.key: v for v in views}
    assert by_key["OPENAI_API_KEY"].is_secret is True
    assert by_key["PAPERLESS_TOKEN"].is_secret is True
    assert by_key["OCR_DPI"].is_secret is False


def test_view_covers_every_config_key() -> None:
    """view_settings returns one SettingView per config key, no more."""
    from common.config import CONFIG_KEYS

    views = view_settings(config_table={}, environ={})
    assert {v.key for v in views} == set(CONFIG_KEYS)
    assert all(isinstance(v, SettingView) for v in views)


def test_validate_rejects_an_unknown_key() -> None:
    with pytest.raises(ValueError, match="unknown configuration key"):
        validate_change_set(
            changes={"NOT_A_REAL_KEY": "x"},
            config_table={},
            environ={
                "PAPERLESS_TOKEN": "t",
                "OPENAI_API_KEY": "k",
            },
        )


def test_validate_rejects_a_value_that_breaks_settings() -> None:
    """A change that makes Settings invalid is rejected before it is written."""
    with pytest.raises(ValueError, match="CHUNK_SIZE"):
        validate_change_set(
            changes={"CHUNK_SIZE": "not-an-int"},
            config_table={},
            environ={"PAPERLESS_TOKEN": "t", "OPENAI_API_KEY": "k"},
        )


def test_validate_accepts_a_good_change_set() -> None:
    """A valid change set passes and returns the keys that actually changed."""
    changed = validate_change_set(
        changes={"OCR_DPI": "200", "CHUNK_SIZE": "3000"},
        config_table={"OCR_DPI": "200"},  # OCR_DPI is unchanged
        environ={"PAPERLESS_TOKEN": "t", "OPENAI_API_KEY": "k"},
    )
    # OCR_DPI was already 200 in the table — only CHUNK_SIZE changed.
    assert changed == {"CHUNK_SIZE"}


_SECRETS = {"PAPERLESS_TOKEN": "t", "OPENAI_API_KEY": "k"}


def test_reindex_required_is_true_when_a_reindex_key_changed() -> None:
    # CHUNK_SIZE is a re-index key; changing it stales every chunk.
    assert (
        reindex_required(
            changes={"CHUNK_SIZE": "3000", "OCR_DPI": "200"},
            config_table={},
            environ=_SECRETS,
        )
        is True
    )


def test_reindex_required_is_false_when_no_reindex_key_changed() -> None:
    # OCR_DPI and LOG_LEVEL hot-load with no re-index.
    assert (
        reindex_required(
            changes={"OCR_DPI": "200", "LOG_LEVEL": "DEBUG"},
            config_table={},
            environ=_SECRETS,
        )
        is False
    )


def test_reindex_required_of_an_empty_change_set_is_false() -> None:
    assert reindex_required(changes={}, config_table={}, environ=_SECRETS) is False


def test_reindex_required_is_true_when_llm_provider_flip_changes_embeddings() -> None:
    """Flipping LLM_PROVIDER stales the index via the derived EMBEDDING_PROVIDER.

    LLM_PROVIDER is not itself a re-index key, so the old raw changed-key
    intersection missed this and the index would have been silently wiped with no
    warning. The resolved-identity comparison catches it.
    """
    assert (
        reindex_required(
            changes={"LLM_PROVIDER": "ollama"},
            config_table={},
            environ=_SECRETS,
        )
        is True
    )


def test_reindex_required_is_false_for_a_no_op_llm_provider_change() -> None:
    assert (
        reindex_required(
            changes={"LLM_PROVIDER": "openai"},
            config_table={},
            environ=_SECRETS,
        )
        is False
    )


def test_validate_rejects_ollama_provider_with_an_openai_embedding_model() -> None:
    """A provider flip that would leave an OpenAI embedding model on Ollama is
    refused — saving it would wipe the index and then fail to re-embed."""
    with pytest.raises(ValueError, match="OpenAI model and"):
        validate_change_set(
            changes={"LLM_PROVIDER": "ollama"},
            config_table={},
            environ=_SECRETS,
        )


def test_validate_rejects_setting_an_openai_model_while_on_ollama() -> None:
    """The guard fires on the resulting config, not just on a provider flip."""
    with pytest.raises(ValueError, match="OpenAI model and"):
        validate_change_set(
            changes={"EMBEDDING_MODEL": "text-embedding-3-large"},
            config_table={
                "LLM_PROVIDER": "ollama",
                "EMBEDDING_MODEL": "nomic-embed-text",
                "EMBEDDING_DIMENSIONS": "768",
            },
            environ=_SECRETS,
        )


def test_validate_accepts_ollama_with_a_local_embedding_model() -> None:
    """Flipping to Ollama WITH a local embedding model and its dimensions is a
    coherent, allowed change."""
    changed = validate_change_set(
        changes={
            "LLM_PROVIDER": "ollama",
            "EMBEDDING_MODEL": "nomic-embed-text",
            "EMBEDDING_DIMENSIONS": "768",
        },
        config_table={},
        environ=_SECRETS,
    )
    assert changed == {"LLM_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS"}
