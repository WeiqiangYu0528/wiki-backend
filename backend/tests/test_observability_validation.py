"""Observability validation tests for trace store, metrics, tokens, tracing, and config."""

import math
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from observability.trace_store import RequestTraceStore
from observability.tokens import estimate_tokens, extract_usage_metadata
from observability.metrics import AgentMetrics
from observability.config import ObservabilityConfig
from observability.tracing import traced


# ── RequestTraceStore ──────────────────────────────────────────────


def test_trace_store_write_read():
    """Write a trace, read via recent(), verify all fields match."""
    with tempfile.TemporaryDirectory() as tmp:
        store = RequestTraceStore(db_path=os.path.join(tmp, "traces.db"))
        store.write(
            request_id="req-1",
            model="gpt-4",
            query="What is MkDocs?",
            status="ok",
            total_tokens=150,
            input_tokens=100,
            output_tokens=50,
            llm_calls=1,
            tool_calls=2,
            search_calls=3,
            embedding_calls=4,
            prompt_chars=500,
            retrieval_chars=300,
            citations_count=5,
            duration_ms=1200,
            error_message="",
            tiers_used="tier1,tier2",
            tools_used="search,embed",
        )
        rows = store.recent(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == "req-1"
        assert row["model"] == "gpt-4"
        assert row["query"] == "What is MkDocs?"
        assert row["status"] == "ok"
        assert row["total_tokens"] == 150
        assert row["input_tokens"] == 100
        assert row["output_tokens"] == 50
        assert row["llm_calls"] == 1
        assert row["tool_calls"] == 2
        assert row["search_calls"] == 3
        assert row["embedding_calls"] == 4
        assert row["prompt_chars"] == 500
        assert row["retrieval_chars"] == 300
        assert row["citations_count"] == 5
        assert row["duration_ms"] == 1200
        assert row["error_message"] == ""
        assert row["tiers_used"] == "tier1,tier2"
        assert row["tools_used"] == "search,embed"
        assert row["timestamp"]  # non-empty ISO timestamp


def test_trace_store_multiple_entries():
    """Write 3 traces, recent(limit=2) returns only 2 most recent."""
    with tempfile.TemporaryDirectory() as tmp:
        store = RequestTraceStore(db_path=os.path.join(tmp, "traces.db"))
        for i in range(3):
            store.write(f"req-{i}", "ollama", f"query-{i}", "ok")
        rows = store.recent(limit=2)
        assert len(rows) == 2
        # Most recent first (req-2 before req-1)
        ids = [r["id"] for r in rows]
        assert "req-2" in ids
        assert "req-0" not in ids


def test_trace_store_query():
    """Use custom SQL query to filter traces by model."""
    with tempfile.TemporaryDirectory() as tmp:
        store = RequestTraceStore(db_path=os.path.join(tmp, "traces.db"))
        store.write("req-a", "gpt-4", "q1", "ok")
        store.write("req-b", "ollama", "q2", "ok")
        store.write("req-c", "gpt-4", "q3", "error", error_message="timeout")

        gpt_rows = store.query(
            "SELECT * FROM request_traces WHERE model = ?", ("gpt-4",)
        )
        assert len(gpt_rows) == 2
        assert all(r["model"] == "gpt-4" for r in gpt_rows)

        err_rows = store.query(
            "SELECT * FROM request_traces WHERE status = ?", ("error",)
        )
        assert len(err_rows) == 1
        assert err_rows[0]["error_message"] == "timeout"


def test_trace_store_thread_safety():
    """Write from multiple threads concurrently, all writes succeed."""
    with tempfile.TemporaryDirectory() as tmp:
        store = RequestTraceStore(db_path=os.path.join(tmp, "traces.db"))

        def write_trace(s, i):
            s.write(f"req-{i}", "ollama", f"query-{i}", "ok")

        threads = [
            threading.Thread(target=write_trace, args=(store, i)) for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        rows = store.recent(limit=20)
        assert len(rows) == 10
        ids = sorted(r["id"] for r in rows)
        assert ids == sorted(f"req-{i}" for i in range(10))


# ── Token utilities ────────────────────────────────────────────────


def test_estimate_tokens_accuracy():
    """Various test strings: empty → 0, short/long strings follow chars/4."""
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") == math.ceil(5 / 4)  # 2
    long_text = "a" * 1000
    assert estimate_tokens(long_text) == math.ceil(1000 / 4)  # 250
    # Single character
    assert estimate_tokens("x") == 1


def test_extract_usage_metadata_dict():
    """Extract from dict with usage_metadata key."""
    msg = {
        "usage_metadata": {
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
        }
    }
    usage = extract_usage_metadata(msg)
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 20
    assert usage["total_tokens"] == 30


def test_extract_usage_metadata_empty():
    """Extract from message without usage returns zeros."""
    usage = extract_usage_metadata({})
    assert usage == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    usage2 = extract_usage_metadata("just a string")
    assert usage2 == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    # Object without usage_metadata attribute
    class FakeMsg:
        pass

    usage3 = extract_usage_metadata(FakeMsg())
    assert usage3 == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


# ── AgentMetrics ───────────────────────────────────────────────────


def test_agent_metrics_creation():
    """AgentMetrics() creates without error, has expected attributes."""
    m = AgentMetrics()
    # Counters
    assert hasattr(m, "requests_total")
    assert hasattr(m, "llm_calls_total")
    assert hasattr(m, "tool_calls_total")
    assert hasattr(m, "search_calls_total")
    assert hasattr(m, "embedding_calls_total")
    assert hasattr(m, "tokens_total")
    assert hasattr(m, "errors_total")
    # Histograms
    assert hasattr(m, "request_duration")
    assert hasattr(m, "llm_call_duration")
    assert hasattr(m, "tool_call_duration")
    assert hasattr(m, "prompt_tokens_hist")
    assert hasattr(m, "search_results_hist")
    assert hasattr(m, "retrieval_chars_hist")
    # Up-down counter
    assert hasattr(m, "embedding_cache_size")


# ── ObservabilityConfig ────────────────────────────────────────────


def test_observability_config_defaults():
    """ObservabilityConfig has correct default values."""
    cfg = ObservabilityConfig(_env_file="")
    assert cfg.service_name == "mkdocs-agent"
    assert cfg.otel_endpoint == "http://localhost:4317"
    assert cfg.otel_insecure is True
    assert cfg.enabled is True
    assert "traces.db" in cfg.sqlite_path


# ── @traced decorator ──────────────────────────────────────────────


def test_traced_decorator():
    """Function decorated with @traced executes normally and returns result."""

    @traced("test-span")
    def add(a, b):
        return a + b

    assert add(2, 3) == 5


def test_traced_decorator_propagates_exceptions():
    """@traced re-raises exceptions from the wrapped function."""

    @traced("error-span")
    def boom():
        raise ValueError("kaboom")

    try:
        boom()
        assert False, "Should have raised"
    except ValueError as e:
        assert str(e) == "kaboom"
