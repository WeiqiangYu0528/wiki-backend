# Backend Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenTelemetry-based observability to the FastAPI wiki agent backend so every request produces a trace with token usage, search quality, and latency breakdown — plus a debug UI for per-request inspection.

**Architecture:** OpenTelemetry Python SDK instruments each pipeline stage with spans and metrics. Traces export to Jaeger (dev) via OTLP gRPC. Prometheus metrics are exposed at `/metrics`. A lightweight in-memory ring buffer powers a debug HTML page at `/debug/traces`. structlog replaces basic logging for JSON-structured, trace-correlated output.

**Tech Stack:** OpenTelemetry SDK, FastAPI auto-instrumentation, httpx auto-instrumentation, structlog, Jaeger, Prometheus, Grafana, ChromaDB (existing), LangGraph/LangChain (existing)

**Spec:** `docs/superpowers/specs/2026-04-11-backend-observability-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|----------------|
| `backend/observability/__init__.py` | Package init, re-exports `init_observability`, `get_tracer`, `get_meter` |
| `backend/observability/setup.py` | OTel SDK init: TracerProvider, MeterProvider, OTLP exporter, Prometheus exporter, FastAPI/httpx auto-instrumentation, toggle via `OTEL_ENABLED` |
| `backend/observability/metrics.py` | All Prometheus metric instrument definitions (counters, histograms) |
| `backend/observability/spans.py` | Span helper context managers for search, embedding, prompt build |
| `backend/observability/callbacks.py` | `OTelCallbackHandler(BaseCallbackHandler)` for LangChain LLM/tool events |
| `backend/observability/middleware.py` | FastAPI middleware: assigns `request_id`, sets root span attributes |
| `backend/observability/trace_buffer.py` | `TraceRecord` dataclass + `TraceBuffer` ring buffer (last N traces) |
| `backend/observability/debug_routes.py` | FastAPI router: `/debug/traces`, `/debug/traces/api`, `/debug/traces/api/{id}`, `/debug/metrics` |
| `backend/observability/debug_ui.html` | Single-file HTML + CSS + JS debug page |
| `backend/observability/prometheus.yml` | Prometheus scrape config (dev) |
| `backend/observability/grafana-dashboards/agent-overview.json` | Pre-built Grafana dashboard |
| `backend/observability/test_trace_buffer.py` | Tests for ring buffer |
| `backend/observability/test_callbacks.py` | Tests for callback handler |
| `backend/observability/test_metrics.py` | Tests for metric recording |
| `backend/observability/test_middleware.py` | Tests for middleware |

### Modified Files

| File | Changes |
|------|---------|
| `backend/pyproject.toml` | Add OTel + structlog dependencies |
| `backend/main.py` | Call `init_observability()`, add middleware, mount debug routes |
| `backend/agent.py` | Add spans around `build_system_prompt`, `_format_history`, pass `OTelCallbackHandler` to `create_react_agent` |
| `backend/search_tools.py` | Add spans inside `smart_search`, `find_symbol`, `read_code_section` tools |
| `backend/search/orchestrator.py` | Add spans around each search tier, record search quality attributes |
| `backend/search/semantic.py` | Add spans around embedding calls and ChromaDB queries |
| `backend/search/lexical.py` | Add span around ripgrep/grep execution |
| `backend/security.py` | Add observability env vars to `Settings` |
| `docker-compose.yml` | Add optional Jaeger, Prometheus, Grafana services |

---

## Task 1: Add Dependencies

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add OTel and structlog dependencies to pyproject.toml**

Replace the `dependencies` list in `backend/pyproject.toml`:

```toml
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
    "chromadb",
    "tree-sitter",
    "tree-sitter-python",
    "tree-sitter-typescript",
    "tree-sitter-c-sharp",
    "opentelemetry-api",
    "opentelemetry-sdk",
    "opentelemetry-exporter-otlp-proto-grpc",
    "opentelemetry-instrumentation-fastapi",
    "opentelemetry-instrumentation-httpx",
    "opentelemetry-exporter-prometheus",
    "structlog",
]
```

- [ ] **Step 2: Install dependencies**

Run: `cd backend && uv sync`
Expected: All new packages install successfully

- [ ] **Step 3: Verify imports work**

Run: `cd backend && python -c "import opentelemetry; import structlog; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki
git add backend/pyproject.toml backend/uv.lock
git commit -m "build: add opentelemetry and structlog dependencies"
```

---

## Task 2: Add Observability Config to Settings

**Files:**
- Modify: `backend/security.py`

- [ ] **Step 1: Add observability settings to the Settings class**

Add these fields after the existing `read_code_max_symbol_lines` field in the `Settings` class in `backend/security.py`:

```python
    # Observability
    otel_enabled: bool = True
    otel_service_name: str = "wiki-agent-backend"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_metrics_exporter: str = "prometheus"
    debug_ui_enabled: bool = True
    debug_trace_buffer_size: int = 200
    warn_prompt_tokens: int = 6000
    warn_tool_results_pct: int = 60
    warn_llm_calls_max: int = 5
    warn_request_duration_seconds: int = 30
```

- [ ] **Step 2: Verify settings load**

Run: `cd backend && python -c "from security import settings; print(settings.otel_enabled, settings.otel_service_name)"`
Expected: `True wiki-agent-backend`

- [ ] **Step 3: Commit**

```bash
git add backend/security.py
git commit -m "feat(observability): add observability settings to config"
```

---

## Task 3: OTel SDK Setup

**Files:**
- Create: `backend/observability/__init__.py`
- Create: `backend/observability/setup.py`

- [ ] **Step 1: Create the observability package init**

Create `backend/observability/__init__.py`:

```python
"""Observability package for the wiki agent backend.

Provides OpenTelemetry tracing, Prometheus metrics, structured logging,
and a debug UI for per-request inspection.
"""

from observability.setup import init_observability, get_tracer, get_meter
```

- [ ] **Step 2: Create the OTel SDK setup module**

Create `backend/observability/setup.py`:

```python
"""OpenTelemetry SDK initialization.

Call init_observability() once at app startup. All instrumentation
is gated behind settings.otel_enabled — when disabled, the OTel API
returns no-op tracers and meters with negligible overhead.
"""

import logging

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource

_initialized = False
_SERVICE_NAME = "wiki-agent-backend"


def get_tracer(name: str = "wiki-agent") -> trace.Tracer:
    return trace.get_tracer(name)


def get_meter(name: str = "wiki-agent") -> metrics.Meter:
    return metrics.get_meter(name)


def init_observability(app=None) -> None:
    """Initialize OTel tracing, metrics, and auto-instrumentation.

    Args:
        app: FastAPI application instance for auto-instrumentation.
    """
    global _initialized
    if _initialized:
        return

    from security import settings

    if not settings.otel_enabled:
        logging.getLogger(__name__).info("Observability disabled (OTEL_ENABLED=false)")
        _initialized = True
        return

    resource = Resource.create({
        "service.name": settings.otel_service_name,
    })

    # --- Tracing ---
    tracer_provider = TracerProvider(resource=resource)

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        otlp_exporter = OTLPSpanExporter(
            endpoint=settings.otel_exporter_otlp_endpoint,
            insecure=True,
        )
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    except Exception as e:
        logging.getLogger(__name__).warning("OTLP trace exporter failed to init: %s", e)

    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ---
    metric_readers = []

    if settings.otel_metrics_exporter == "prometheus":
        try:
            from opentelemetry.exporter.prometheus import PrometheusMetricReader
            prometheus_reader = PrometheusMetricReader()
            metric_readers.append(prometheus_reader)
        except Exception as e:
            logging.getLogger(__name__).warning("Prometheus metric reader failed: %s", e)

    meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
    metrics.set_meter_provider(meter_provider)

    # --- Auto-instrumentation ---
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
        except Exception as e:
            logging.getLogger(__name__).warning("FastAPI auto-instrumentation failed: %s", e)

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except Exception as e:
        logging.getLogger(__name__).warning("httpx auto-instrumentation failed: %s", e)

    _initialized = True
    logging.getLogger(__name__).info(
        "Observability initialized: tracing=%s, metrics=%s",
        settings.otel_exporter_otlp_endpoint,
        settings.otel_metrics_exporter,
    )
```

- [ ] **Step 3: Verify setup imports**

Run: `cd backend && python -c "from observability.setup import init_observability, get_tracer, get_meter; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/observability/__init__.py backend/observability/setup.py
git commit -m "feat(observability): add OTel SDK setup with tracing and metrics"
```

---

## Task 4: Metric Instrument Definitions

**Files:**
- Create: `backend/observability/metrics.py`
- Create: `backend/observability/test_metrics.py`

- [ ] **Step 1: Write the test for metric instruments**

Create `backend/observability/test_metrics.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from observability.metrics import (
    requests_counter,
    llm_calls_counter,
    llm_tokens_input_counter,
    llm_tokens_output_counter,
    search_calls_counter,
    embedding_calls_counter,
    embedding_cache_hits_counter,
    embedding_cache_misses_counter,
    tool_calls_counter,
    request_duration_histogram,
    llm_call_duration_histogram,
    tool_call_duration_histogram,
    prompt_tokens_histogram,
    search_results_histogram,
    embedding_api_duration_histogram,
)

# --- TEST 1: All instruments exist and are callable ---
print("=== TEST 1: all instruments exist ===")
assert requests_counter is not None
assert llm_calls_counter is not None
assert llm_tokens_input_counter is not None
assert llm_tokens_output_counter is not None
assert search_calls_counter is not None
assert embedding_calls_counter is not None
assert embedding_cache_hits_counter is not None
assert embedding_cache_misses_counter is not None
assert tool_calls_counter is not None
assert request_duration_histogram is not None
assert llm_call_duration_histogram is not None
assert tool_call_duration_histogram is not None
assert prompt_tokens_histogram is not None
assert search_results_histogram is not None
assert embedding_api_duration_histogram is not None
print("PASS")

# --- TEST 2: Counters can be incremented ---
print("\n=== TEST 2: counters can be incremented ===")
requests_counter.add(1, {"model": "test", "status": "ok", "endpoint": "/chat"})
llm_calls_counter.add(1, {"model": "test"})
llm_tokens_input_counter.add(100, {"model": "test"})
llm_tokens_output_counter.add(50, {"model": "test"})
search_calls_counter.add(1, {"tier": "lexical"})
embedding_calls_counter.add(1)
embedding_cache_hits_counter.add(3)
embedding_cache_misses_counter.add(2)
tool_calls_counter.add(1, {"tool_name": "smart_search"})
print("PASS")

# --- TEST 3: Histograms can record ---
print("\n=== TEST 3: histograms can record ===")
request_duration_histogram.record(1.5, {"model": "test", "endpoint": "/chat"})
llm_call_duration_histogram.record(0.8, {"model": "test"})
tool_call_duration_histogram.record(0.05, {"tool_name": "smart_search"})
prompt_tokens_histogram.record(2000, {"model": "test"})
search_results_histogram.record(5, {"tier": "semantic"})
embedding_api_duration_histogram.record(0.045)
print("PASS")

print("\n✅ All metric tests passed.")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python observability/test_metrics.py`
Expected: `ModuleNotFoundError: No module named 'observability.metrics'`

- [ ] **Step 3: Create the metrics module**

Create `backend/observability/metrics.py`:

```python
"""Prometheus metric instrument definitions.

All metric instruments are created once at import time using the
global OTel meter. They are safe to use even before init_observability()
is called — OTel returns no-op instruments until a MeterProvider is set.
"""

from observability.setup import get_meter

_meter = get_meter("wiki-agent")

# --- Counters ---

requests_counter = _meter.create_counter(
    name="agent_requests_total",
    description="Total agent requests",
    unit="1",
)

llm_calls_counter = _meter.create_counter(
    name="agent_llm_calls_total",
    description="Total LLM API invocations",
    unit="1",
)

llm_tokens_input_counter = _meter.create_counter(
    name="agent_llm_tokens_input_total",
    description="Total input tokens consumed by LLM calls",
    unit="1",
)

llm_tokens_output_counter = _meter.create_counter(
    name="agent_llm_tokens_output_total",
    description="Total output tokens generated by LLM calls",
    unit="1",
)

search_calls_counter = _meter.create_counter(
    name="agent_search_calls_total",
    description="Total search calls by tier",
    unit="1",
)

embedding_calls_counter = _meter.create_counter(
    name="agent_embedding_calls_total",
    description="Total embedding API calls (cache misses)",
    unit="1",
)

embedding_cache_hits_counter = _meter.create_counter(
    name="agent_embedding_cache_hits_total",
    description="Total embedding cache hits",
    unit="1",
)

embedding_cache_misses_counter = _meter.create_counter(
    name="agent_embedding_cache_misses_total",
    description="Total embedding cache misses",
    unit="1",
)

tool_calls_counter = _meter.create_counter(
    name="agent_tool_calls_total",
    description="Total tool invocations by tool name",
    unit="1",
)

# --- Histograms ---

request_duration_histogram = _meter.create_histogram(
    name="agent_request_duration_seconds",
    description="Request latency distribution",
    unit="s",
)

llm_call_duration_histogram = _meter.create_histogram(
    name="agent_llm_call_duration_seconds",
    description="LLM API call latency distribution",
    unit="s",
)

tool_call_duration_histogram = _meter.create_histogram(
    name="agent_tool_call_duration_seconds",
    description="Tool execution time distribution",
    unit="s",
)

prompt_tokens_histogram = _meter.create_histogram(
    name="agent_prompt_tokens",
    description="Prompt size distribution in estimated tokens",
    unit="1",
)

search_results_histogram = _meter.create_histogram(
    name="agent_search_results_count",
    description="Number of results per search call",
    unit="1",
)

embedding_api_duration_histogram = _meter.create_histogram(
    name="agent_embedding_api_duration_seconds",
    description="Embedding API (Ollama) latency distribution",
    unit="s",
)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python observability/test_metrics.py`
Expected: All 3 tests pass, `✅ All metric tests passed.`

- [ ] **Step 5: Commit**

```bash
git add backend/observability/metrics.py backend/observability/test_metrics.py
git commit -m "feat(observability): add Prometheus metric instrument definitions"
```

---

## Task 5: Trace Buffer for Debug UI

**Files:**
- Create: `backend/observability/trace_buffer.py`
- Create: `backend/observability/test_trace_buffer.py`

- [ ] **Step 1: Write the test for the trace buffer**

Create `backend/observability/test_trace_buffer.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from observability.trace_buffer import TraceRecord, TraceBuffer

# --- TEST 1: TraceRecord creation ---
print("=== TEST 1: TraceRecord creation ===")
record = TraceRecord(
    request_id="req-001",
    trace_id="abc123",
    timestamp="2026-04-11T12:00:00Z",
    endpoint="/chat",
    model="qwen-plus",
    query_preview="how does the tool system work",
    status="ok",
    duration_ms=1500.0,
    tokens_input=2800,
    tokens_output=350,
    llm_calls_count=2,
    tool_calls_count=1,
    search_calls_count=1,
    warnings=[],
    spans=[],
    token_breakdown={},
    search_details=[],
)
assert record.request_id == "req-001"
assert record.tokens_total == 3150
print("PASS")

# --- TEST 2: TraceBuffer add and list ---
print("\n=== TEST 2: TraceBuffer add and list ===")
buf = TraceBuffer(max_size=3)
for i in range(3):
    buf.add(TraceRecord(
        request_id=f"req-{i:03d}",
        trace_id=f"trace-{i}",
        timestamp=f"2026-04-11T12:0{i}:00Z",
        endpoint="/chat",
        model="qwen-plus",
        query_preview=f"query {i}",
        status="ok",
        duration_ms=1000.0 + i * 100,
        tokens_input=1000 + i * 100,
        tokens_output=200 + i * 50,
        llm_calls_count=1,
        tool_calls_count=0,
        search_calls_count=0,
        warnings=[],
        spans=[],
        token_breakdown={},
        search_details=[],
    ))
summaries = buf.list_recent()
assert len(summaries) == 3
assert summaries[0]["request_id"] == "req-002"  # most recent first
print("PASS")

# --- TEST 3: Ring buffer eviction ---
print("\n=== TEST 3: ring buffer eviction ===")
buf.add(TraceRecord(
    request_id="req-003",
    trace_id="trace-3",
    timestamp="2026-04-11T12:03:00Z",
    endpoint="/chat",
    model="qwen-plus",
    query_preview="query 3",
    status="ok",
    duration_ms=1300.0,
    tokens_input=1300,
    tokens_output=350,
    llm_calls_count=1,
    tool_calls_count=0,
    search_calls_count=0,
    warnings=[],
    spans=[],
    token_breakdown={},
    search_details=[],
))
summaries = buf.list_recent()
assert len(summaries) == 3
ids = [s["request_id"] for s in summaries]
assert "req-000" not in ids  # oldest evicted
assert "req-003" in ids
print("PASS")

# --- TEST 4: Get by request_id ---
print("\n=== TEST 4: get by request_id ===")
detail = buf.get("req-003")
assert detail is not None
assert detail["request_id"] == "req-003"
assert detail["tokens_total"] == 1650
assert buf.get("req-000") is None  # evicted
print("PASS")

print("\n✅ All trace buffer tests passed.")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python observability/test_trace_buffer.py`
Expected: `ModuleNotFoundError: No module named 'observability.trace_buffer'`

- [ ] **Step 3: Create the trace buffer module**

Create `backend/observability/trace_buffer.py`:

```python
"""In-memory ring buffer for recent request traces.

Stores the last N completed request traces for the debug UI.
Thread-safe for concurrent FastAPI request handlers.
"""

import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class TraceRecord:
    """Complete trace data for one agent request."""

    request_id: str
    trace_id: str
    timestamp: str
    endpoint: str
    model: str
    query_preview: str
    status: str  # "ok" or "error"
    duration_ms: float
    tokens_input: int
    tokens_output: int
    llm_calls_count: int
    tool_calls_count: int
    search_calls_count: int
    warnings: list[str]
    spans: list[dict[str, Any]]
    token_breakdown: dict[str, Any]
    search_details: list[dict[str, Any]]

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output

    def to_summary(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "endpoint": self.endpoint,
            "model": self.model,
            "query_preview": self.query_preview,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "tokens_total": self.tokens_total,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "llm_calls_count": self.llm_calls_count,
            "tool_calls_count": self.tool_calls_count,
            "search_calls_count": self.search_calls_count,
            "warnings_count": len(self.warnings),
        }

    def to_detail(self) -> dict[str, Any]:
        d = asdict(self)
        d["tokens_total"] = self.tokens_total
        return d


class TraceBuffer:
    """Thread-safe ring buffer for trace records."""

    def __init__(self, max_size: int = 200) -> None:
        self._max_size = max_size
        self._buffer: deque[TraceRecord] = deque(maxlen=max_size)
        self._index: dict[str, TraceRecord] = {}
        self._lock = threading.Lock()

    def add(self, record: TraceRecord) -> None:
        with self._lock:
            if len(self._buffer) == self._max_size:
                evicted = self._buffer[0]
                self._index.pop(evicted.request_id, None)
            self._buffer.append(record)
            self._index[record.request_id] = record

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._buffer)
        records.reverse()
        return [r.to_summary() for r in records[:limit]]

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._index.get(request_id)
        if record is None:
            return None
        return record.to_detail()

    def __len__(self) -> int:
        return len(self._buffer)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python observability/test_trace_buffer.py`
Expected: All 4 tests pass, `✅ All trace buffer tests passed.`

- [ ] **Step 5: Commit**

```bash
git add backend/observability/trace_buffer.py backend/observability/test_trace_buffer.py
git commit -m "feat(observability): add in-memory trace buffer for debug UI"
```

---

## Task 6: LangChain OTel Callback Handler

**Files:**
- Create: `backend/observability/callbacks.py`
- Create: `backend/observability/test_callbacks.py`

- [ ] **Step 1: Write the test for the callback handler**

Create `backend/observability/test_callbacks.py`:

```python
import sys, os, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from observability.callbacks import OTelCallbackHandler

# --- TEST 1: Handler creation ---
print("=== TEST 1: handler creation ===")
handler = OTelCallbackHandler(model_id="qwen-plus", request_id="test-001")
assert handler.model_id == "qwen-plus"
assert handler.request_id == "test-001"
assert handler.llm_calls_count == 0
assert handler.total_tokens_input == 0
assert handler.total_tokens_output == 0
print("PASS")

# --- TEST 2: Simulate LLM start/end cycle ---
print("\n=== TEST 2: simulate LLM start/end ===")
from unittest.mock import MagicMock

run_id = uuid.uuid4()
handler.on_llm_start(serialized={}, prompts=["Hello world"], run_id=run_id)
assert handler.llm_calls_count == 0  # not counted until end

mock_response = MagicMock()
mock_response.llm_output = {"token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
handler.on_llm_end(response=mock_response, run_id=run_id)

assert handler.llm_calls_count == 1
assert handler.total_tokens_input == 100
assert handler.total_tokens_output == 50
assert len(handler.llm_call_records) == 1
assert handler.llm_call_records[0]["tokens_input"] == 100
assert handler.llm_call_records[0]["tokens_output"] == 50
print("PASS")

# --- TEST 3: Simulate tool start/end cycle ---
print("\n=== TEST 3: simulate tool start/end ===")
tool_run_id = uuid.uuid4()
handler.on_tool_start(serialized={"name": "smart_search"}, input_str="test query", run_id=tool_run_id)
assert handler.tool_calls_count == 0  # not counted until end

handler.on_tool_end(output="result text here", run_id=tool_run_id)
assert handler.tool_calls_count == 1
assert len(handler.tool_call_records) == 1
assert handler.tool_call_records[0]["name"] == "smart_search"
assert handler.tool_call_records[0]["output_size"] == len("result text here")
print("PASS")

# --- TEST 4: get_summary ---
print("\n=== TEST 4: get_summary ===")
summary = handler.get_summary()
assert summary["llm_calls_count"] == 1
assert summary["tool_calls_count"] == 1
assert summary["total_tokens_input"] == 100
assert summary["total_tokens_output"] == 50
assert len(summary["llm_calls"]) == 1
assert len(summary["tool_calls"]) == 1
print("PASS")

# --- TEST 5: LLM error handling ---
print("\n=== TEST 5: LLM error handling ===")
error_run_id = uuid.uuid4()
handler.on_llm_start(serialized={}, prompts=["test"], run_id=error_run_id)
handler.on_llm_error(error=ValueError("test error"), run_id=error_run_id)
# Should not crash, llm_calls_count stays at 1 (only successful calls counted)
assert handler.llm_calls_count == 1
print("PASS")

print("\n✅ All callback handler tests passed.")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python observability/test_callbacks.py`
Expected: `ModuleNotFoundError: No module named 'observability.callbacks'`

- [ ] **Step 3: Create the callback handler module**

Create `backend/observability/callbacks.py`:

```python
"""LangChain callback handler for OpenTelemetry tracing and metrics.

Intercepts LLM and tool events from LangGraph's ReAct agent to create
OTel spans and record token usage metrics.
"""

import time
import uuid
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from observability.setup import get_tracer
from observability.metrics import (
    llm_calls_counter,
    llm_tokens_input_counter,
    llm_tokens_output_counter,
    llm_call_duration_histogram,
    tool_calls_counter,
    tool_call_duration_histogram,
    prompt_tokens_histogram,
)

tracer = get_tracer("wiki-agent.callbacks")


class OTelCallbackHandler(BaseCallbackHandler):
    """Captures LLM and tool call events for tracing and metrics."""

    def __init__(self, model_id: str = "", request_id: str = "") -> None:
        super().__init__()
        self.model_id = model_id
        self.request_id = request_id

        self.llm_calls_count = 0
        self.tool_calls_count = 0
        self.total_tokens_input = 0
        self.total_tokens_output = 0

        self.llm_call_records: list[dict[str, Any]] = []
        self.tool_call_records: list[dict[str, Any]] = []

        self._llm_spans: dict[uuid.UUID, tuple[Any, float]] = {}
        self._tool_spans: dict[uuid.UUID, tuple[Any, str, float]] = {}

    # --- LLM events ---

    def on_llm_start(self, serialized: dict, prompts: list[str], *, run_id: uuid.UUID, **kwargs) -> None:
        span = tracer.start_span("llm_call")
        span.set_attribute("llm.model", self.model_id)
        span.set_attribute("request.id", self.request_id)
        prompt_chars = sum(len(p) for p in prompts)
        estimated_tokens = prompt_chars // 4
        span.set_attribute("llm.prompt.estimated_tokens", estimated_tokens)
        span.set_attribute("llm.prompt.char_count", prompt_chars)
        prompt_tokens_histogram.record(estimated_tokens, {"model": self.model_id})
        self._llm_spans[run_id] = (span, time.monotonic())

    def on_llm_end(self, response: LLMResult, *, run_id: uuid.UUID, **kwargs) -> None:
        entry = self._llm_spans.pop(run_id, None)
        if entry is None:
            return
        span, start_time = entry
        duration = time.monotonic() - start_time

        usage = {}
        if response.llm_output:
            usage = response.llm_output.get("token_usage", {})

        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)

        span.set_attribute("llm.tokens.input", tokens_in)
        span.set_attribute("llm.tokens.output", tokens_out)
        span.set_attribute("llm.tokens.total", tokens_in + tokens_out)
        span.set_attribute("llm.duration_seconds", duration)
        span.end()

        llm_calls_counter.add(1, {"model": self.model_id})
        llm_tokens_input_counter.add(tokens_in, {"model": self.model_id})
        llm_tokens_output_counter.add(tokens_out, {"model": self.model_id})
        llm_call_duration_histogram.record(duration, {"model": self.model_id})

        self.llm_calls_count += 1
        self.total_tokens_input += tokens_in
        self.total_tokens_output += tokens_out
        self.llm_call_records.append({
            "call_index": self.llm_calls_count,
            "model": self.model_id,
            "tokens_input": tokens_in,
            "tokens_output": tokens_out,
            "duration_seconds": round(duration, 3),
        })

    def on_llm_error(self, error: BaseException, *, run_id: uuid.UUID, **kwargs) -> None:
        entry = self._llm_spans.pop(run_id, None)
        if entry is None:
            return
        span, _ = entry
        span.set_attribute("llm.error", str(error))
        span.record_exception(error)
        span.end()

    # --- Tool events ---

    def on_tool_start(self, serialized: dict, input_str: str, *, run_id: uuid.UUID, **kwargs) -> None:
        tool_name = serialized.get("name", "unknown")
        span = tracer.start_span(f"tool:{tool_name}")
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("tool.input_preview", str(input_str)[:500])
        span.set_attribute("request.id", self.request_id)
        self._tool_spans[run_id] = (span, tool_name, time.monotonic())

    def on_tool_end(self, output: str, *, run_id: uuid.UUID, **kwargs) -> None:
        entry = self._tool_spans.pop(run_id, None)
        if entry is None:
            return
        span, tool_name, start_time = entry
        duration = time.monotonic() - start_time

        output_size = len(str(output))
        span.set_attribute("tool.output_size", output_size)
        span.set_attribute("tool.duration_seconds", duration)
        span.end()

        tool_calls_counter.add(1, {"tool_name": tool_name})
        tool_call_duration_histogram.record(duration, {"tool_name": tool_name})

        self.tool_calls_count += 1
        self.tool_call_records.append({
            "name": tool_name,
            "output_size": output_size,
            "duration_seconds": round(duration, 3),
        })

    def on_tool_error(self, error: BaseException, *, run_id: uuid.UUID, **kwargs) -> None:
        entry = self._tool_spans.pop(run_id, None)
        if entry is None:
            return
        span, tool_name, _ = entry
        span.set_attribute("tool.error", str(error))
        span.record_exception(error)
        span.end()
        tool_calls_counter.add(1, {"tool_name": tool_name})

    # --- Summary ---

    def get_summary(self) -> dict[str, Any]:
        return {
            "model": self.model_id,
            "llm_calls_count": self.llm_calls_count,
            "tool_calls_count": self.tool_calls_count,
            "total_tokens_input": self.total_tokens_input,
            "total_tokens_output": self.total_tokens_output,
            "total_tokens": self.total_tokens_input + self.total_tokens_output,
            "llm_calls": self.llm_call_records,
            "tool_calls": self.tool_call_records,
        }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python observability/test_callbacks.py`
Expected: All 5 tests pass, `✅ All callback handler tests passed.`

- [ ] **Step 5: Commit**

```bash
git add backend/observability/callbacks.py backend/observability/test_callbacks.py
git commit -m "feat(observability): add LangChain OTel callback handler"
```

---

## Task 7: Span Helpers for Search Pipeline

**Files:**
- Create: `backend/observability/spans.py`

- [ ] **Step 1: Create span helper context managers**

Create `backend/observability/spans.py`:

```python
"""Span helper context managers for instrumenting the search pipeline.

Usage:
    with search_span("orchestrate", query="test", scope="auto") as span:
        results = do_search()
        span.set_attribute("search.results_count", len(results))
"""

import time
from contextlib import contextmanager
from typing import Any, Generator

from opentelemetry import trace

from observability.setup import get_tracer

tracer = get_tracer("wiki-agent.search")


@contextmanager
def search_span(name: str, **attrs: Any) -> Generator[trace.Span, None, None]:
    """Create a span for a search pipeline stage."""
    with tracer.start_as_current_span(f"search.{name}") as span:
        for k, v in attrs.items():
            span.set_attribute(f"search.{k}", _safe_attr(v))
        yield span


@contextmanager
def embedding_span(**attrs: Any) -> Generator[trace.Span, None, None]:
    """Create a span for an embedding operation."""
    with tracer.start_as_current_span("embedding.generate") as span:
        for k, v in attrs.items():
            span.set_attribute(f"embedding.{k}", _safe_attr(v))
        yield span


@contextmanager
def agent_span(name: str, **attrs: Any) -> Generator[trace.Span, None, None]:
    """Create a span for an agent pipeline stage."""
    with tracer.start_as_current_span(name) as span:
        for k, v in attrs.items():
            span.set_attribute(k, _safe_attr(v))
        yield span


@contextmanager
def timed_span(name: str, **attrs: Any) -> Generator[tuple[trace.Span, dict], None, None]:
    """Create a span that automatically records duration_ms on exit.

    Yields (span, timing_dict). The timing_dict is populated with
    'duration_ms' after the context exits.
    """
    timing: dict[str, float] = {}
    with tracer.start_as_current_span(name) as span:
        for k, v in attrs.items():
            span.set_attribute(k, _safe_attr(v))
        start = time.monotonic()
        yield span, timing
        elapsed_ms = (time.monotonic() - start) * 1000
        timing["duration_ms"] = round(elapsed_ms, 2)
        span.set_attribute("duration_ms", timing["duration_ms"])


def _safe_attr(value: Any) -> str | int | float | bool:
    """Convert a value to an OTel-safe attribute type."""
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return str(value)
    return str(value)
```

- [ ] **Step 2: Verify import**

Run: `cd backend && python -c "from observability.spans import search_span, embedding_span, agent_span, timed_span; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/observability/spans.py
git commit -m "feat(observability): add span helper context managers"
```

---

## Task 8: Instrument Search Orchestrator

**Files:**
- Modify: `backend/search/orchestrator.py`

- [ ] **Step 1: Add spans to the search orchestrator**

In `backend/search/orchestrator.py`, add the import at the top (after existing imports):

```python
from observability.spans import search_span, timed_span
from observability.metrics import search_calls_counter, search_results_histogram
```

Then replace the `search` method body of `SearchOrchestrator` (lines 104–178) with this instrumented version:

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

        cache_key = f"{query}:{scope}"
        if cache_key in self._session_cache:
            logger.debug("Search cache hit for: %s", query[:50])
            return self._session_cache[cache_key]

        with search_span("orchestrate", query=query[:200], scope=scope) as root_span:
            namespace = scope if scope not in ("auto", "wiki", "code") else ""
            targets = self.registry.target(query, page_url=page_url, namespace=namespace)
            query_type = classify_query(query)
            root_span.set_attribute("search.query_type", query_type)

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
            with search_span("lexical", paths_count=len(search_paths)) as lex_span:
                if query_type in ("symbol", "exact"):
                    lexical_results = self.lexical.search(query, search_paths=search_paths, max_results=max_results)
                else:
                    lexical_results = self.lexical.search(query, search_paths=search_paths, max_results=5)
                all_results.extend(lexical_results)
                tiers_used.append("lexical")
                lex_span.set_attribute("search.results_count", len(lexical_results))
                search_calls_counter.add(1, {"tier": "lexical"})
                search_results_histogram.record(len(lexical_results), {"tier": "lexical"})

            # Early stopping
            distinct_files = len({r.get("file_path", "") for r in all_results})
            high_confidence = len(all_results) >= 5 and distinct_files >= 2
            early_stopped = False

            # --- Tier 2: Semantic ---
            if self._ready and not high_confidence and (query_type == "concept" or len(all_results) < 3):
                with search_span("semantic") as sem_span:
                    semantic_results = self._semantic_search(query, scope, targets, max_results)
                    all_results.extend(semantic_results)
                    tiers_used.append("semantic")
                    sem_span.set_attribute("search.results_count", len(semantic_results))
                    search_calls_counter.add(1, {"tier": "semantic"})
                    search_results_histogram.record(len(semantic_results), {"tier": "semantic"})
            elif high_confidence:
                early_stopped = True

            # --- Tier 3: Symbol ---
            if self._ready and query_type == "symbol" and len(all_results) < 3:
                with search_span("symbol") as sym_span:
                    symbol_results = self.semantic.query("symbols", query, n_results=5)
                    all_results.extend(symbol_results)
                    tiers_used.append("symbol")
                    sym_span.set_attribute("search.results_count", len(symbol_results))
                    search_calls_counter.add(1, {"tier": "symbol"})
                    search_results_histogram.record(len(symbol_results), {"tier": "symbol"})

            logger.info("Search '%s' → tiers: %s, raw results: %d", query[:40], tiers_used, len(all_results))

            seen: set[str] = set()
            unique: list[dict] = []
            for r in all_results:
                key = f"{r.get('file_path', '')}:{r.get('line_number', r.get('start_line', ''))}"
                if key not in seen:
                    seen.add(key)
                    unique.append(r)

            unique.sort(key=lambda r: r.get("score", 0), reverse=True)
            result = format_results(unique[:max_results], max_chars=self._max_chars, result_max_chars=self._result_max_chars)

            # Record summary attributes on root span
            distinct_files = len({r.get("file_path", "") for r in unique})
            root_span.set_attribute("search.tiers_used", str(tiers_used))
            root_span.set_attribute("search.total_raw_results", len(all_results))
            root_span.set_attribute("search.unique_results", len(unique))
            root_span.set_attribute("search.results_returned", min(len(unique), max_results))
            root_span.set_attribute("search.results_chars", len(result))
            root_span.set_attribute("search.distinct_files", distinct_files)
            root_span.set_attribute("search.early_stopped", early_stopped)
            root_span.set_attribute("search.cache_hit", False)

            search_calls_counter.add(1, {"tier": "orchestrate"})

            self._session_cache[cache_key] = result
            return result
```

- [ ] **Step 2: Run existing search orchestrator tests**

Run: `cd backend && python search/test_orchestrator.py`
Expected: All existing tests pass

- [ ] **Step 3: Commit**

```bash
git add backend/search/orchestrator.py
git commit -m "feat(observability): instrument search orchestrator with OTel spans"
```

---

## Task 9: Instrument Semantic Search & Embeddings

**Files:**
- Modify: `backend/search/semantic.py`

- [ ] **Step 1: Add spans to embedding function and semantic query**

In `backend/search/semantic.py`, add the import at the top (after existing imports):

```python
from observability.spans import embedding_span, search_span
from observability.metrics import (
    embedding_calls_counter,
    embedding_cache_hits_counter,
    embedding_cache_misses_counter,
    embedding_api_duration_histogram,
)
```

Then replace the `__call__` method of `OllamaEmbeddingFunction` (lines 76–116) with this instrumented version:

```python
    def __call__(self, input: list[str]) -> list[list[float]]:
        if not input:
            return []

        with embedding_span(model=self._model, requested=len(input)) as span:
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
            embedding_cache_hits_counter.add(cache_hits)
            embedding_cache_misses_counter.add(len(uncached))

            if uncached:
                import time as _time
                for batch_start in range(0, len(uncached), BATCH_SIZE):
                    batch = uncached[batch_start:batch_start + BATCH_SIZE]
                    batch_texts = [t for _, t in batch]
                    api_start = _time.monotonic()
                    try:
                        resp = httpx.post(
                            f"{self._base_url}/api/embed",
                            json={"model": self._model, "input": batch_texts},
                            timeout=120,
                        )
                        resp.raise_for_status()
                    except httpx.ConnectError:
                        logger.warning(
                            "Ollama not reachable at %s — returning empty embeddings",
                            self._base_url,
                        )
                        return []

                    api_duration = _time.monotonic() - api_start
                    embedding_calls_counter.add(1)
                    embedding_api_duration_histogram.record(api_duration)
                    span.set_attribute("embedding.api_duration_ms", round(api_duration * 1000, 2))

                    data = resp.json()
                    embeddings = data["embeddings"]
                    for i, (orig_idx, text) in enumerate(batch):
                        emb = embeddings[i]
                        self._cache.put(self._model, text, emb)
                        results.append((orig_idx, emb))

            results.sort(key=lambda x: x[0])
            return [emb for _, emb in results]
```

Then replace the `query` method of `SemanticSearch` (lines 183–234) with this instrumented version:

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

        with search_span("chromadb_query", collection=collection_name, n_results=n_results) as span:
            try:
                collection = self._client.get_collection(
                    name=collection_name,
                    embedding_function=self._embed_fn,
                )
            except Exception:
                return []

            count = collection.count()
            if count == 0:
                return []

            kwargs: dict[str, Any] = {
                "query_texts": [query_text],
                "n_results": min(n_results, count),
            }
            if where:
                kwargs["where"] = where

            try:
                results = collection.query(**kwargs)
            except Exception as e:
                logger.warning("Semantic query failed: %s", e)
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

- [ ] **Step 2: Run existing semantic tests**

Run: `cd backend && python search/test_semantic.py`
Expected: All existing tests pass (embedding cache tests work without Ollama; integration tests skip if Ollama unavailable)

- [ ] **Step 3: Commit**

```bash
git add backend/search/semantic.py
git commit -m "feat(observability): instrument embeddings and semantic search with spans"
```

---

## Task 10: Instrument Lexical Search

**Files:**
- Modify: `backend/search/lexical.py`

- [ ] **Step 1: Add span to lexical search**

In `backend/search/lexical.py`, add the import at the top (after existing imports):

```python
from observability.spans import timed_span
```

Then wrap the body of the `search` method (lines 23–45). Replace:

```python
    def search(
        self,
        query: str,
        search_paths: Optional[list[str]] = None,
        max_results: int = 15,
        file_glob: str = "",
        context_lines: int = 2,
    ) -> list[dict]:
        if not query.strip():
            return []

        if search_paths:
            abs_paths = [os.path.join(self.workspace_dir, p) for p in search_paths]
        else:
            abs_paths = [self.workspace_dir]

        abs_paths = [p for p in abs_paths if os.path.exists(p)]
        if not abs_paths:
            return []

        if self._has_rg:
            return self._search_rg(query, abs_paths, max_results, file_glob, context_lines)
        return self._search_grep(query, abs_paths, max_results, file_glob, context_lines)
```

With:

```python
    def search(
        self,
        query: str,
        search_paths: Optional[list[str]] = None,
        max_results: int = 15,
        file_glob: str = "",
        context_lines: int = 2,
    ) -> list[dict]:
        if not query.strip():
            return []

        if search_paths:
            abs_paths = [os.path.join(self.workspace_dir, p) for p in search_paths]
        else:
            abs_paths = [self.workspace_dir]

        abs_paths = [p for p in abs_paths if os.path.exists(p)]
        if not abs_paths:
            return []

        with timed_span("search.lexical_exec", **{"search.engine": "rg" if self._has_rg else "grep", "search.paths_count": len(abs_paths)}) as (span, timing):
            if self._has_rg:
                results = self._search_rg(query, abs_paths, max_results, file_glob, context_lines)
            else:
                results = self._search_grep(query, abs_paths, max_results, file_glob, context_lines)
            span.set_attribute("search.results_count", len(results))
            return results
```

- [ ] **Step 2: Run existing lexical tests**

Run: `cd backend && python search/test_lexical.py`
Expected: All existing tests pass

- [ ] **Step 3: Commit**

```bash
git add backend/search/lexical.py
git commit -m "feat(observability): instrument lexical search with timed span"
```

---

## Task 11: Instrument Agent Pipeline

**Files:**
- Modify: `backend/agent.py`

- [ ] **Step 1: Add imports to agent.py**

Add these imports at the top of `backend/agent.py` (after existing imports):

```python
from observability.spans import agent_span
from observability.callbacks import OTelCallbackHandler
from observability.metrics import requests_counter, request_duration_histogram
```

- [ ] **Step 2: Instrument build_system_prompt**

Replace the `build_system_prompt` function (starting at line 279) with:

```python
def build_system_prompt(page_context: Optional[dict] = None) -> str:
    with agent_span("build_system_prompt") as span:
        prompt = """You are a Wiki Knowledge Assistant embedded in a documentation site that covers multiple AI agent codebases.

Available wiki namespaces:
- **Claude Code** (docs/claude-code/) — Claude Code CLI: agent system, tool system, permission model, MCP, skills, memory, state management
- **Deep Agents** (docs/deepagents-wiki/) — DeepAgents framework: graph factory, subagent system, session persistence, ACP server, evals
- **OpenCode** (docs/opencode-wiki/) — OpenCode AI coding assistant: session system, provider system, LSP integration, plugin system
- **OpenClaw** (docs/openclaw-wiki/) — OpenClaw personal assistant: gateway control plane, channel system, routing, voice/media stack
- **AutoGen** (docs/autogen-wiki/) — Microsoft AutoGen: core runtime, AgentChat, distributed workers, model clients, AutoGen Studio
- **Hermes Agent** (docs/hermes-agent-wiki/) — Hermes conversational agent: agent loop, prompt assembly, tool registry, memory/learning

Each namespace contains:
- summaries/ — architecture overview, codebase map, glossary
- entities/ — deep dives into specific systems/components
- concepts/ — cross-cutting design patterns
- syntheses/ — how multiple systems work together end-to-end

Source code repositories:
Each wiki documents a project whose source code is available in the workspace under its own directory:
- claude-code → claude_code/
- deepagents → deepagents/
- opencode → opencode/
- openclaw → openclaw/
- autogen → autogen/
- hermes-agent → hermes-agent/

Wiki pages reference source files using paths relative to their project root (e.g. a Deep Agents page
may cite `libs/deepagents/deepagents/middleware/memory.py` — the actual file is at `deepagents/libs/deepagents/deepagents/middleware/memory.py`).

When answering — follow this tool priority order strictly:
1. **`find_symbol`** first — if the user asks about a specific function, class, or type.
2. **`smart_search`** — for any conceptual or broad question. Use scope="auto".
   Only narrow the scope to a namespace if you are confident it is a single-repo question.
3. **`read_code_section`** — to read a specific function/class from a file by symbol name,
   or a small line range (≤150 lines). ALWAYS prefer this over reading a whole file.
4. **`read_workspace_file`** — ONLY for wiki docs (docs/ folder). These are small and safe.
   For source code files, use `read_code_section` instead.
5. **`read_source_file`** — last resort only. Source files can be thousands of lines.
   If you must use it, always provide start_line/end_line to limit the range.

Token budget rules:
- NEVER read a source file without a line range — always check the header for total line count first.
- If a file is truncated (header says "truncated"), read the next chunk using start_line/end_line.
- Do NOT call `list_wiki_pages` + `read_workspace_file` in a loop — use `smart_search` instead.
- When you have enough information to answer, STOP searching. Do not call multiple search tools for the same question.
- If smart_search returns good results, answer directly. Do not verify with read_workspace_file.
- Prefer read_code_section with a specific symbol name over reading entire files.
- Provide clear, accurate answers grounded in the documentation and source code.
- End your response with a "**Sources:**" section listing each file path you read.

Documentation updates:
- You operate in READ-ONLY mode by default. You CANNOT write files or run git commands directly.
- When you believe documentation should be updated, use `propose_doc_change` to create a proposal.
- The proposal shows the user a diff. Changes are ONLY applied after the user clicks Approve.
- You may ONLY propose changes to files under the `docs/` directory.
- Always provide the COMPLETE new file content in the proposal, not just the changed section.
- Use conventional commit messages: `docs(namespace): description`."""

        if page_context:
            title = page_context.get("title", "").strip()
            url = page_context.get("url", "").strip()
            if title or url:
                prompt += f"\n\nThe user is currently reading: **{title}**"
                if url:
                    prompt += f" ({url})"
                prompt += "\nPrioritise answering in the context of this page when relevant."

        span.set_attribute("prompt.char_count", len(prompt))
        span.set_attribute("prompt.estimated_tokens", len(prompt) // 4)
        span.set_attribute("prompt.page_context", bool(page_context))
        return prompt
```

- [ ] **Step 3: Instrument _format_history**

Replace the `_format_history` function with:

```python
def _format_history(chat_history: list, max_turns: int = 6) -> list:
    """Convert [{role, content}] dicts to LangChain tuples, keeping last N turns."""
    with agent_span("format_history") as span:
        from security import settings
        max_turns = settings.max_history_turns

        result = []
        for msg in chat_history:
            role = "user" if msg.get("role") == "user" else "assistant"
            content = msg.get("content", "").strip()
            if content:
                result.append((role, content))

        total_messages = len(result)
        max_messages = max_turns * 2
        if len(result) > max_messages:
            result = result[-max_messages:]

        total_chars = sum(len(c) for _, c in result)
        span.set_attribute("history.total_messages", total_messages)
        span.set_attribute("history.kept_messages", len(result))
        span.set_attribute("history.truncated", len(result) < total_messages)
        span.set_attribute("history.estimated_tokens", total_chars // 4)
        return result
```

- [ ] **Step 4: Instrument run_agent with callback handler**

Replace the `run_agent` function with:

```python
def run_agent(
    query: str,
    chat_history: list,
    model_id: str = "deepseek",
    page_context: Optional[dict] = None,
) -> str:
    """Blocking agent execution (kept for backward compatibility with /chat endpoint)."""
    import time as _time
    import uuid as _uuid

    request_id = str(_uuid.uuid4())[:8]
    start_time = _time.monotonic()

    with agent_span("agent_invoke", **{"request.id": request_id, "request.model": model_id}) as span:
        callback = OTelCallbackHandler(model_id=model_id, request_id=request_id)
        llm = get_chat_model(model_id)
        agent = create_react_agent(llm, tools=tools)

        messages = [("system", build_system_prompt(page_context))]
        messages.extend(_format_history(chat_history))
        messages.append(("user", query))

        try:
            response = agent.invoke(
                {"messages": messages},
                config={"callbacks": [callback]},
            )
            result = response["messages"][-1].content
            duration = _time.monotonic() - start_time

            summary = callback.get_summary()
            span.set_attribute("tokens.input", summary["total_tokens_input"])
            span.set_attribute("tokens.output", summary["total_tokens_output"])
            span.set_attribute("llm_calls_count", summary["llm_calls_count"])
            span.set_attribute("tool_calls_count", summary["tool_calls_count"])

            requests_counter.add(1, {"model": model_id, "status": "ok", "endpoint": "/chat"})
            request_duration_histogram.record(duration, {"model": model_id, "endpoint": "/chat"})

            return result
        except Exception as e:
            requests_counter.add(1, {"model": model_id, "status": "error", "endpoint": "/chat"})
            return f"Agent execution failed: {e}"
```

- [ ] **Step 5: Instrument run_agent_stream with callback handler and trace recording**

Replace the `run_agent_stream` function with:

```python
async def run_agent_stream(
    query: str,
    chat_history: list,
    model_id: str = "deepseek",
    page_context: Optional[dict] = None,
) -> AsyncGenerator[dict, None]:
    """Streaming agent execution. Yields event dicts as newline-delimited JSON."""
    import time as _time
    import uuid as _uuid
    from datetime import datetime, timezone

    request_id = str(_uuid.uuid4())[:8]
    start_time = _time.monotonic()

    callback = OTelCallbackHandler(model_id=model_id, request_id=request_id)

    with agent_span("agent_invoke_stream", **{"request.id": request_id, "request.model": model_id, "request.query_preview": query[:100]}) as span:
        llm = get_chat_model(model_id)
        agent = create_react_agent(llm, tools=tools)

        system_prompt = build_system_prompt(page_context)
        messages = [("system", system_prompt)]
        history = _format_history(chat_history)
        messages.extend(history)
        messages.append(("user", query))

        cited_files: set[str] = set()
        status = "ok"
        token_count = 0

        try:
            async for event in agent.astream_events(
                {"messages": messages},
                version="v2",
                config={"callbacks": [callback]},
            ):
                event_type = event["event"]

                if event_type == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    content = chunk.content if hasattr(chunk, "content") else ""
                    if isinstance(content, str) and content:
                        token_count += 1
                        yield {"type": "token", "content": content}

                elif event_type == "on_tool_start":
                    tool_name = event["name"]
                    tool_input = event["data"].get("input", {})
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

                    if tool_name == "smart_search" and isinstance(output, str):
                        for line in output.splitlines():
                            m = re.match(r"^\*\*([\w/\-\.]+\.\w+)\*\*", line)
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

            if cited_files:
                yield {"type": "citations", "sources": sorted(cited_files)}

            duration = _time.monotonic() - start_time
            summary = callback.get_summary()

            span.set_attribute("tokens.input", summary["total_tokens_input"])
            span.set_attribute("tokens.output", summary["total_tokens_output"])
            span.set_attribute("llm_calls_count", summary["llm_calls_count"])
            span.set_attribute("tool_calls_count", summary["tool_calls_count"])
            span.set_attribute("stream.token_chunks", token_count)
            span.set_attribute("stream.citations_count", len(cited_files))

            requests_counter.add(1, {"model": model_id, "status": "ok", "endpoint": "/chat/stream"})
            request_duration_histogram.record(duration, {"model": model_id, "endpoint": "/chat/stream"})

            # Record trace for debug UI
            _record_trace(
                request_id=request_id,
                endpoint="/chat/stream",
                model=model_id,
                query=query,
                status="ok",
                duration_ms=duration * 1000,
                callback=callback,
                system_prompt=system_prompt,
                history=history,
            )

            yield {"type": "done"}

        except Exception as e:
            requests_counter.add(1, {"model": model_id, "status": "error", "endpoint": "/chat/stream"})
            yield {"type": "error", "detail": str(e)}
            yield {"type": "done"}
```

- [ ] **Step 6: Add the _record_trace helper function**

Add this function after the `run_agent_stream` function in `backend/agent.py`:

```python
def _record_trace(
    request_id: str,
    endpoint: str,
    model: str,
    query: str,
    status: str,
    duration_ms: float,
    callback: OTelCallbackHandler,
    system_prompt: str,
    history: list,
) -> None:
    """Record a completed request trace into the debug buffer."""
    from datetime import datetime, timezone

    try:
        from observability.trace_buffer import TraceRecord

        summary = callback.get_summary()
        history_chars = sum(len(c) for _, c in history)
        total_prompt_chars = len(system_prompt) + history_chars + len(query)
        tool_results_chars = sum(r.get("output_size", 0) for r in summary["tool_calls"])
        tool_results_pct = round(tool_results_chars / max(total_prompt_chars, 1) * 100, 1)

        warnings: list[str] = []
        from security import settings
        if summary["total_tokens_input"] > settings.warn_prompt_tokens:
            warnings.append(f"Large prompt: {summary['total_tokens_input']} tokens")
        if summary["llm_calls_count"] > settings.warn_llm_calls_max:
            warnings.append(f"Many LLM rounds: {summary['llm_calls_count']} calls")
        if duration_ms > settings.warn_request_duration_seconds * 1000:
            warnings.append(f"Slow request: {duration_ms / 1000:.1f}s")
        if tool_results_pct > settings.warn_tool_results_pct:
            warnings.append(f"Retrieval dominates prompt: {tool_results_pct}%")

        record = TraceRecord(
            request_id=request_id,
            trace_id="",
            timestamp=datetime.now(timezone.utc).isoformat(),
            endpoint=endpoint,
            model=model,
            query_preview=query[:100],
            status=status,
            duration_ms=round(duration_ms, 2),
            tokens_input=summary["total_tokens_input"],
            tokens_output=summary["total_tokens_output"],
            llm_calls_count=summary["llm_calls_count"],
            tool_calls_count=summary["tool_calls_count"],
            search_calls_count=sum(1 for t in summary["tool_calls"] if t["name"] in ("smart_search", "find_symbol")),
            warnings=warnings,
            spans=[],
            token_breakdown={
                "system_prompt_chars": len(system_prompt),
                "system_prompt_estimated_tokens": len(system_prompt) // 4,
                "history_chars": history_chars,
                "history_estimated_tokens": history_chars // 4,
                "user_query_chars": len(query),
                "tool_results_chars": tool_results_chars,
                "tool_results_pct": tool_results_pct,
            },
            search_details=[t for t in summary["tool_calls"] if t["name"] in ("smart_search", "find_symbol")],
        )

        from main import get_trace_buffer
        buf = get_trace_buffer()
        if buf is not None:
            buf.add(record)
    except Exception:
        pass  # Never break a request for tracing
```

- [ ] **Step 7: Verify the imports resolve**

Run: `cd backend && python -c "from agent import run_agent, run_agent_stream; print('OK')"`
Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add backend/agent.py
git commit -m "feat(observability): instrument agent pipeline with spans, callbacks, and trace recording"
```

---

## Task 12: FastAPI Middleware

**Files:**
- Create: `backend/observability/middleware.py`

- [ ] **Step 1: Create the request tracking middleware**

Create `backend/observability/middleware.py`:

```python
"""FastAPI middleware for request tracking.

Adds a unique request_id to every request and sets root span attributes
for the OTel auto-instrumented FastAPI span.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from opentelemetry import trace


class RequestTrackingMiddleware(BaseHTTPMiddleware):
    """Adds request_id and model info to the OTel root span."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("request.id", request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
```

- [ ] **Step 2: Verify import**

Run: `cd backend && python -c "from observability.middleware import RequestTrackingMiddleware; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/observability/middleware.py
git commit -m "feat(observability): add request tracking middleware"
```

---

## Task 13: Debug UI Routes and HTML Page

**Files:**
- Create: `backend/observability/debug_routes.py`
- Create: `backend/observability/debug_ui.html`

- [ ] **Step 1: Create the debug API routes**

Create `backend/observability/debug_routes.py`:

```python
"""FastAPI routes for the debug UI.

Serves:
- GET /debug/traces — HTML debug page
- GET /debug/traces/api — JSON list of recent traces
- GET /debug/traces/api/{request_id} — JSON detail for one trace
- GET /debug/metrics — JSON snapshot of current metrics
"""

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/debug", tags=["debug"])

_trace_buffer = None


def set_trace_buffer(buf) -> None:
    global _trace_buffer
    _trace_buffer = buf


def _get_buffer():
    if _trace_buffer is None:
        raise HTTPException(status_code=503, detail="Trace buffer not initialized")
    return _trace_buffer


@router.get("/traces", response_class=HTMLResponse)
async def debug_traces_page():
    """Serve the debug UI HTML page."""
    html_path = os.path.join(os.path.dirname(__file__), "debug_ui.html")
    with open(html_path, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@router.get("/traces/api")
async def list_traces(limit: int = 50):
    """Return recent trace summaries."""
    buf = _get_buffer()
    return {"traces": buf.list_recent(limit=limit)}


@router.get("/traces/api/{request_id}")
async def get_trace(request_id: str):
    """Return full trace detail for a specific request."""
    buf = _get_buffer()
    detail = buf.get(request_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return detail
```

- [ ] **Step 2: Create the debug UI HTML page**

Create `backend/observability/debug_ui.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Agent Debug — Trace Viewer</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <style>
    :root { --pico-font-size: 14px; }
    body { padding: 1rem; }
    .trace-table { width: 100%; font-size: 0.85rem; }
    .trace-table td, .trace-table th { padding: 0.4rem 0.6rem; }
    .clickable { cursor: pointer; }
    .clickable:hover { background: var(--pico-primary-focus); }
    .warning { color: #e67e22; font-weight: 600; }
    .error { color: #e74c3c; }
    .ok { color: #27ae60; }
    #detail-panel { display: none; margin-top: 1rem; }
    .bar-container { display: flex; height: 24px; border-radius: 4px; overflow: hidden; margin: 0.5rem 0; }
    .bar-segment { display: flex; align-items: center; justify-content: center; color: #fff; font-size: 0.7rem; min-width: 20px; }
    .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.5rem; margin: 1rem 0; }
    .metric-card { background: var(--pico-card-background-color); border: 1px solid var(--pico-muted-border-color); border-radius: 8px; padding: 0.8rem; text-align: center; }
    .metric-card .value { font-size: 1.8rem; font-weight: 700; }
    .metric-card .label { font-size: 0.75rem; color: var(--pico-muted-color); }
    pre.json { background: var(--pico-card-background-color); padding: 1rem; border-radius: 8px; overflow-x: auto; font-size: 0.8rem; max-height: 400px; }
    .tool-table, .search-table { font-size: 0.8rem; }
  </style>
</head>
<body>
  <main class="container">
    <h1>🔍 Agent Debug — Trace Viewer</h1>
    <p id="status">Loading traces…</p>

    <table class="trace-table" id="trace-list">
      <thead>
        <tr>
          <th>Time</th>
          <th>ID</th>
          <th>Model</th>
          <th>Query</th>
          <th>Tokens</th>
          <th>LLM</th>
          <th>Tools</th>
          <th>Latency</th>
          <th>Status</th>
          <th>⚠️</th>
        </tr>
      </thead>
      <tbody id="trace-body"></tbody>
    </table>

    <div id="detail-panel">
      <hr>
      <h2>Request Detail: <code id="detail-id"></code></h2>

      <div class="metric-grid" id="metrics-grid"></div>

      <h3>Token Breakdown</h3>
      <div class="bar-container" id="token-bar"></div>
      <small id="token-legend"></small>

      <h3>Tool Calls</h3>
      <table class="tool-table">
        <thead><tr><th>Tool</th><th>Duration</th><th>Output Size</th></tr></thead>
        <tbody id="tool-body"></tbody>
      </table>

      <h3>Warnings</h3>
      <ul id="warnings-list"></ul>

      <details>
        <summary>Raw Trace JSON</summary>
        <pre class="json" id="raw-json"></pre>
      </details>
    </div>
  </main>

  <script>
    const API = '/debug/traces/api';
    const tbody = document.getElementById('trace-body');
    const statusEl = document.getElementById('status');

    async function loadTraces() {
      try {
        const res = await fetch(API);
        const data = await res.json();
        const traces = data.traces || [];
        statusEl.textContent = `${traces.length} recent traces`;
        tbody.innerHTML = '';
        traces.forEach(t => {
          const tr = document.createElement('tr');
          tr.className = 'clickable';
          tr.onclick = () => loadDetail(t.request_id);
          const time = new Date(t.timestamp).toLocaleTimeString();
          const statusCls = t.status === 'ok' ? 'ok' : 'error';
          tr.innerHTML = `
            <td>${time}</td>
            <td><code>${t.request_id}</code></td>
            <td>${t.model}</td>
            <td>${escHtml(t.query_preview.substring(0, 60))}</td>
            <td>${t.tokens_total.toLocaleString()}</td>
            <td>${t.llm_calls_count}</td>
            <td>${t.tool_calls_count}</td>
            <td>${(t.duration_ms / 1000).toFixed(1)}s</td>
            <td class="${statusCls}">${t.status}</td>
            <td>${t.warnings_count > 0 ? '⚠️' + t.warnings_count : ''}</td>
          `;
          tbody.appendChild(tr);
        });
      } catch (e) {
        statusEl.textContent = 'Failed to load traces: ' + e.message;
      }
    }

    async function loadDetail(id) {
      const panel = document.getElementById('detail-panel');
      try {
        const res = await fetch(`${API}/${id}`);
        const d = await res.json();
        panel.style.display = 'block';
        document.getElementById('detail-id').textContent = id;

        // Metrics grid
        const grid = document.getElementById('metrics-grid');
        grid.innerHTML = [
          metric('Tokens In', d.tokens_input.toLocaleString()),
          metric('Tokens Out', d.tokens_output.toLocaleString()),
          metric('Total Tokens', d.tokens_total.toLocaleString()),
          metric('LLM Calls', d.llm_calls_count),
          metric('Tool Calls', d.tool_calls_count),
          metric('Latency', (d.duration_ms / 1000).toFixed(1) + 's'),
        ].join('');

        // Token breakdown bar
        const tb = d.token_breakdown || {};
        const parts = [
          { label: 'System', val: tb.system_prompt_estimated_tokens || 0, color: '#3498db' },
          { label: 'History', val: tb.history_estimated_tokens || 0, color: '#2ecc71' },
          { label: 'Query', val: (tb.user_query_chars || 0) / 4, color: '#9b59b6' },
          { label: 'Tools', val: (tb.tool_results_chars || 0) / 4, color: '#e67e22' },
        ];
        const total = parts.reduce((s, p) => s + p.val, 0) || 1;
        const bar = document.getElementById('token-bar');
        bar.innerHTML = parts.map(p =>
          `<div class="bar-segment" style="width:${Math.max(p.val/total*100, 2)}%;background:${p.color}">${p.label}</div>`
        ).join('');
        document.getElementById('token-legend').textContent = parts.map(p => `${p.label}: ~${Math.round(p.val)}`).join(' | ');

        // Tool calls
        const toolBody = document.getElementById('tool-body');
        const tools = d.search_details || [];
        toolBody.innerHTML = tools.length
          ? tools.map(t => `<tr><td>${t.name}</td><td>${(t.duration_seconds||0).toFixed(2)}s</td><td>${(t.output_size||0).toLocaleString()} chars</td></tr>`).join('')
          : '<tr><td colspan="3">No tool calls recorded</td></tr>';

        // Warnings
        const wl = document.getElementById('warnings-list');
        wl.innerHTML = (d.warnings || []).map(w => `<li class="warning">${escHtml(w)}</li>`).join('') || '<li>None</li>';

        // Raw JSON
        document.getElementById('raw-json').textContent = JSON.stringify(d, null, 2);

        panel.scrollIntoView({ behavior: 'smooth' });
      } catch (e) {
        panel.innerHTML = '<p class="error">Failed to load detail: ' + e.message + '</p>';
      }
    }

    function metric(label, value) {
      return `<div class="metric-card"><div class="value">${value}</div><div class="label">${label}</div></div>`;
    }

    function escHtml(s) {
      const d = document.createElement('div');
      d.textContent = s;
      return d.innerHTML;
    }

    loadTraces();
    setInterval(loadTraces, 10000);
  </script>
</body>
</html>
```

- [ ] **Step 3: Verify imports**

Run: `cd backend && python -c "from observability.debug_routes import router; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/observability/debug_routes.py backend/observability/debug_ui.html
git commit -m "feat(observability): add debug UI routes and HTML page"
```

---

## Task 14: Wire Everything into main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add observability initialization and middleware to main.py**

Add these imports at the top of `backend/main.py` (after existing imports):

```python
from observability import init_observability
from observability.middleware import RequestTrackingMiddleware
from observability.trace_buffer import TraceBuffer
from observability.debug_routes import router as debug_router, set_trace_buffer
```

Add a module-level trace buffer variable after the `_index_status` dict:

```python
_trace_buffer: TraceBuffer | None = None


def get_trace_buffer() -> TraceBuffer | None:
    return _trace_buffer
```

Add these lines right after the `app = FastAPI(...)` line and before the CORS middleware:

```python
# --- Observability ---
init_observability(app=app)
app.add_middleware(RequestTrackingMiddleware)

from security import settings as _settings
if _settings.debug_ui_enabled:
    _trace_buffer = TraceBuffer(max_size=_settings.debug_trace_buffer_size)
    set_trace_buffer(_trace_buffer)
    app.include_router(debug_router)
```

- [ ] **Step 2: Verify the app starts without errors**

Run: `cd backend && python -c "from main import app; print('Routes:', [r.path for r in app.routes][:10])"`
Expected: Output shows routes including `/debug/traces`

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat(observability): wire observability into FastAPI app startup"
```

---

## Task 15: Docker Compose — Jaeger, Prometheus, Grafana

**Files:**
- Modify: `docker-compose.yml`
- Create: `backend/observability/prometheus.yml`
- Create: `backend/observability/grafana-dashboards/agent-overview.json`
- Create: `backend/observability/grafana-dashboards/dashboard.yml`

- [ ] **Step 1: Add observability services to docker-compose.yml**

Add these services to `docker-compose.yml` (after the existing `backend` service, before the `volumes:` section):

```yaml
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"
      - "4317:4317"
    environment:
      - COLLECTOR_OTLP_ENABLED=true
    restart: unless-stopped
    profiles:
      - observability

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./backend/observability/prometheus.yml:/etc/prometheus/prometheus.yml
    restart: unless-stopped
    profiles:
      - observability

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/etc/grafana/provisioning/dashboards/agent-overview.json
    volumes:
      - ./backend/observability/grafana-dashboards:/etc/grafana/provisioning/dashboards
    restart: unless-stopped
    profiles:
      - observability
```

Also update the `backend` service to add Jaeger endpoint config. Add to the backend's `environment:` list:

```yaml
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
```

- [ ] **Step 2: Create Prometheus config**

Create `backend/observability/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "wiki-agent-backend"
    static_configs:
      - targets: ["backend:8001"]
    metrics_path: "/metrics"
```

- [ ] **Step 3: Create Grafana dashboard provisioning config**

Create `backend/observability/grafana-dashboards/dashboard.yml`:

```yaml
apiVersion: 1

providers:
  - name: "Agent Dashboards"
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /etc/grafana/provisioning/dashboards
      foldersFromFilesStructure: false
```

- [ ] **Step 4: Create the Grafana dashboard JSON**

Create `backend/observability/grafana-dashboards/agent-overview.json`:

```json
{
  "dashboard": {
    "title": "Wiki Agent Overview",
    "uid": "wiki-agent-overview",
    "timezone": "browser",
    "panels": [
      {
        "title": "Request Rate",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 8, "x": 0, "y": 0},
        "targets": [{"expr": "rate(agent_requests_total[5m])", "legendFormat": "{{model}} / {{status}}"}]
      },
      {
        "title": "Request Latency P95",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 8, "x": 8, "y": 0},
        "targets": [{"expr": "histogram_quantile(0.95, rate(agent_request_duration_seconds_bucket[5m]))", "legendFormat": "p95"}]
      },
      {
        "title": "Tokens per Request (Input)",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 8, "x": 16, "y": 0},
        "targets": [{"expr": "rate(agent_llm_tokens_input_total[5m])", "legendFormat": "{{model}}"}]
      },
      {
        "title": "Search Calls by Tier",
        "type": "piechart",
        "gridPos": {"h": 8, "w": 8, "x": 0, "y": 8},
        "targets": [{"expr": "agent_search_calls_total", "legendFormat": "{{tier}}"}]
      },
      {
        "title": "Embedding Cache Hit Rate",
        "type": "gauge",
        "gridPos": {"h": 8, "w": 8, "x": 8, "y": 8},
        "targets": [{"expr": "agent_embedding_cache_hits_total / (agent_embedding_cache_hits_total + agent_embedding_cache_misses_total)", "legendFormat": "hit_rate"}]
      },
      {
        "title": "Tool Call Duration P95",
        "type": "bargauge",
        "gridPos": {"h": 8, "w": 8, "x": 16, "y": 8},
        "targets": [{"expr": "histogram_quantile(0.95, rate(agent_tool_call_duration_seconds_bucket[5m]))", "legendFormat": "{{tool_name}}"}]
      }
    ],
    "templating": {"list": []},
    "time": {"from": "now-1h", "to": "now"},
    "refresh": "30s"
  }
}
```

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml backend/observability/prometheus.yml backend/observability/grafana-dashboards/
git commit -m "feat(observability): add Jaeger, Prometheus, and Grafana to Docker Compose"
```

---

## Task 16: Structured Logging with structlog

**Files:**
- Modify: `backend/observability/setup.py`

- [ ] **Step 1: Add structlog configuration to the setup module**

Add this function to the end of `backend/observability/setup.py`:

```python
def configure_structlog() -> None:
    """Configure structlog for JSON-structured logging with trace correlation."""
    import structlog
    from opentelemetry import trace as otl_trace

    def add_trace_context(logger, method_name, event_dict):
        span = otl_trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
        return event_dict

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            add_trace_context,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

Then add `configure_structlog()` as the last line inside `init_observability()`, right before `_initialized = True`:

```python
    configure_structlog()

    _initialized = True
```

- [ ] **Step 2: Verify structlog works**

Run: `cd backend && python -c "from observability.setup import init_observability, configure_structlog; configure_structlog(); import structlog; log = structlog.get_logger(); log.info('test', key='value')"`
Expected: JSON output like `{"key": "value", "level": "info", "timestamp": "...", "event": "test"}`

- [ ] **Step 3: Commit**

```bash
git add backend/observability/setup.py
git commit -m "feat(observability): add structlog JSON logging with trace correlation"
```

---

## Task 17: Update Package Init Exports

**Files:**
- Modify: `backend/observability/__init__.py`

- [ ] **Step 1: Update the package init with all public exports**

Replace `backend/observability/__init__.py` with:

```python
"""Observability package for the wiki agent backend.

Provides OpenTelemetry tracing, Prometheus metrics, structured logging,
and a debug UI for per-request inspection.
"""

from observability.setup import init_observability, get_tracer, get_meter
from observability.trace_buffer import TraceBuffer, TraceRecord
from observability.callbacks import OTelCallbackHandler
from observability.spans import search_span, embedding_span, agent_span, timed_span
```

- [ ] **Step 2: Verify all imports**

Run: `cd backend && python -c "from observability import init_observability, get_tracer, get_meter, TraceBuffer, TraceRecord, OTelCallbackHandler, search_span, embedding_span, agent_span, timed_span; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/observability/__init__.py
git commit -m "feat(observability): update package init with all public exports"
```

---

## Task 18: Run All Tests and Validate

**Files:** No changes — validation only.

- [ ] **Step 1: Run all observability tests**

Run: `cd backend && python observability/test_trace_buffer.py && python observability/test_callbacks.py && python observability/test_metrics.py`
Expected: All tests pass

- [ ] **Step 2: Run all existing backend tests**

Run: `cd backend && python search/test_orchestrator.py && python search/test_lexical.py && python search/test_semantic.py && python search/test_chunker.py && python search/test_registry.py && python search/test_symbols.py`
Expected: All existing tests still pass (some may skip if Ollama not available)

- [ ] **Step 3: Verify the FastAPI app loads**

Run: `cd backend && python -c "from main import app; routes = [r.path for r in app.routes if hasattr(r, 'path')]; print('Debug routes:', [r for r in routes if 'debug' in r]); print('Total routes:', len(routes))"`
Expected: Shows debug routes including `/debug/traces`, `/debug/traces/api`, `/debug/traces/api/{request_id}`

- [ ] **Step 4: Final commit with all tests green**

```bash
git add -A
git commit -m "feat(observability): complete backend observability implementation

Adds OpenTelemetry tracing, Prometheus metrics, LangChain callback
handler, search pipeline instrumentation, in-memory trace buffer,
debug UI, and structlog JSON logging.

See: docs/superpowers/specs/2026-04-11-backend-observability-design.md"
```
