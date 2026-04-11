# Agent Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add full OpenTelemetry + Jaeger + Prometheus + Grafana observability to the backend agent system, with a supplementary SQLite request summary table.

**Architecture:** Instrument the existing FastAPI + LangGraph backend with OpenTelemetry SDK. Traces export via OTLP to an OTEL Collector sidecar, which fans out to Jaeger (traces) and Prometheus (metrics). Grafana provides pre-provisioned dashboards. A lightweight SQLite table captures per-request summaries for fast local queries.

**Tech Stack:** Python 3.11+, opentelemetry-sdk, opentelemetry-instrumentation-fastapi, opentelemetry-instrumentation-httpx, opentelemetry-exporter-otlp, SQLite, Jaeger, Prometheus, Grafana, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-04-11-agent-observability-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|----------------|
| `backend/observability/__init__.py` | Package init, re-exports `init_observability`, `get_tracer`, `get_meter`, `metrics` |
| `backend/observability/tracing.py` | OTEL tracer/meter init, `@traced` decorator, span helpers |
| `backend/observability/metrics.py` | All Prometheus metric definitions (counters, histograms, gauges) |
| `backend/observability/tokens.py` | Token counting/estimation utilities |
| `backend/observability/trace_store.py` | SQLite `request_traces` writer + query helpers |
| `backend/observability/config.py` | Configuration via env vars (OTEL endpoint, service name, SQLite path) |
| `backend/test_observability.py` | Tests for the observability package |
| `backend/otel-collector-config.yaml` | OTEL Collector pipeline config |
| `backend/prometheus.yml` | Prometheus scrape targets |
| `backend/grafana/provisioning/datasources/datasources.yaml` | Grafana data source config |
| `backend/grafana/provisioning/dashboards/dashboards.yaml` | Grafana dashboard provisioning config |
| `backend/grafana/dashboards/agent-overview.json` | Dashboard 1: Agent Overview |
| `backend/grafana/dashboards/token-deep-dive.json` | Dashboard 2: Token Deep-Dive |
| `backend/grafana/dashboards/search-retrieval.json` | Dashboard 3: Search & Retrieval |

### Modified Files

| File | What Changes |
|------|-------------|
| `backend/pyproject.toml` | Add opentelemetry dependencies |
| `backend/main.py:1-19,88-127` | Import observability, call init, add request ID middleware, record request attributes |
| `backend/agent.py:1-12,292-347,365-462` | Import tracing, wrap prompt building, instrument `run_agent` and `run_agent_stream` with spans/metrics/SQLite writes |
| `backend/search/orchestrator.py:1-11,104-178` | Import tracing, wrap `search()` and tier blocks with spans |
| `backend/search/semantic.py:1-11,64-128,130-234` | Import tracing, wrap `OllamaEmbeddingFunction.__call__` and `SemanticSearch.query()` |
| `docker-compose.yml` | Add otel-collector, jaeger, prometheus, grafana services |

---

## Task 1: Add OTEL Dependencies

**Files:**
- Modify: `backend/pyproject.toml:7-21`

- [ ] **Step 1: Add opentelemetry packages to pyproject.toml**

```toml
[project]
name = "mkdocs-ai-backend"
version = "0.1.0"
description = "Agentic backend for MkDocs Chatbox Widget"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "fastapi[standard]",
    "uvicorn",
    "langchain",
    "langchain-openai",
    "litellm",
    "langgraph",
    "pyotp",
    "python-jose[cryptography]",
    "passlib[bcrypt]",
    "python-multipart",
    "pydantic-settings",
    "python-dotenv",
    "httpx",
    "opentelemetry-api>=1.25.0",
    "opentelemetry-sdk>=1.25.0",
    "opentelemetry-exporter-otlp>=1.25.0",
    "opentelemetry-instrumentation-fastapi>=0.46b0",
    "opentelemetry-instrumentation-httpx>=0.46b0",
]

[tool.uv]
package = false
```

- [ ] **Step 2: Install dependencies**

Run: `cd backend && uv sync`
Expected: All packages install successfully, no version conflicts.

- [ ] **Step 3: Verify imports work**

Run: `cd backend && python -c "import opentelemetry; from opentelemetry import trace, metrics; from opentelemetry.sdk.trace import TracerProvider; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "build: add opentelemetry dependencies"
```

---

## Task 2: Observability Config Module

**Files:**
- Create: `backend/observability/__init__.py`
- Create: `backend/observability/config.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/test_observability.py`:

```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from observability.config import ObservabilityConfig

# --- TEST: config defaults ---
print("=== TEST 1: ObservabilityConfig defaults ===")
cfg = ObservabilityConfig()
assert cfg.service_name == "mkdocs-agent"
assert cfg.otel_endpoint == "http://localhost:4317"
assert cfg.sqlite_path.endswith("traces.db")
assert cfg.enabled is True
print("PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python test_observability.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'observability'`

- [ ] **Step 3: Write config module**

Create `backend/observability/__init__.py`:

```python
from observability.config import ObservabilityConfig
from observability.tracing import init_observability, get_tracer, get_meter

__all__ = [
    "ObservabilityConfig",
    "init_observability",
    "get_tracer",
    "get_meter",
]
```

Create `backend/observability/config.py`:

```python
"""Observability configuration loaded from environment variables."""

import os
from pydantic_settings import BaseSettings


class ObservabilityConfig(BaseSettings):
    service_name: str = "mkdocs-agent"
    otel_endpoint: str = "http://localhost:4317"
    otel_insecure: bool = True
    sqlite_path: str = os.path.join(os.path.dirname(__file__), "..", "data", "traces.db")
    enabled: bool = True

    class Config:
        env_prefix = "OTEL_"
        env_file = ".env"
        extra = "ignore"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python test_observability.py`
Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add backend/observability/ backend/test_observability.py
git commit -m "feat(observability): add config module with env var support"
```

---

## Task 3: Tracing Module — Tracer Init & `@traced` Decorator

**Files:**
- Create: `backend/observability/tracing.py`
- Modify: `backend/test_observability.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/test_observability.py`:

```python
from observability.tracing import init_observability, get_tracer, get_meter, traced
from opentelemetry import trace

# --- TEST 2: init_observability returns provider ---
print("\n=== TEST 2: init_observability ===")
cfg = ObservabilityConfig(enabled=True, otel_endpoint="http://localhost:4317")
init_observability(cfg)
tracer = get_tracer()
assert tracer is not None
meter = get_meter()
assert meter is not None
print("PASS")

# --- TEST 3: traced decorator creates span ---
print("\n=== TEST 3: traced decorator ===")

@traced("test.operation")
def my_function(x, y):
    return x + y

result = my_function(2, 3)
assert result == 5
print("PASS")

# --- TEST 4: traced decorator records exceptions ---
print("\n=== TEST 4: traced decorator exception handling ===")

@traced("test.failing")
def failing_function():
    raise ValueError("test error")

try:
    failing_function()
    assert False, "Should have raised"
except ValueError as e:
    assert str(e) == "test error"
print("PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python test_observability.py`
Expected: FAIL with `ImportError: cannot import name 'init_observability'`

- [ ] **Step 3: Write tracing module**

Create `backend/observability/tracing.py`:

```python
"""OpenTelemetry tracer and meter initialization, @traced decorator."""

import functools
import logging
from typing import Callable, Optional

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.trace import StatusCode

from observability.config import ObservabilityConfig

logger = logging.getLogger(__name__)

_tracer: Optional[trace.Tracer] = None
_meter: Optional[metrics.Meter] = None
_initialized = False


def init_observability(config: Optional[ObservabilityConfig] = None) -> None:
    """Initialize OpenTelemetry tracing and metrics."""
    global _tracer, _meter, _initialized
    if _initialized:
        return

    config = config or ObservabilityConfig()
    if not config.enabled:
        logger.info("Observability disabled via config")
        _tracer = trace.get_tracer(config.service_name)
        _meter = metrics.get_meter(config.service_name)
        _initialized = True
        return

    resource = Resource.create({SERVICE_NAME: config.service_name})

    # Tracing
    tracer_provider = TracerProvider(resource=resource)
    try:
        span_exporter = OTLPSpanExporter(
            endpoint=config.otel_endpoint,
            insecure=config.otel_insecure,
        )
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    except Exception as e:
        logger.warning("Failed to connect OTLP trace exporter: %s", e)
    trace.set_tracer_provider(tracer_provider)

    # Metrics
    try:
        metric_exporter = OTLPMetricExporter(
            endpoint=config.otel_endpoint,
            insecure=config.otel_insecure,
        )
        metric_reader = PeriodicExportingMetricReader(
            metric_exporter, export_interval_millis=15000,
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    except Exception as e:
        logger.warning("Failed to connect OTLP metric exporter: %s", e)
        meter_provider = MeterProvider(resource=resource)
    metrics.set_meter_provider(meter_provider)

    _tracer = trace.get_tracer(config.service_name)
    _meter = metrics.get_meter(config.service_name)
    _initialized = True
    logger.info("Observability initialized: endpoint=%s", config.otel_endpoint)


def get_tracer() -> trace.Tracer:
    """Return the configured tracer, initializing with defaults if needed."""
    global _tracer
    if _tracer is None:
        init_observability()
    return _tracer


def get_meter() -> metrics.Meter:
    """Return the configured meter, initializing with defaults if needed."""
    global _meter
    if _meter is None:
        init_observability()
    return _meter


def traced(span_name: str, attributes: Optional[dict] = None) -> Callable:
    """Decorator that wraps a function in an OTEL span.

    Automatically records exceptions as span events and sets error status.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, v)
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.set_status(StatusCode.ERROR, str(e))
                    span.record_exception(e)
                    raise
        return wrapper
    return decorator
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python test_observability.py`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/observability/tracing.py backend/test_observability.py
git commit -m "feat(observability): add tracer init and @traced decorator"
```

---

## Task 4: Metrics Definitions

**Files:**
- Create: `backend/observability/metrics.py`
- Modify: `backend/observability/__init__.py`
- Modify: `backend/test_observability.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/test_observability.py`:

```python
from observability.metrics import AgentMetrics

# --- TEST 5: metrics objects created ---
print("\n=== TEST 5: AgentMetrics ===")
m = AgentMetrics()
assert m.requests_total is not None
assert m.llm_calls_total is not None
assert m.tool_calls_total is not None
assert m.tokens_total is not None
assert m.request_duration is not None
assert m.llm_call_duration is not None
assert m.prompt_tokens_hist is not None
print("PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python test_observability.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'observability.metrics'`

- [ ] **Step 3: Write metrics module**

Create `backend/observability/metrics.py`:

```python
"""All Prometheus/OTEL metric definitions for the agent system."""

from observability.tracing import get_meter


class AgentMetrics:
    """Container for all agent observability metrics.

    Instantiate once at startup. Each attribute is a meter instrument.
    """

    def __init__(self) -> None:
        meter = get_meter()

        # --- Counters ---
        self.requests_total = meter.create_counter(
            "agent_requests_total",
            description="Total agent requests",
        )
        self.llm_calls_total = meter.create_counter(
            "agent_llm_calls_total",
            description="Total LLM invocations",
        )
        self.tool_calls_total = meter.create_counter(
            "agent_tool_calls_total",
            description="Total tool invocations",
        )
        self.search_calls_total = meter.create_counter(
            "agent_search_calls_total",
            description="Total search calls by tier",
        )
        self.embedding_calls_total = meter.create_counter(
            "agent_embedding_calls_total",
            description="Total embedding API calls",
        )
        self.tokens_total = meter.create_counter(
            "agent_tokens_total",
            description="Total tokens consumed",
        )
        self.errors_total = meter.create_counter(
            "agent_errors_total",
            description="Total errors by stage",
        )

        # --- Histograms ---
        self.request_duration = meter.create_histogram(
            "agent_request_duration_seconds",
            description="End-to-end request latency",
            unit="s",
        )
        self.llm_call_duration = meter.create_histogram(
            "agent_llm_call_duration_seconds",
            description="Per-LLM-call latency",
            unit="s",
        )
        self.tool_call_duration = meter.create_histogram(
            "agent_tool_call_duration_seconds",
            description="Per-tool-call latency",
            unit="s",
        )
        self.prompt_tokens_hist = meter.create_histogram(
            "agent_prompt_tokens",
            description="Prompt size in estimated tokens",
        )
        self.search_results_hist = meter.create_histogram(
            "agent_search_results_count",
            description="Number of search results returned",
        )
        self.retrieval_chars_hist = meter.create_histogram(
            "agent_retrieval_chars",
            description="Characters of retrieved content injected into prompt",
        )

        # --- Up-Down Counters (gauges) ---
        self.embedding_cache_size = meter.create_up_down_counter(
            "agent_embedding_cache_size",
            description="Current embedding cache entries",
        )
```

Update `backend/observability/__init__.py` to add the export:

```python
from observability.config import ObservabilityConfig
from observability.tracing import init_observability, get_tracer, get_meter, traced
from observability.metrics import AgentMetrics

__all__ = [
    "ObservabilityConfig",
    "init_observability",
    "get_tracer",
    "get_meter",
    "traced",
    "AgentMetrics",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python test_observability.py`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/observability/metrics.py backend/observability/__init__.py backend/test_observability.py
git commit -m "feat(observability): add metric definitions (counters, histograms, gauges)"
```

---

## Task 5: Token Estimation Utilities

**Files:**
- Create: `backend/observability/tokens.py`
- Modify: `backend/test_observability.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/test_observability.py`:

```python
from observability.tokens import estimate_tokens, extract_usage_metadata

# --- TEST 6: estimate_tokens ---
print("\n=== TEST 6: estimate_tokens ===")
assert estimate_tokens("hello world") == 3  # 11 chars / 4 = 2.75 → 3
assert estimate_tokens("") == 0
assert estimate_tokens("a" * 400) == 100  # 400 / 4
print("PASS")

# --- TEST 7: extract_usage_metadata from dict ---
print("\n=== TEST 7: extract_usage_metadata ===")
usage = extract_usage_metadata({"usage_metadata": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}})
assert usage == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}

# Missing usage
usage2 = extract_usage_metadata({})
assert usage2 == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
print("PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python test_observability.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'observability.tokens'`

- [ ] **Step 3: Write tokens module**

Create `backend/observability/tokens.py`:

```python
"""Token counting and estimation utilities."""

import math
from typing import Any


def estimate_tokens(text: str) -> int:
    """Estimate token count from text using chars/4 heuristic.

    This is a rough approximation. For exact counts, use tiktoken,
    but this avoids adding a heavy dependency for observability.
    """
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def extract_usage_metadata(message: Any) -> dict[str, int]:
    """Extract token usage from a LangChain AIMessage or dict.

    LangChain AIMessage objects have a `usage_metadata` attribute when
    the provider returns token counts. Falls back to zeros if unavailable.
    """
    empty = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    if isinstance(message, dict):
        usage = message.get("usage_metadata", {})
    elif hasattr(message, "usage_metadata") and message.usage_metadata:
        usage = message.usage_metadata
    else:
        return empty

    if not isinstance(usage, dict):
        return empty

    return {
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "total_tokens": usage.get("total_tokens", 0) or 0,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python test_observability.py`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/observability/tokens.py backend/test_observability.py
git commit -m "feat(observability): add token estimation utilities"
```

---

## Task 6: SQLite Request Trace Store

**Files:**
- Create: `backend/observability/trace_store.py`
- Modify: `backend/test_observability.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/test_observability.py`:

```python
import tempfile, os
from observability.trace_store import RequestTraceStore

# --- TEST 8: trace store write + read ---
print("\n=== TEST 8: RequestTraceStore ===")
tmp_db = os.path.join(tempfile.mkdtemp(), "test_traces.db")
store = RequestTraceStore(db_path=tmp_db)

store.write(
    request_id="req-001",
    model="gpt-4o",
    query="how does the tool system work",
    status="success",
    total_tokens=1500,
    input_tokens=1200,
    output_tokens=300,
    llm_calls=2,
    tool_calls=3,
    search_calls=1,
    embedding_calls=1,
    prompt_chars=4800,
    retrieval_chars=2000,
    citations_count=2,
    duration_ms=5400,
    tiers_used="lexical,semantic",
    tools_used="search_knowledge_base,read_workspace_file,read_workspace_file",
)

rows = store.query("SELECT * FROM request_traces WHERE id = 'req-001'")
assert len(rows) == 1
row = rows[0]
assert row["model"] == "gpt-4o"
assert row["total_tokens"] == 1500
assert row["llm_calls"] == 2
assert row["tiers_used"] == "lexical,semantic"
print("PASS")

# --- TEST 9: trace store recent ---
print("\n=== TEST 9: trace store recent query ===")
recent = store.recent(limit=5)
assert len(recent) == 1
assert recent[0]["id"] == "req-001"
print("PASS")

os.unlink(tmp_db)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python test_observability.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'observability.trace_store'`

- [ ] **Step 3: Write trace store module**

Create `backend/observability/trace_store.py`:

```python
"""SQLite-backed request trace summary store."""

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS request_traces (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    model TEXT NOT NULL,
    query TEXT NOT NULL,
    status TEXT NOT NULL,
    total_tokens INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    llm_calls INTEGER DEFAULT 0,
    tool_calls INTEGER DEFAULT 0,
    search_calls INTEGER DEFAULT 0,
    embedding_calls INTEGER DEFAULT 0,
    prompt_chars INTEGER DEFAULT 0,
    retrieval_chars INTEGER DEFAULT 0,
    citations_count INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    error_message TEXT DEFAULT '',
    tiers_used TEXT DEFAULT '',
    tools_used TEXT DEFAULT ''
)
"""


class RequestTraceStore:
    """Thread-safe SQLite store for per-request trace summaries."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(CREATE_TABLE_SQL)
                conn.commit()
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def write(
        self,
        request_id: str,
        model: str,
        query: str,
        status: str,
        total_tokens: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        llm_calls: int = 0,
        tool_calls: int = 0,
        search_calls: int = 0,
        embedding_calls: int = 0,
        prompt_chars: int = 0,
        retrieval_chars: int = 0,
        citations_count: int = 0,
        duration_ms: int = 0,
        error_message: str = "",
        tiers_used: str = "",
        tools_used: str = "",
    ) -> None:
        """Write a request trace summary row."""
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO request_traces
                    (id, timestamp, model, query, status, total_tokens, input_tokens,
                     output_tokens, llm_calls, tool_calls, search_calls, embedding_calls,
                     prompt_chars, retrieval_chars, citations_count, duration_ms,
                     error_message, tiers_used, tools_used)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        request_id, timestamp, model, query[:200], status,
                        total_tokens, input_tokens, output_tokens,
                        llm_calls, tool_calls, search_calls, embedding_calls,
                        prompt_chars, retrieval_chars, citations_count, duration_ms,
                        error_message, tiers_used, tools_used,
                    ),
                )
                conn.commit()
            except Exception as e:
                logger.error("Failed to write trace: %s", e)
            finally:
                conn.close()

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Run a read query and return rows as dicts."""
        conn = self._connect()
        try:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def recent(self, limit: int = 20) -> list[dict]:
        """Return the most recent trace summaries."""
        return self.query(
            "SELECT * FROM request_traces ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python test_observability.py`
Expected: All 9 tests PASS.

- [ ] **Step 5: Update `__init__.py` exports**

Add `RequestTraceStore` to `backend/observability/__init__.py`:

```python
from observability.config import ObservabilityConfig
from observability.tracing import init_observability, get_tracer, get_meter, traced
from observability.metrics import AgentMetrics
from observability.tokens import estimate_tokens, extract_usage_metadata
from observability.trace_store import RequestTraceStore

__all__ = [
    "ObservabilityConfig",
    "init_observability",
    "get_tracer",
    "get_meter",
    "traced",
    "AgentMetrics",
    "estimate_tokens",
    "extract_usage_metadata",
    "RequestTraceStore",
]
```

- [ ] **Step 6: Run all tests again**

Run: `cd backend && python test_observability.py`
Expected: All 9 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/observability/ backend/test_observability.py
git commit -m "feat(observability): add SQLite request trace store"
```

---

## Task 7: Instrument FastAPI (`main.py`)

**Files:**
- Modify: `backend/main.py:1-28,88-127`

- [ ] **Step 1: Add observability imports and initialization to main.py**

Add these imports at the top of `backend/main.py` (after existing imports on line 17):

```python
import uuid
from observability import init_observability, ObservabilityConfig, AgentMetrics, RequestTraceStore
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry import trace
```

After the existing `app = FastAPI(...)` line (line 19), add initialization:

```python
# --- Observability ---
obs_config = ObservabilityConfig()
init_observability(obs_config)
agent_metrics = AgentMetrics()
trace_store = RequestTraceStore(db_path=obs_config.sqlite_path)
FastAPIInstrumentor.instrument_app(app)
```

- [ ] **Step 2: Add request ID middleware**

After the CORS middleware block (after line 28), add:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute("request.id", request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

app.add_middleware(RequestIdMiddleware)
```

- [ ] **Step 3: Pass trace_store and agent_metrics to agent functions**

Update the `/chat` endpoint (line 88-100) to pass observability objects. Replace the entire function body:

```python
@app.post("/chat")
def chat_endpoint(request: ChatRequest, current_user: str = Depends(get_current_user)):
    try:
        history_dict = [{"role": msg.role, "content": msg.content} for msg in request.history]
        reply = run_agent(
            query=request.query,
            chat_history=history_dict,
            model_id=request.model,
            page_context=request.page_context,
            agent_metrics=agent_metrics,
            trace_store=trace_store,
        )
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

Update the `/chat/stream` endpoint (line 103-127) similarly:

```python
@app.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest, current_user: str = Depends(get_current_user)):
    """Streaming chat endpoint. Returns newline-delimited JSON events."""
    history_dict = [{"role": msg.role, "content": msg.content} for msg in request.history]

    async def event_generator():
        try:
            async for event in run_agent_stream(
                query=request.query,
                chat_history=history_dict,
                model_id=request.model,
                page_context=request.page_context,
                agent_metrics=agent_metrics,
                trace_store=trace_store,
            ):
                yield json.dumps(event) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "detail": str(e)}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(event_generator(), media_type="text/plain")
```

- [ ] **Step 4: Verify syntax**

Run: `cd backend && python -c "import main; print('OK')"`
Expected: This will fail because `run_agent` doesn't accept `agent_metrics` yet. That's OK — we'll fix it in Task 8.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat(observability): instrument FastAPI with OTEL auto-instrumentation and request ID middleware"
```

---

## Task 8: Instrument Agent Pipeline (`agent.py`)

This is the largest task. It instruments the core agent execution with spans, metrics, and SQLite writes.

**Files:**
- Modify: `backend/agent.py:1-12,365-462`

- [ ] **Step 1: Add observability imports to agent.py**

Replace the imports section (lines 1-12) of `backend/agent.py` with:

```python
import os
import re
import subprocess
import time
import uuid
import warnings
from typing import AsyncGenerator, Literal, Optional

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from opentelemetry import trace
from pydantic_settings import BaseSettings

from observability import (
    get_tracer,
    AgentMetrics,
    RequestTraceStore,
    estimate_tokens,
    extract_usage_metadata,
)

warnings.filterwarnings("ignore", category=UserWarning, module="langgraph")
from langgraph.prebuilt import create_react_agent  # noqa: E402
```

- [ ] **Step 2: Instrument `build_system_prompt` to return size metadata**

Replace the `build_system_prompt` function (lines 292-347) to also return a size measurement. Instead of modifying the function signature (which would break callers), add a helper:

```python
def _measure_prompt(system_prompt: str, history: list, query: str) -> dict:
    """Measure prompt assembly sizes for observability."""
    history_chars = sum(len(content) for _, content in history)
    return {
        "system_prompt_chars": len(system_prompt),
        "history_turns": len(history),
        "history_chars": history_chars,
        "query_chars": len(query),
        "total_chars": len(system_prompt) + history_chars + len(query),
    }
```

Add this function right after `build_system_prompt` (after line 347).

- [ ] **Step 3: Instrument `run_agent` (blocking version)**

Replace the `run_agent` function (lines 365-383) with the instrumented version:

```python
def run_agent(
    query: str,
    chat_history: list,
    model_id: str = "deepseek",
    page_context: Optional[dict] = None,
    agent_metrics: Optional[AgentMetrics] = None,
    trace_store: Optional[RequestTraceStore] = None,
) -> str:
    """Blocking agent execution (kept for backward compatibility with /chat endpoint)."""
    tracer = get_tracer()
    request_id = str(uuid.uuid4())
    start_time = time.time()

    with tracer.start_as_current_span("agent.react_loop") as span:
        span.set_attribute("request.id", request_id)
        span.set_attribute("request.model", model_id)
        span.set_attribute("request.query", query[:200])

        llm = get_chat_model(model_id)
        agent = create_react_agent(llm, tools=tools)

        system_prompt = build_system_prompt(page_context)
        history = _format_history(chat_history)
        messages = [("system", system_prompt)]
        messages.extend(history)
        messages.append(("user", query))

        prompt_info = _measure_prompt(system_prompt, history, query)
        span.set_attribute("prompt.total_chars", prompt_info["total_chars"])
        span.set_attribute("prompt.history_turns", prompt_info["history_turns"])
        span.set_attribute("prompt.system_prompt_chars", prompt_info["system_prompt_chars"])

        try:
            response = agent.invoke({"messages": messages})
            reply = response["messages"][-1].content
            duration_ms = int((time.time() - start_time) * 1000)

            # Extract token usage from the last AI message
            last_msg = response["messages"][-1]
            usage = extract_usage_metadata(last_msg)

            span.set_attribute("llm.total_tokens", usage["total_tokens"])
            span.set_attribute("agent.duration_ms", duration_ms)

            if agent_metrics:
                agent_metrics.requests_total.add(1, {"model": model_id, "status": "success"})
                agent_metrics.request_duration.record(duration_ms / 1000, {"model": model_id})
                if usage["total_tokens"]:
                    agent_metrics.tokens_total.add(usage["input_tokens"], {"model": model_id, "direction": "input"})
                    agent_metrics.tokens_total.add(usage["output_tokens"], {"model": model_id, "direction": "output"})

            if trace_store:
                trace_store.write(
                    request_id=request_id,
                    model=model_id,
                    query=query,
                    status="success",
                    total_tokens=usage["total_tokens"],
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    prompt_chars=prompt_info["total_chars"],
                    duration_ms=duration_ms,
                )

            return reply
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            span.set_status(trace.StatusCode.ERROR, str(e))
            span.record_exception(e)
            if agent_metrics:
                agent_metrics.requests_total.add(1, {"model": model_id, "status": "error"})
                agent_metrics.errors_total.add(1, {"stage": "agent", "error_type": type(e).__name__})
            if trace_store:
                trace_store.write(
                    request_id=request_id, model=model_id, query=query, status="error",
                    duration_ms=duration_ms, error_message=str(e)[:500],
                )
            return f"Agent execution failed: {e}"
```

- [ ] **Step 4: Instrument `run_agent_stream` (streaming version)**

Replace the `run_agent_stream` function (lines 386-462) with the fully instrumented version:

```python
async def run_agent_stream(
    query: str,
    chat_history: list,
    model_id: str = "deepseek",
    page_context: Optional[dict] = None,
    agent_metrics: Optional[AgentMetrics] = None,
    trace_store: Optional[RequestTraceStore] = None,
) -> AsyncGenerator[dict, None]:
    """Streaming agent execution with full observability."""
    tracer = get_tracer()
    request_id = str(uuid.uuid4())
    start_time = time.time()

    # Accumulators for trace summary
    total_input_tokens = 0
    total_output_tokens = 0
    llm_call_count = 0
    tool_call_count = 0
    search_call_count = 0
    tools_used: list[str] = []
    retrieval_chars = 0

    with tracer.start_as_current_span("agent.react_loop") as root_span:
        root_span.set_attribute("request.id", request_id)
        root_span.set_attribute("request.model", model_id)
        root_span.set_attribute("request.query", query[:200])

        llm = get_chat_model(model_id)
        agent = create_react_agent(llm, tools=tools)

        system_prompt = build_system_prompt(page_context)
        history = _format_history(chat_history)
        messages = [("system", system_prompt)]
        messages.extend(history)
        messages.append(("user", query))

        prompt_info = _measure_prompt(system_prompt, history, query)
        root_span.set_attribute("prompt.total_chars", prompt_info["total_chars"])
        root_span.set_attribute("prompt.history_turns", prompt_info["history_turns"])
        root_span.set_attribute("prompt.system_prompt_chars", prompt_info["system_prompt_chars"])

        cited_files: set[str] = set()
        active_tool_spans: dict[str, trace.Span] = {}
        tool_start_times: dict[str, float] = {}

        try:
            async for event in agent.astream_events({"messages": messages}, version="v2"):
                event_type = event["event"]

                if event_type == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    content = chunk.content if hasattr(chunk, "content") else ""
                    if isinstance(content, str) and content:
                        yield {"type": "token", "content": content}

                    # Check for usage metadata on stream end
                    if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                        usage = chunk.usage_metadata
                        total_input_tokens += usage.get("input_tokens", 0) or 0
                        total_output_tokens += usage.get("output_tokens", 0) or 0

                elif event_type == "on_chat_model_start":
                    llm_call_count += 1
                    if agent_metrics:
                        agent_metrics.llm_calls_total.add(1, {"model": model_id, "iteration": str(llm_call_count)})

                elif event_type == "on_tool_start":
                    tool_name = event["name"]
                    tool_input = event["data"].get("input", {})
                    run_id = event.get("run_id", tool_name)

                    tool_call_count += 1
                    tools_used.append(tool_name)

                    # Create a child span for this tool call
                    tool_span = tracer.start_span(
                        f"tool.{tool_name}",
                        attributes={
                            "tool.name": tool_name,
                            "tool.input": str(tool_input)[:500],
                        },
                    )
                    active_tool_spans[run_id] = tool_span
                    tool_start_times[run_id] = time.time()

                    if tool_name in ("search_knowledge_base", "smart_search", "find_symbol"):
                        search_call_count += 1

                    yield {"type": "tool_call", "name": tool_name, "input": str(tool_input)[:200]}

                    if tool_name == "read_workspace_file" and isinstance(tool_input, dict):
                        path = tool_input.get("file_path", "").strip().lstrip("/")
                        if path:
                            cited_files.add(path)
                    elif tool_name == "read_source_file" and isinstance(tool_input, dict):
                        ns = tool_input.get("namespace", "")
                        path = tool_input.get("file_path", "").strip().lstrip("/")
                        if ns and path and ns in SOURCE_ROOTS:
                            cited_files.add(f"{SOURCE_ROOTS[ns]}/{path}")

                elif event_type == "on_tool_end":
                    tool_name = event["name"]
                    output = event["data"].get("output", "")
                    run_id = event.get("run_id", tool_name)

                    output_size = len(output) if isinstance(output, str) else 0
                    retrieval_chars += output_size

                    # Close the tool span
                    tool_span = active_tool_spans.pop(run_id, None)
                    if tool_span:
                        tool_duration = time.time() - tool_start_times.pop(run_id, time.time())
                        tool_span.set_attribute("tool.output_size", output_size)
                        tool_span.set_attribute("tool.status", "success")
                        tool_span.end()
                        if agent_metrics:
                            agent_metrics.tool_calls_total.add(1, {"tool_name": tool_name, "status": "success"})
                            agent_metrics.tool_call_duration.record(tool_duration, {"tool_name": tool_name})

                    if tool_name == "search_knowledge_base" and isinstance(output, str):
                        for line in output.splitlines():
                            m = re.match(r"^(docs/[\w/\-]+\.md):", line)
                            if m:
                                cited_files.add(m.group(1))

                    elif tool_name == "propose_doc_change" and isinstance(output, str):
                        pid_match = re.search(r"Proposal ID: `(\w+)`", output)
                        if pid_match:
                            from proposals import proposal_store as _ps
                            pid = pid_match.group(1)
                            prop = _ps.get(pid)
                            if prop:
                                yield {
                                    "type": "proposal",
                                    "proposal_id": pid,
                                    "summary": prop.summary,
                                    "commit_message": prop.commit_message,
                                    "files": [
                                        {"path": f.path, "diff": f.diff}
                                        for f in prop.files
                                    ],
                                }

            # --- Request complete: record summary ---
            duration_ms = int((time.time() - start_time) * 1000)
            total_tokens = total_input_tokens + total_output_tokens

            # If no usage metadata was available, estimate from prompt size
            if total_tokens == 0:
                total_input_tokens = estimate_tokens(
                    system_prompt + query + "".join(c for _, c in history)
                )
                total_tokens = total_input_tokens

            root_span.set_attribute("agent.total_tokens", total_tokens)
            root_span.set_attribute("agent.input_tokens", total_input_tokens)
            root_span.set_attribute("agent.output_tokens", total_output_tokens)
            root_span.set_attribute("agent.llm_calls", llm_call_count)
            root_span.set_attribute("agent.tool_calls", tool_call_count)
            root_span.set_attribute("agent.search_calls", search_call_count)
            root_span.set_attribute("agent.retrieval_chars", retrieval_chars)
            root_span.set_attribute("agent.citations_count", len(cited_files))
            root_span.set_attribute("agent.duration_ms", duration_ms)

            if agent_metrics:
                agent_metrics.requests_total.add(1, {"model": model_id, "status": "success"})
                agent_metrics.request_duration.record(duration_ms / 1000, {"model": model_id})
                agent_metrics.tokens_total.add(total_input_tokens, {"model": model_id, "direction": "input"})
                agent_metrics.tokens_total.add(total_output_tokens, {"model": model_id, "direction": "output"})
                agent_metrics.prompt_tokens_hist.record(prompt_info["total_chars"] // 4, {"model": model_id})
                agent_metrics.retrieval_chars_hist.record(retrieval_chars)

            if trace_store:
                trace_store.write(
                    request_id=request_id,
                    model=model_id,
                    query=query,
                    status="success",
                    total_tokens=total_tokens,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    llm_calls=llm_call_count,
                    tool_calls=tool_call_count,
                    search_calls=search_call_count,
                    prompt_chars=prompt_info["total_chars"],
                    retrieval_chars=retrieval_chars,
                    citations_count=len(cited_files),
                    duration_ms=duration_ms,
                    tools_used=",".join(tools_used),
                )

            if cited_files:
                yield {"type": "citations", "sources": sorted(cited_files)}
            yield {"type": "done"}

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            root_span.set_status(trace.StatusCode.ERROR, str(e))
            root_span.record_exception(e)

            # Clean up any open tool spans
            for span_obj in active_tool_spans.values():
                span_obj.set_attribute("tool.status", "error")
                span_obj.end()

            if agent_metrics:
                agent_metrics.requests_total.add(1, {"model": model_id, "status": "error"})
                agent_metrics.errors_total.add(1, {"stage": "agent", "error_type": type(e).__name__})

            if trace_store:
                trace_store.write(
                    request_id=request_id, model=model_id, query=query, status="error",
                    llm_calls=llm_call_count, tool_calls=tool_call_count,
                    duration_ms=duration_ms, error_message=str(e)[:500],
                )

            yield {"type": "error", "detail": str(e)}
            yield {"type": "done"}
```

- [ ] **Step 5: Verify syntax compiles**

Run: `cd backend && python -c "import agent; print('OK')"`
Expected: `OK` (or a warning about missing env vars, which is fine)

- [ ] **Step 6: Commit**

```bash
git add backend/agent.py
git commit -m "feat(observability): instrument agent pipeline with spans, metrics, and SQLite traces"
```

---

## Task 9: Instrument Search Orchestrator

**Files:**
- Modify: `backend/search/orchestrator.py:1-11,104-178`

- [ ] **Step 1: Add tracing imports**

Replace the imports block (lines 1-11) of `backend/search/orchestrator.py`:

```python
"""Search orchestrator: repo targeting, tier escalation, result ranking."""

import logging
import re
import time
from typing import Optional

from opentelemetry import trace

from observability import get_tracer, AgentMetrics
from search.lexical import LexicalSearch
from search.registry import RepoMeta, RepoRegistry, repo_registry
from search.semantic import SemanticSearch

logger = logging.getLogger(__name__)
```

- [ ] **Step 2: Instrument the `search()` method**

Replace the `search()` method body (lines 104-178) with the traced version. The key changes are: wrap in a span, record tier usage, cache hits, and result counts.

```python
    def search(
        self,
        query: str,
        scope: str = "auto",
        page_url: str = "",
        max_results: int = 0,
    ) -> str:
        """Run a multi-tier search with early stopping."""
        if not query.strip():
            return "No results found."

        max_results = max_results or self._max_results
        tracer = get_tracer()

        with tracer.start_as_current_span("search.orchestrator") as span:
            span.set_attribute("search.query", query[:200])
            span.set_attribute("search.scope", scope)

            cache_key = f"{query}:{scope}"
            if cache_key in self._session_cache:
                logger.debug("Search cache hit for: %s", query[:50])
                span.set_attribute("search.cache_hit", True)
                return self._session_cache[cache_key]

            span.set_attribute("search.cache_hit", False)

            namespace = scope if scope not in ("auto", "wiki", "code") else ""
            targets = self.registry.target(query, page_url=page_url, namespace=namespace)
            query_type = classify_query(query)
            span.set_attribute("search.query_type", query_type)

            all_results: list[dict] = []
            tiers_used: list[str] = []

            if scope == "wiki":
                search_paths = [r.wiki_dir for r in targets]
            elif scope == "code":
                search_paths = [r.source_dir for r in targets]
            elif namespace:
                t = targets[0] if targets else None
                search_paths = [t.wiki_dir, t.source_dir] if t else ["docs/"]
            else:
                search_paths = []
                for t in targets[:3]:
                    search_paths.extend([t.wiki_dir, t.source_dir])

            # --- Tier 1: Lexical ---
            with tracer.start_as_current_span("search.lexical") as lex_span:
                t0 = time.time()
                if query_type in ("symbol", "exact"):
                    lexical_results = self.lexical.search(query, search_paths=search_paths, max_results=max_results)
                else:
                    lexical_results = self.lexical.search(query, search_paths=search_paths, max_results=5)
                lex_span.set_attribute("search.results_count", len(lexical_results))
                lex_span.set_attribute("search.duration_ms", int((time.time() - t0) * 1000))
            all_results.extend(lexical_results)
            tiers_used.append("lexical")

            # Early stopping
            distinct_files = len({r.get("file_path", "") for r in all_results})
            high_confidence = len(all_results) >= 5 and distinct_files >= 2

            # --- Tier 2: Semantic ---
            if self._ready and not high_confidence and (query_type == "concept" or len(all_results) < 3):
                with tracer.start_as_current_span("search.semantic") as sem_span:
                    t0 = time.time()
                    semantic_results = self._semantic_search(query, scope, targets, max_results)
                    sem_span.set_attribute("search.results_count", len(semantic_results))
                    sem_span.set_attribute("search.duration_ms", int((time.time() - t0) * 1000))
                all_results.extend(semantic_results)
                tiers_used.append("semantic")
            elif high_confidence:
                span.set_attribute("search.early_stopped", True)

            # --- Tier 3: Symbol ---
            if self._ready and query_type == "symbol" and len(all_results) < 3:
                with tracer.start_as_current_span("search.symbol") as sym_span:
                    t0 = time.time()
                    symbol_results = self.semantic.query("symbols", query, n_results=5)
                    sym_span.set_attribute("search.results_count", len(symbol_results))
                    sym_span.set_attribute("search.duration_ms", int((time.time() - t0) * 1000))
                all_results.extend(symbol_results)
                tiers_used.append("symbol")

            span.set_attribute("search.tiers_used", ",".join(tiers_used))
            span.set_attribute("search.total_raw_results", len(all_results))
            logger.info("Search '%s' → tiers: %s, raw results: %d", query[:40], tiers_used, len(all_results))

            seen: set[str] = set()
            unique: list[dict] = []
            for r in all_results:
                key = f"{r.get('file_path', '')}:{r.get('line_number', r.get('start_line', ''))}"
                if key not in seen:
                    seen.add(key)
                    unique.append(r)

            unique.sort(key=lambda r: r.get("score", 0), reverse=True)
            final_count = min(len(unique), max_results)
            span.set_attribute("search.final_results_count", final_count)

            result = format_results(unique[:max_results], max_chars=self._max_chars, result_max_chars=self._result_max_chars)
            self._session_cache[cache_key] = result
            return result
```

- [ ] **Step 3: Run existing orchestrator tests**

Run: `cd backend && python search/test_orchestrator.py`
Expected: All orchestrator tests PASS (the tracing spans are created but harmlessly no-op without a configured exporter).

- [ ] **Step 4: Commit**

```bash
git add backend/search/orchestrator.py
git commit -m "feat(observability): instrument search orchestrator with per-tier spans"
```

---

## Task 10: Instrument Semantic Search & Embeddings

**Files:**
- Modify: `backend/search/semantic.py:1-11,64-128,183-234`

- [ ] **Step 1: Add tracing imports**

Replace the imports block (lines 1-11) of `backend/search/semantic.py`:

```python
"""Semantic search using ChromaDB and local Ollama embeddings."""

import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any

import chromadb
import httpx
from opentelemetry import trace

from observability import get_tracer

logger = logging.getLogger(__name__)
```

- [ ] **Step 2: Instrument `OllamaEmbeddingFunction.__call__`**

Replace the `__call__` method (lines 76-116) with the traced version:

```python
    def __call__(self, input: list[str]) -> list[list[float]]:
        if not input:
            return []

        tracer = get_tracer()
        with tracer.start_as_current_span("embedding.ollama") as span:
            span.set_attribute("embedding.model", self._model)
            span.set_attribute("embedding.texts_count", len(input))

            results: list[tuple[int, list[float]]] = []
            uncached: list[tuple[int, str]] = []

            for idx, text in enumerate(input):
                cached = self._cache.get(self._model, text)
                if cached is not None:
                    results.append((idx, cached))
                else:
                    uncached.append((idx, text))

            cache_hits = len(input) - len(uncached)
            span.set_attribute("embedding.cache_hits", cache_hits)
            span.set_attribute("embedding.cache_misses", len(uncached))

            if uncached:
                batch_count = 0
                for batch_start in range(0, len(uncached), BATCH_SIZE):
                    batch = uncached[batch_start:batch_start + BATCH_SIZE]
                    batch_texts = [t for _, t in batch]
                    batch_count += 1
                    try:
                        t0 = time.time()
                        resp = httpx.post(
                            f"{self._base_url}/api/embed",
                            json={"model": self._model, "input": batch_texts},
                            timeout=120,
                        )
                        resp.raise_for_status()
                        span.set_attribute("embedding.api_latency_ms", int((time.time() - t0) * 1000))
                    except httpx.ConnectError:
                        logger.warning(
                            "Ollama not reachable at %s — returning empty embeddings",
                            self._base_url,
                        )
                        span.set_attribute("embedding.error", "connection_error")
                        return []

                    data = resp.json()
                    embeddings = data["embeddings"]
                    for i, (orig_idx, text) in enumerate(batch):
                        emb = embeddings[i]
                        self._cache.put(self._model, text, emb)
                        results.append((orig_idx, emb))

                span.set_attribute("embedding.batch_count", batch_count)

            results.sort(key=lambda x: x[0])
            return [emb for _, emb in results]
```

- [ ] **Step 3: Instrument `SemanticSearch.query()`**

Replace the `query` method (lines 183-234) with the traced version:

```python
    def query(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 10,
        where: dict | None = None,
    ) -> list[dict]:
        if not query_text.strip():
            return []

        tracer = get_tracer()
        with tracer.start_as_current_span("search.semantic.query") as span:
            span.set_attribute("search.collection", collection_name)
            span.set_attribute("search.n_results_requested", n_results)

            try:
                collection = self._client.get_collection(
                    name=collection_name,
                    embedding_function=self._embed_fn,
                )
            except Exception:
                span.set_attribute("search.collection_found", False)
                return []

            count = collection.count()
            if count == 0:
                span.set_attribute("search.collection_count", 0)
                return []

            span.set_attribute("search.collection_count", count)

            kwargs: dict[str, Any] = {
                "query_texts": [query_text],
                "n_results": min(n_results, count),
            }
            if where:
                kwargs["where"] = where

            try:
                t0 = time.time()
                results = collection.query(**kwargs)
                span.set_attribute("search.query_latency_ms", int((time.time() - t0) * 1000))
            except Exception as e:
                logger.warning("Semantic query failed: %s", e)
                span.set_attribute("search.error", str(e)[:200])
                return []

            if not results or not results["documents"] or not results["documents"][0]:
                span.set_attribute("search.results_count", 0)
                return []

            output: list[dict] = []
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else 1.0
                output.append({
                    "text": doc,
                    "file_path": meta.get("file_path", ""),
                    "section": meta.get("section", ""),
                    "symbol": meta.get("symbol", ""),
                    "score": round(1.0 - distance, 4),
                    **{k: v for k, v in meta.items() if k not in ("file_path", "section", "symbol")},
                })

            span.set_attribute("search.results_count", len(output))
            return output
```

- [ ] **Step 4: Run existing semantic search tests**

Run: `cd backend && python search/test_semantic.py`
Expected: Tests 1-2 PASS (Tests 3-5 may skip if Ollama is not running — that's expected).

- [ ] **Step 5: Commit**

```bash
git add backend/search/semantic.py
git commit -m "feat(observability): instrument embeddings and semantic search with spans"
```

---

## Task 11: Docker Compose Infrastructure

**Files:**
- Create: `backend/otel-collector-config.yaml`
- Create: `backend/prometheus.yml`
- Create: `backend/grafana/provisioning/datasources/datasources.yaml`
- Create: `backend/grafana/provisioning/dashboards/dashboards.yaml`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Create OTEL Collector config**

Create `backend/otel-collector-config.yaml`:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 5s
    send_batch_size: 1024

exporters:
  otlp/jaeger:
    endpoint: jaeger:4317
    tls:
      insecure: true

  prometheus:
    endpoint: 0.0.0.0:8889
    namespace: ""
    resource_to_telemetry_conversion:
      enabled: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/jaeger]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheus]
```

- [ ] **Step 2: Create Prometheus config**

Create `backend/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "otel-collector"
    static_configs:
      - targets: ["otel-collector:8889"]
```

- [ ] **Step 3: Create Grafana provisioning configs**

Create `backend/grafana/provisioning/datasources/datasources.yaml`:

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: true

  - name: Jaeger
    type: jaeger
    access: proxy
    url: http://jaeger:16686
    editable: true
```

Create `backend/grafana/provisioning/dashboards/dashboards.yaml`:

```yaml
apiVersion: 1

providers:
  - name: "Agent Observability"
    orgId: 1
    folder: "Agent"
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: false
```

- [ ] **Step 4: Update docker-compose.yml**

Replace the entire `docker-compose.yml` with the expanded version adding observability services:

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8001:8001"
    env_file:
      - backend/.env
    volumes:
      - ./docs:/workspace/docs
      - ${PUBLISH_REPO_DIR:-~/Projects/LLM_Knowledge_Base}:/publish-repo
      - ./deepagents:/workspace/deepagents
      - ./autogen:/workspace/autogen
      - ./opencode:/workspace/opencode
      - ./openclaw:/workspace/openclaw
      - ./hermes-agent:/workspace/hermes-agent
      - ./claude_code:/workspace/claude_code
    environment:
      - PUBLISH_REPO_DIR=/publish-repo
      - OTEL_OTEL_ENDPOINT=http://otel-collector:4317
      - OTEL_ENABLED=true
    depends_on:
      - otel-collector
    restart: unless-stopped

  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.100.0
    command: ["--config=/etc/otel-collector-config.yaml"]
    volumes:
      - ./backend/otel-collector-config.yaml:/etc/otel-collector-config.yaml:ro
    ports:
      - "4317:4317"   # OTLP gRPC
      - "4318:4318"   # OTLP HTTP
      - "8889:8889"   # Prometheus metrics
    depends_on:
      - jaeger
    restart: unless-stopped

  jaeger:
    image: jaegertracing/all-in-one:1.57
    ports:
      - "16686:16686"  # Jaeger UI
      - "14250:14250"  # gRPC
    environment:
      - COLLECTOR_OTLP_ENABLED=true
    restart: unless-stopped

  prometheus:
    image: prom/prometheus:v2.52.0
    volumes:
      - ./backend/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"
    depends_on:
      - otel-collector
    restart: unless-stopped

  grafana:
    image: grafana/grafana:10.4.2
    volumes:
      - ./backend/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./backend/grafana/dashboards:/var/lib/grafana/dashboards:ro
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_AUTH_ANONYMOUS_ENABLED=true
      - GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer
    depends_on:
      - prometheus
      - jaeger
    restart: unless-stopped
```

- [ ] **Step 5: Commit**

```bash
git add backend/otel-collector-config.yaml backend/prometheus.yml backend/grafana/ docker-compose.yml
git commit -m "infra: add OTEL collector, Jaeger, Prometheus, and Grafana to docker-compose"
```

---

## Task 12: Grafana Dashboard JSON Files

**Files:**
- Create: `backend/grafana/dashboards/agent-overview.json`
- Create: `backend/grafana/dashboards/token-deep-dive.json`
- Create: `backend/grafana/dashboards/search-retrieval.json`

- [ ] **Step 1: Create Agent Overview dashboard**

Create `backend/grafana/dashboards/agent-overview.json`:

```json
{
  "dashboard": {
    "id": null,
    "uid": "agent-overview",
    "title": "Agent Overview",
    "tags": ["agent", "observability"],
    "timezone": "browser",
    "refresh": "30s",
    "panels": [
      {
        "id": 1,
        "title": "Requests / Hour",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
        "targets": [{"expr": "sum(rate(agent_requests_total[1h]))", "legendFormat": "requests/hr"}],
        "datasource": {"type": "prometheus", "uid": "prometheus"}
      },
      {
        "id": 2,
        "title": "Median Latency (s)",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
        "targets": [{"expr": "histogram_quantile(0.5, sum(rate(agent_request_duration_seconds_bucket[5m])) by (le))", "legendFormat": "p50"}],
        "datasource": {"type": "prometheus", "uid": "prometheus"}
      },
      {
        "id": 3,
        "title": "P95 Latency (s)",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
        "targets": [{"expr": "histogram_quantile(0.95, sum(rate(agent_request_duration_seconds_bucket[5m])) by (le))", "legendFormat": "p95"}],
        "datasource": {"type": "prometheus", "uid": "prometheus"}
      },
      {
        "id": 4,
        "title": "Tokens / Hour",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
        "targets": [
          {"expr": "sum(rate(agent_tokens_total{direction=\"input\"}[1h]))", "legendFormat": "input"},
          {"expr": "sum(rate(agent_tokens_total{direction=\"output\"}[1h]))", "legendFormat": "output"}
        ],
        "datasource": {"type": "prometheus", "uid": "prometheus"}
      },
      {
        "id": 5,
        "title": "Error Rate / Hour",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 16},
        "targets": [{"expr": "sum(rate(agent_errors_total[1h])) by (stage)", "legendFormat": "{{stage}}"}],
        "datasource": {"type": "prometheus", "uid": "prometheus"}
      },
      {
        "id": 6,
        "title": "Model Usage",
        "type": "piechart",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 16},
        "targets": [{"expr": "sum(agent_requests_total) by (model)", "legendFormat": "{{model}}"}],
        "datasource": {"type": "prometheus", "uid": "prometheus"}
      }
    ]
  }
}
```

- [ ] **Step 2: Create Token Deep-Dive dashboard**

Create `backend/grafana/dashboards/token-deep-dive.json`:

```json
{
  "dashboard": {
    "id": null,
    "uid": "token-deep-dive",
    "title": "Token Deep-Dive",
    "tags": ["agent", "tokens"],
    "timezone": "browser",
    "refresh": "30s",
    "panels": [
      {
        "id": 1,
        "title": "Input vs Output Tokens",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
        "targets": [
          {"expr": "sum(agent_tokens_total{direction=\"input\"})", "legendFormat": "input"},
          {"expr": "sum(agent_tokens_total{direction=\"output\"})", "legendFormat": "output"}
        ],
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "fieldConfig": {"defaults": {"custom": {"stacking": {"mode": "normal"}}}}
      },
      {
        "id": 2,
        "title": "Prompt Size Distribution",
        "type": "heatmap",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
        "targets": [{"expr": "sum(rate(agent_prompt_tokens_bucket[5m])) by (le)", "format": "heatmap"}],
        "datasource": {"type": "prometheus", "uid": "prometheus"}
      },
      {
        "id": 3,
        "title": "Tokens by Model",
        "type": "table",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
        "targets": [{"expr": "sum(agent_tokens_total) by (model, direction)", "format": "table", "instant": true}],
        "datasource": {"type": "prometheus", "uid": "prometheus"}
      },
      {
        "id": 4,
        "title": "LLM Calls per Request (avg)",
        "type": "stat",
        "gridPos": {"h": 8, "w": 6, "x": 12, "y": 8},
        "targets": [{"expr": "sum(agent_llm_calls_total) / sum(agent_requests_total)", "legendFormat": "avg calls"}],
        "datasource": {"type": "prometheus", "uid": "prometheus"}
      },
      {
        "id": 5,
        "title": "Avg Tokens per Request",
        "type": "stat",
        "gridPos": {"h": 8, "w": 6, "x": 18, "y": 8},
        "targets": [{"expr": "sum(agent_tokens_total) / sum(agent_requests_total)", "legendFormat": "avg tokens"}],
        "datasource": {"type": "prometheus", "uid": "prometheus"}
      }
    ]
  }
}
```

- [ ] **Step 3: Create Search & Retrieval dashboard**

Create `backend/grafana/dashboards/search-retrieval.json`:

```json
{
  "dashboard": {
    "id": null,
    "uid": "search-retrieval",
    "title": "Search & Retrieval",
    "tags": ["agent", "search"],
    "timezone": "browser",
    "refresh": "30s",
    "panels": [
      {
        "id": 1,
        "title": "Search Tier Usage",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
        "targets": [{"expr": "sum(agent_search_calls_total) by (tier)", "legendFormat": "{{tier}}"}],
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "fieldConfig": {"defaults": {"custom": {"stacking": {"mode": "normal"}}}}
      },
      {
        "id": 2,
        "title": "Embedding Cache Hit Ratio",
        "type": "gauge",
        "gridPos": {"h": 8, "w": 6, "x": 12, "y": 0},
        "targets": [{"expr": "sum(agent_embedding_calls_total{cache_hit=\"true\"}) / sum(agent_embedding_calls_total) * 100", "legendFormat": "hit %"}],
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "fieldConfig": {"defaults": {"min": 0, "max": 100, "unit": "percent"}}
      },
      {
        "id": 3,
        "title": "Avg Search Results",
        "type": "stat",
        "gridPos": {"h": 8, "w": 6, "x": 18, "y": 0},
        "targets": [{"expr": "avg(agent_search_results_count_sum / agent_search_results_count_count)", "legendFormat": "avg results"}],
        "datasource": {"type": "prometheus", "uid": "prometheus"}
      },
      {
        "id": 4,
        "title": "Retrieval Context Size (chars)",
        "type": "heatmap",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
        "targets": [{"expr": "sum(rate(agent_retrieval_chars_bucket[5m])) by (le)", "format": "heatmap"}],
        "datasource": {"type": "prometheus", "uid": "prometheus"}
      },
      {
        "id": 5,
        "title": "Tool Call Frequency",
        "type": "bargauge",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
        "targets": [{"expr": "sum(agent_tool_calls_total) by (tool_name)", "legendFormat": "{{tool_name}}"}],
        "datasource": {"type": "prometheus", "uid": "prometheus"}
      }
    ]
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add backend/grafana/dashboards/
git commit -m "feat(observability): add pre-provisioned Grafana dashboard definitions"
```

---

## Task 13: Integration Verification

**Files:**
- Modify: `backend/test_observability.py` (add final integration tests)

- [ ] **Step 1: Add integration tests to test_observability.py**

Append to `backend/test_observability.py`:

```python
# --- TEST 10: Full observability init + metrics + store integration ---
print("\n=== TEST 10: Integration: init → metrics → store ===")
from observability import init_observability, ObservabilityConfig, AgentMetrics, RequestTraceStore

cfg = ObservabilityConfig(enabled=True, otel_endpoint="http://localhost:4317")
init_observability(cfg)

m = AgentMetrics()
m.requests_total.add(1, {"model": "gpt-4o", "status": "success"})
m.tokens_total.add(500, {"model": "gpt-4o", "direction": "input"})
m.tokens_total.add(100, {"model": "gpt-4o", "direction": "output"})
m.request_duration.record(2.5, {"model": "gpt-4o"})
m.llm_calls_total.add(1, {"model": "gpt-4o", "iteration": "1"})
m.tool_calls_total.add(1, {"tool_name": "search_knowledge_base", "status": "success"})
print("Metrics recorded OK")

tmp_db2 = os.path.join(tempfile.mkdtemp(), "integration_traces.db")
store = RequestTraceStore(db_path=tmp_db2)
store.write(
    request_id="int-001", model="gpt-4o", query="test integration",
    status="success", total_tokens=600, input_tokens=500, output_tokens=100,
    llm_calls=1, tool_calls=1, search_calls=1, prompt_chars=2000,
    duration_ms=2500, tools_used="search_knowledge_base",
)
rows = store.recent(limit=1)
assert len(rows) == 1
assert rows[0]["total_tokens"] == 600
os.unlink(tmp_db2)
print("PASS")

print("\n✅ All observability tests passed.")
```

- [ ] **Step 2: Run all observability tests**

Run: `cd backend && python test_observability.py`
Expected: All 10 tests PASS, ending with `✅ All observability tests passed.`

- [ ] **Step 3: Run existing backend tests to verify no regressions**

Run: `cd backend && python search/test_orchestrator.py && python search/test_semantic.py && python search/test_lexical.py`
Expected: All existing tests PASS.

- [ ] **Step 4: Verify Python imports for all modified files**

Run: `cd backend && python -c "import main; print('main OK')" && python -c "import agent; print('agent OK')" && python -c "from search.orchestrator import SearchOrchestrator; print('orchestrator OK')" && python -c "from search.semantic import SemanticSearch; print('semantic OK')"`
Expected: All print `OK`.

- [ ] **Step 5: Commit**

```bash
git add backend/test_observability.py
git commit -m "test(observability): add integration tests for full observability stack"
```

---

## Task 14: Final Validation & Docker Compose Test

- [ ] **Step 1: Validate docker-compose config**

Run: `cd /Users/weiqiangyu/Downloads/wiki && docker compose config --quiet`
Expected: Exit code 0, no errors.

- [ ] **Step 2: Verify all new files exist**

Run: `ls -la backend/observability/*.py backend/otel-collector-config.yaml backend/prometheus.yml backend/grafana/provisioning/datasources/datasources.yaml backend/grafana/provisioning/dashboards/dashboards.yaml backend/grafana/dashboards/*.json`
Expected: All 12+ files listed.

- [ ] **Step 3: Final commit with summary**

Run:
```bash
git add -A
git status
```
Expected: Clean working tree, all changes committed.

If anything is unstaged:
```bash
git add -A && git commit -m "chore: final cleanup for observability implementation"
```

---

## Summary of All Commits

1. `build: add opentelemetry dependencies`
2. `feat(observability): add config module with env var support`
3. `feat(observability): add tracer init and @traced decorator`
4. `feat(observability): add metric definitions (counters, histograms, gauges)`
5. `feat(observability): add token estimation utilities`
6. `feat(observability): add SQLite request trace store`
7. `feat(observability): instrument FastAPI with OTEL auto-instrumentation and request ID middleware`
8. `feat(observability): instrument agent pipeline with spans, metrics, and SQLite traces`
9. `feat(observability): instrument search orchestrator with per-tier spans`
10. `feat(observability): instrument embeddings and semantic search with spans`
11. `infra: add OTEL collector, Jaeger, Prometheus, and Grafana to docker-compose`
12. `feat(observability): add pre-provisioned Grafana dashboard definitions`
13. `test(observability): add integration tests for full observability stack`
