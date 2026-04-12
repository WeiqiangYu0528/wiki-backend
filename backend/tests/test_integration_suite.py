"""Comprehensive integration tests for the FastAPI + LangGraph wiki agent system.

Covers: HTTP endpoints, authentication, middleware, memory, cache,
embedding cache, trace store, context engine, compactor, and token estimation.
"""

import math
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.sqlite_memory import SQLiteMemory
from search.cache import MultiLevelCache
from search.embedding_cache import PersistentEmbeddingCache
from observability.tokens import estimate_tokens
from context_engine import ContextCompactor, TokenBudget


# ---------------------------------------------------------------------------
# 1. Health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_endpoint(self, test_client):
        """GET /health returns 200 with status ok."""
        resp = test_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"


# ---------------------------------------------------------------------------
# 2–4. Login / authentication
# ---------------------------------------------------------------------------

class TestLogin:
    def test_login_valid_credentials(self, test_client, monkeypatch):
        """POST /login with correct creds returns a bearer token."""
        from security import settings as _settings

        monkeypatch.setattr(_settings, "app_admin_username", "admin")
        monkeypatch.setattr(_settings, "app_admin_password", "password")
        monkeypatch.setattr(_settings, "app_mfa_secret", "")

        resp = test_client.post(
            "/login",
            json={"username": "admin", "password": "password", "totp": ""},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    def test_login_invalid_password(self, test_client, monkeypatch):
        """Wrong password → 400."""
        from security import settings as _settings

        monkeypatch.setattr(_settings, "app_admin_password", "password")

        resp = test_client.post(
            "/login",
            json={"username": "admin", "password": "wrong", "totp": ""},
        )
        assert resp.status_code == 400

    def test_login_invalid_username(self, test_client, monkeypatch):
        """Unknown user → 400."""
        from security import settings as _settings

        monkeypatch.setattr(_settings, "app_admin_username", "admin")
        monkeypatch.setattr(_settings, "app_admin_password", "password")

        resp = test_client.post(
            "/login",
            json={"username": "nobody", "password": "password", "totp": ""},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 5–7. Auth-gated endpoints
# ---------------------------------------------------------------------------

class TestAuthRequired:
    def test_chat_requires_auth(self, test_client):
        """POST /chat without token → 401."""
        resp = test_client.post("/chat", json={"query": "hi"})
        assert resp.status_code == 401

    def test_chat_stream_requires_auth(self, test_client):
        """POST /chat/stream without token → 401."""
        resp = test_client.post("/chat/stream", json={"query": "hi"})
        assert resp.status_code == 401

    def test_proposals_require_auth(self, test_client):
        """GET /proposals/xxx without token → 401."""
        resp = test_client.get("/proposals/xxx")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 8–9. Middleware (request ID, CORS)
# ---------------------------------------------------------------------------

class TestMiddleware:
    def test_request_id_header(self, test_client):
        """Every response carries X-Request-ID."""
        resp = test_client.get("/health")
        assert "x-request-id" in resp.headers

    def test_cors_headers_present(self, test_client):
        """OPTIONS preflight returns CORS headers for an allowed origin."""
        resp = test_client.options(
            "/chat",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" in resp.headers


# ---------------------------------------------------------------------------
# 10–11. SQLiteMemory
# ---------------------------------------------------------------------------

class TestSQLiteMemory:
    def test_memory_add_query_clear_cycle(self, memory_store):
        """add → query → clear lifecycle."""
        memory_store.add("FastAPI is great for APIs")
        memory_store.add("LangGraph orchestrates agents")

        results = memory_store.query("FastAPI")
        assert len(results) >= 1
        assert any("FastAPI" in r["content"] for r in results)

        memory_store.clear()
        assert memory_store.count() == 0

    def test_memory_eviction_at_capacity(self, tmp_data_dir):
        """Adding max_items+1 evicts the oldest entry."""
        cap = 5
        mem = SQLiteMemory(
            db_path=os.path.join(tmp_data_dir, "evict.db"),
            max_items=cap,
        )
        for i in range(cap + 3):
            mem.add(f"memory item {i}")

        assert mem.count() == cap


# ---------------------------------------------------------------------------
# 12–13. MultiLevelCache
# ---------------------------------------------------------------------------

class TestMultiLevelCache:
    def test_cache_put_get_cycle(self, cache_store):
        """put → get returns the same data."""
        data = [{"title": "page1", "score": 0.9}]
        cache_store.put("hello world", "wiki", data, token_count=10)
        cached = cache_store.get("hello world", "wiki")
        assert cached == data

    def test_cache_l2_persistence(self, tmp_data_dir):
        """A new cache instance reads L2 data written by a previous one."""
        db = os.path.join(tmp_data_dir, "persist.db")
        data = [{"title": "persisted"}]

        c1 = MultiLevelCache(db_path=db, l1_max_entries=10, l2_ttl_seconds=3600)
        c1.put("q", "s", data, token_count=5)

        c2 = MultiLevelCache(db_path=db, l1_max_entries=10, l2_ttl_seconds=3600)
        assert c2.get("q", "s") == data


# ---------------------------------------------------------------------------
# 14. PersistentEmbeddingCache
# ---------------------------------------------------------------------------

class TestEmbeddingCache:
    def test_embedding_cache_hit_miss(self, embedding_cache):
        """Store an embedding, verify hit; query missing key, verify miss."""
        vec = [0.1, 0.2, 0.3, 0.4]
        assert embedding_cache.get("model-a", "hello") is None
        assert embedding_cache.stats["misses"] == 1

        embedding_cache.put("model-a", "hello", vec)
        result = embedding_cache.get("model-a", "hello")

        assert result is not None
        assert len(result) == len(vec)
        for a, b in zip(result, vec):
            assert abs(a - b) < 1e-5
        assert embedding_cache.stats["hits"] == 1


# ---------------------------------------------------------------------------
# 15. RequestTraceStore
# ---------------------------------------------------------------------------

class TestTraceStore:
    def test_trace_store_write_read(self, trace_store):
        """write → recent() returns the trace."""
        trace_store.write(
            request_id="req-001",
            model="gpt-4",
            query="What is FastAPI?",
            status="ok",
            total_tokens=150,
            llm_calls=1,
        )
        traces = trace_store.recent(limit=5)
        assert len(traces) >= 1
        latest = traces[0]
        assert latest["id"] == "req-001"
        assert latest["model"] == "gpt-4"
        assert latest["total_tokens"] == 150


# ---------------------------------------------------------------------------
# 16. ContextEngine.assemble
# ---------------------------------------------------------------------------

class TestContextEngine:
    def test_context_engine_assemble(self, context_engine):
        """assemble() returns messages list and budget_summary dict."""
        result = context_engine.assemble(
            system_prompt="You are a helpful assistant.",
            messages=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
            query="Tell me about testing.",
        )
        assert "messages" in result
        assert "budget_summary" in result
        assert "total_tokens" in result
        assert isinstance(result["messages"], list)
        assert result["messages"][0]["role"] == "system"
        assert result["messages"][-1]["role"] == "user"
        assert result["messages"][-1]["content"] == "Tell me about testing."


# ---------------------------------------------------------------------------
# 17. ContextCompactor
# ---------------------------------------------------------------------------

class TestCompactor:
    def test_compactor_prunes_old_tools(self):
        """Tool outputs outside the protected window get pruned."""
        compactor = ContextCompactor(protected_turns=1, trigger_pct=0.0)

        long_output = "x" * 500
        messages = [
            {"role": "user", "content": "turn-1 question"},
            {"role": "assistant", "content": "calling tool..."},
            {"role": "tool", "name": "search", "content": long_output},
            {"role": "assistant", "content": "here is the answer"},
            # --- second turn (protected) ---
            {"role": "user", "content": "turn-2 question"},
            {"role": "assistant", "content": "calling tool again..."},
            {"role": "tool", "name": "read_file", "content": long_output},
            {"role": "assistant", "content": "final answer"},
        ]

        result = compactor.compact(messages, token_budget=100)

        # The first tool output (turn 1, outside protected window) should be pruned
        pruned_tool = result[2]
        assert "[Tool output pruned" in pruned_tool["content"]
        assert compactor.last_pruned_count >= 1

        # The second tool output (turn 2, inside protected window) should survive
        protected_tool = result[6]
        assert protected_tool["content"] == long_output


# ---------------------------------------------------------------------------
# 18. Token estimation
# ---------------------------------------------------------------------------

class TestTokenEstimation:
    def test_token_estimation_accuracy(self):
        """estimate_tokens returns ceil(len/4) — reasonable heuristic."""
        assert estimate_tokens("") == 0
        assert estimate_tokens("abcd") == 1
        assert estimate_tokens("abcde") == 2
        text = "hello world, this is a test sentence"
        expected = math.ceil(len(text) / 4)
        assert estimate_tokens(text) == expected

    def test_token_budget_allocation(self):
        """TokenBudget allocates and tracks usage correctly."""
        budget = TokenBudget(context_limit=10000)
        alloc = budget.allocate()
        assert alloc["system"] == int(10000 * 0.03)
        assert alloc["history"] == int(10000 * 0.35)

        budget.use("system", 100)
        assert budget.used("system") == 100
        assert budget.remaining("system") == alloc["system"] - 100
        assert not budget.is_over_budget()
