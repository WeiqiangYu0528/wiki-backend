"""Tests for search/embedding/memory settings."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_settings_have_search_defaults():
    from security import Settings

    s = Settings(
        _env_file="",
        app_admin_password="test",
        jwt_secret_key="test",
    )
    assert s.ollama_base_url == "http://localhost:11434"
    assert s.ollama_embed_model == "nomic-embed-text"
    assert s.embedding_dimensions == 768
    assert s.search_max_results == 8
    assert s.search_max_chars == 2000
    assert s.search_result_max_chars == 200


def test_settings_have_cache_defaults():
    from security import Settings

    s = Settings(
        _env_file="",
        app_admin_password="test",
        jwt_secret_key="test",
    )
    assert s.cache_l1_max_entries == 200
    assert s.cache_l2_ttl_seconds == 3600
    assert s.cache_db_path == "data/cache.db"


def test_settings_have_context_defaults():
    from security import Settings

    s = Settings(
        _env_file="",
        app_admin_password="test",
        jwt_secret_key="test",
    )
    assert s.context_budget_system_pct == 0.03
    assert s.context_budget_memory_pct == 0.05
    assert s.context_budget_history_pct == 0.35
    assert s.context_budget_search_pct == 0.25
    assert s.context_budget_output_pct == 0.30
    assert s.context_budget_safety_pct == 0.02
    assert s.max_history_turns == 6
    assert s.compactor_protected_turns == 4


def test_settings_have_memory_defaults():
    from security import Settings

    s = Settings(
        _env_file="",
        app_admin_password="test",
        jwt_secret_key="test",
    )
    assert s.memory_db_path == "data/memory.db"
    assert s.memory_max_items == 1000


def test_settings_have_meilisearch_defaults():
    from security import Settings

    s = Settings(
        _env_file="",
        app_admin_password="test",
        jwt_secret_key="test",
    )
    assert s.meilisearch_url == "http://localhost:7700"
    assert s.meilisearch_api_key == ""


def test_settings_have_read_code_defaults():
    from security import Settings

    s = Settings(
        _env_file="",
        app_admin_password="test",
        jwt_secret_key="test",
    )
    assert s.read_code_default_lines == 50
    assert s.read_code_max_symbol_lines == 100
    assert s.embedding_provider == "ollama"
