"""Shared pytest fixtures for integration/validation tests."""

import os
import sys
import tempfile

import pytest

# Backend uses sys.path, not package imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from security import Settings, create_access_token  # noqa: E402
from memory.sqlite_memory import SQLiteMemory  # noqa: E402
from search.cache import MultiLevelCache  # noqa: E402
from search.embedding_cache import PersistentEmbeddingCache  # noqa: E402
from observability.trace_store import RequestTraceStore  # noqa: E402
from context_engine import ContextEngine, TokenBudget, ContextCompactor  # noqa: E402


@pytest.fixture()
def tmp_data_dir():
    """Temporary directory for test databases — cleaned up automatically."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture()
def test_settings(tmp_data_dir):
    """Settings with test-safe defaults (temp db paths, MFA disabled)."""
    return Settings(
        app_admin_username="admin",
        app_admin_password="password",
        app_mfa_secret="",
        jwt_secret_key="test-secret",
        environment="test",
        memory_db_path=os.path.join(tmp_data_dir, "memory.db"),
        cache_db_path=os.path.join(tmp_data_dir, "cache.db"),
    )


@pytest.fixture()
def test_client():
    """FastAPI TestClient backed by the real application."""
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture()
def auth_token():
    """Valid JWT for the admin user (uses production settings module)."""
    return create_access_token(data={"sub": "admin"})


@pytest.fixture()
def memory_store(tmp_data_dir):
    """SQLiteMemory backed by a temporary database."""
    return SQLiteMemory(
        db_path=os.path.join(tmp_data_dir, "memory.db"),
        max_items=1000,
    )


@pytest.fixture()
def cache_store(tmp_data_dir):
    """MultiLevelCache backed by a temporary database."""
    return MultiLevelCache(
        db_path=os.path.join(tmp_data_dir, "cache.db"),
        l1_max_entries=200,
        l2_ttl_seconds=3600,
    )


@pytest.fixture()
def embedding_cache(tmp_data_dir):
    """PersistentEmbeddingCache backed by a temporary database."""
    return PersistentEmbeddingCache(
        db_path=os.path.join(tmp_data_dir, "embedding_cache.db"),
    )


@pytest.fixture()
def trace_store(tmp_data_dir):
    """RequestTraceStore backed by a temporary database."""
    return RequestTraceStore(
        db_path=os.path.join(tmp_data_dir, "traces.db"),
    )


@pytest.fixture()
def context_engine(memory_store):
    """ContextEngine wired to a temp memory store and fresh budget."""
    compactor = ContextCompactor(protected_turns=4, trigger_pct=0.5)
    budget = TokenBudget(context_limit=128_000)
    return ContextEngine(
        memory=memory_store,
        compactor=compactor,
        budget=budget,
    )
