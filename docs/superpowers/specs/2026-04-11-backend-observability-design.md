# Backend Observability Design

**Date**: 2026-04-11  
**Scope**: Backend FastAPI wiki agent (`backend/`)  
**Status**: Approved

## Problem

The backend agent is opaque. There is no visibility into:
- How many model calls per request, and how many tokens each consumes
- Which search tiers fire (lexical, semantic, symbol) and whether they help
- How much of the prompt is occupied by retrieval results vs. history vs. system prompt
- Where latency comes from (LLM API? embedding? search? tool execution?)
- Whether the embedding cache is effective
- Whether retrieval is returning useful results or wasting tokens

The system uses basic Python `logging.getLogger` in search modules. There is no tracing, no metrics, no token counting, no cost tracking, and no debug UI.

## Approach

**OpenTelemetry + Prometheus + Grafana + Jaeger + custom debug API.**

Instrument the backend with the OpenTelemetry Python SDK. Each request creates a root trace with child spans for every pipeline stage. Export traces to Jaeger (dev) or any OTLP-compatible backend (prod). Expose a Prometheus metrics endpoint. Build Grafana dashboards. Serve a lightweight debug HTML page from FastAPI for per-request inspection.

### Why This Approach

1. The 3-tier search orchestrator (lexical → semantic → symbol) is the most opaque part and needs custom spans — LangSmith would not see these internals.
2. OTel auto-instruments FastAPI and httpx (Ollama embedding calls) out of the box.
3. Vendor-neutral: one instrumentation works with Jaeger (dev), Datadog, Honeycomb, or any OTLP backend (prod).
4. A custom debug page gives immediate per-request inspection without depending on external UIs.

### Constraints

- Backend only (not Hermes agent)
- Works in both local Docker Compose and cloud deployment
- Self-hosted for dev, SaaS-ready for prod
- Low traffic: 10–1000 requests/day — trace 100% of requests
- Token counts from API responses (no tiktoken), rough estimates are sufficient
- Debug UI: a FastAPI-served HTML page behind JWT auth

## Architecture

### Stack

| Layer | Dev (Docker Compose) | Prod (Cloud) |
|-------|---------------------|-------------|
| Tracing | Jaeger all-in-one | Any OTLP backend (Datadog, Honeycomb, etc.) |
| Metrics | Prometheus container | Managed Prometheus / Cloud Monitoring |
| Dashboards | Grafana container | Managed Grafana / cloud equivalent |
| Debug UI | FastAPI `/debug/traces` | Same (auth-gated) |
| Logs | structlog JSON → stdout | Same → log aggregator |

### New Dependencies

```
opentelemetry-api
opentelemetry-sdk
opentelemetry-exporter-otlp-proto-grpc
opentelemetry-instrumentation-fastapi
opentelemetry-instrumentation-httpx
structlog
```

### New Containers (Docker Compose, dev only)

```yaml
jaeger:
  image: jaegertracing/all-in-one:latest
  ports:
    - "16686:16686"   # Jaeger UI
    - "4317:4317"     # OTLP gRPC
prometheus:
  image: prom/prometheus:latest
  ports:
    - "9090:9090"
  volumes:
    - ./backend/observability/prometheus.yml:/etc/prometheus/prometheus.yml
grafana:
  image: grafana/grafana:latest
  ports:
    - "3000:3000"
  volumes:
    - ./backend/observability/grafana-dashboards:/etc/grafana/provisioning/dashboards
```

### Trace Hierarchy Per Request

```
[root] POST /chat or /chat/stream
 ├── build_system_prompt
 │    attrs: prompt.char_count, prompt.estimated_tokens, page_context.present
 ├── format_history
 │    attrs: history.total_messages, history.kept_messages, history.estimated_tokens
 ├── agent_invoke (LangGraph ReAct loop)
 │    ├── llm_call [1]
 │    │    attrs: model, tokens.input, tokens.output, finish_reason
 │    ├── tool:smart_search
 │    │    ├── classify_query
 │    │    │    attrs: query_type
 │    │    ├── repo_targeting
 │    │    │    attrs: targets, target_count
 │    │    ├── search.lexical
 │    │    │    attrs: paths_count, results_count, duration_ms
 │    │    ├── search.semantic
 │    │    │    ├── embedding.generate
 │    │    │    │    attrs: model, batch_size, cache_hits, cache_misses, api_duration_ms
 │    │    │    attrs: collection, results_count, duration_ms
 │    │    ├── search.symbol (if triggered)
 │    │    │    attrs: results_count
 │    │    └── format_results
 │    │         attrs: results_count, total_chars, truncated
 │    ├── tool:read_workspace_file
 │    │    attrs: file_path, output_size, truncated
 │    ├── llm_call [2]
 │    │    attrs: model, tokens.input, tokens.output, finish_reason
 │    └── ...
 └── stream_response
      attrs: token_count, tool_calls_count, citations_count
```

## Instrumentation Plan

### New Files

| File | Purpose |
|------|---------|
| `backend/observability/__init__.py` | Package init |
| `backend/observability/setup.py` | OTel SDK initialization, tracer/meter providers |
| `backend/observability/spans.py` | Span helper functions and context managers |
| `backend/observability/metrics.py` | Metric instrument definitions |
| `backend/observability/callbacks.py` | LangChain OTel callback handler |
| `backend/observability/middleware.py` | FastAPI middleware for request tracking |
| `backend/observability/trace_buffer.py` | In-memory ring buffer for debug UI |
| `backend/observability/debug_routes.py` | FastAPI routes for debug UI |
| `backend/observability/debug_ui.html` | Single-file HTML + JS debug page |
| `backend/observability/prometheus.yml` | Prometheus scrape config (dev) |
| `backend/observability/grafana-dashboards/` | Pre-built Grafana dashboard JSON |

### Modified Files

| File | Changes |
|------|---------|
| `backend/main.py` | Add OTel middleware, debug routes, startup init |
| `backend/agent.py` | Add spans around prompt build, history format; pass callback handler to LangGraph agent |
| `backend/search_tools.py` | Add spans around smart_search, find_symbol, read_code_section |
| `backend/search/orchestrator.py` | Add spans around search tiers, record search quality attributes |
| `backend/search/semantic.py` | Add spans around embedding calls, ChromaDB queries |
| `backend/search/lexical.py` | Add span around ripgrep execution |
| `backend/pyproject.toml` | Add OTel + structlog dependencies |
| `docker-compose.yml` | Add Jaeger, Prometheus, Grafana services |

### Stage-by-Stage Detail

#### 1. Request Entry (`main.py`)

Auto-instrumented by `opentelemetry-instrumentation-fastapi`. Custom middleware adds:

```python
# Attributes added to root span
span.set_attribute("request.id", request_id)      # UUID per request
span.set_attribute("request.model", model_id)      # qwen / deepseek / openai
span.set_attribute("request.query_preview", query[:100])
span.set_attribute("request.history_length", len(history))
span.set_attribute("request.page_context", bool(page_context))
```

#### 2. System Prompt Assembly (`agent.py:build_system_prompt`)

```python
with tracer.start_as_current_span("build_system_prompt") as span:
    prompt = build_system_prompt(page_context)
    span.set_attribute("prompt.char_count", len(prompt))
    span.set_attribute("prompt.estimated_tokens", len(prompt) // 4)
    span.set_attribute("prompt.page_context", bool(page_context))
```

#### 3. History Formatting (`agent.py:_format_history`)

```python
with tracer.start_as_current_span("format_history") as span:
    result = _format_history(chat_history)
    total_chars = sum(len(c) for _, c in result)
    span.set_attribute("history.total_messages", len(chat_history))
    span.set_attribute("history.kept_messages", len(result))
    span.set_attribute("history.truncated", len(result) < len(chat_history))
    span.set_attribute("history.estimated_tokens", total_chars // 4)
```

#### 4. LLM Calls (LangChain Callback Handler)

A custom `OTelCallbackHandler(BaseCallbackHandler)`:

```python
def on_llm_start(self, serialized, prompts, **kwargs):
    span = tracer.start_span("llm_call")
    span.set_attribute("llm.model", self.model_id)
    prompt_text = "".join(str(p) for p in prompts)
    span.set_attribute("llm.prompt.estimated_tokens", len(prompt_text) // 4)
    self._llm_spans[run_id] = span

def on_llm_end(self, response, **kwargs):
    span = self._llm_spans.pop(run_id)
    usage = response.llm_output.get("token_usage", {}) if response.llm_output else {}
    span.set_attribute("llm.tokens.input", usage.get("prompt_tokens", 0))
    span.set_attribute("llm.tokens.output", usage.get("completion_tokens", 0))
    span.set_attribute("llm.tokens.total", usage.get("total_tokens", 0))
    llm_calls_counter.add(1, {"model": self.model_id})
    tokens_input_counter.add(usage.get("prompt_tokens", 0), {"model": self.model_id})
    tokens_output_counter.add(usage.get("completion_tokens", 0), {"model": self.model_id})
    span.end()
```

#### 5. Tool Calls (LangChain Callback Handler)

```python
def on_tool_start(self, serialized, input_str, **kwargs):
    span = tracer.start_span(f"tool:{tool_name}")
    span.set_attribute("tool.name", tool_name)
    span.set_attribute("tool.input_preview", str(input_str)[:500])
    self._tool_spans[run_id] = (span, time.monotonic())

def on_tool_end(self, output, **kwargs):
    span, start_time = self._tool_spans.pop(run_id)
    duration_ms = (time.monotonic() - start_time) * 1000
    span.set_attribute("tool.output_size", len(str(output)))
    span.set_attribute("tool.duration_ms", duration_ms)
    tool_calls_counter.add(1, {"tool": tool_name})
    tool_duration_histogram.record(duration_ms, {"tool": tool_name})
    span.end()
```

#### 6. Search Orchestrator (`search/orchestrator.py:search`)

```python
with tracer.start_as_current_span("search.orchestrate") as span:
    span.set_attribute("search.query", query[:200])
    span.set_attribute("search.scope", scope)
    span.set_attribute("search.query_type", query_type)
    # ... after search completes:
    span.set_attribute("search.cache_hit", cache_hit)
    span.set_attribute("search.tiers_used", tiers_used)
    span.set_attribute("search.lexical_results", lexical_count)
    span.set_attribute("search.semantic_results", semantic_count)
    span.set_attribute("search.total_raw_results", total_raw)
    span.set_attribute("search.unique_results", unique_count)
    span.set_attribute("search.results_chars", len(result))
    span.set_attribute("search.distinct_files", distinct_files)
    span.set_attribute("search.early_stopped", early_stopped)
    search_calls_counter.add(1, {"tier": "orchestrate"})
```

#### 7. Embedding Calls (`search/semantic.py:OllamaEmbeddingFunction.__call__`)

```python
with tracer.start_as_current_span("embedding.generate") as span:
    span.set_attribute("embedding.model", self._model)
    span.set_attribute("embedding.requested", len(input))
    span.set_attribute("embedding.cache_hits", cache_hit_count)
    span.set_attribute("embedding.cache_misses", len(uncached))
    # ... after API call:
    span.set_attribute("embedding.api_duration_ms", api_duration)
    embedding_cache_hits.add(cache_hit_count)
    embedding_cache_misses.add(len(uncached))
    embedding_calls_counter.add(1)
```

## Token Observability

### Token Counting Strategy

- **Primary source**: `response.response_metadata["token_usage"]` from ChatOpenAI. All three providers (OpenAI, DeepSeek, Qwen) return usage data.
- **Fallback estimate**: `len(text) // 4` for pre-call prompt size warnings. Not used for reporting.
- **No tiktoken**: Three different model families make tokenizer-exact counts impractical. API-reported counts are authoritative.

### Per-Request Token Summary

Attached as span attributes to the root request span and stored in the trace buffer:

```json
{
  "tokens": {
    "total_input": 4200,
    "total_output": 850,
    "total": 5050,
    "llm_calls_count": 3,
    "per_call": [
      {"call_index": 1, "input": 2800, "output": 200, "model": "qwen-plus"},
      {"call_index": 2, "input": 3100, "output": 350, "model": "qwen-plus"},
      {"call_index": 3, "input": 3500, "output": 300, "model": "qwen-plus"}
    ]
  },
  "prompt_composition": {
    "system_prompt_chars": 3200,
    "system_prompt_estimated_tokens": 800,
    "history_chars": 1200,
    "history_estimated_tokens": 300,
    "user_query_chars": 150,
    "user_query_estimated_tokens": 38,
    "tool_results_chars": 4800,
    "tool_results_estimated_tokens": 1200,
    "tool_results_pct": 51.2
  }
}
```

### Waste Detection Signals

| Signal | Threshold | Meaning |
|--------|-----------|---------|
| `tool_results_pct > 60%` | Warning | Retrieval dominating prompt context |
| `tokens.total_input > 6000` | Warning | Large prompt — check if search results or history can be trimmed |
| `llm_calls_count > 5` | Warning | Agent may be looping |
| `tokens increasing across calls` | Info | Tool results accumulating in context |
| `history.truncated == true` | Info | History was trimmed — conversation may lose context |

## Retrieval Quality Observability

### Per-Search Attributes

```json
{
  "search.query": "how does the permission model work",
  "search.scope": "auto",
  "search.query_type": "concept",
  "search.cache_hit": false,
  "search.tiers_used": ["lexical", "semantic"],
  "search.lexical_results": 3,
  "search.semantic_results": 5,
  "search.total_raw_results": 8,
  "search.unique_results": 6,
  "search.results_returned": 6,
  "search.results_chars": 1847,
  "search.results_truncated": false,
  "search.early_stopped": false,
  "search.distinct_files": 4
}
```

### Retrieval Quality Signals

| Signal | Condition | Meaning |
|--------|-----------|---------|
| Empty search | `total_raw_results == 0` | Query too specific or index stale |
| Narrow coverage | `distinct_files == 1` | All results from one file |
| Char limit hit | `results_chars / max_chars > 0.9` | May be truncating useful content |
| Semantic skipped | `early_stopped && tiers == [lexical]` | Good for speed, verify quality |
| Low semantic scores | Average score < 0.3 | Semantic results may not be relevant |

### Embedding Cache Performance

```json
{
  "embedding.model": "all-minilm",
  "embedding.cache.size": 85,
  "embedding.cache.max_size": 128,
  "embedding.cache.hit_rate": 0.72,
  "embedding.cache.total_hits": 340,
  "embedding.cache.total_misses": 132
}
```

## Debug UI

### Implementation

A FastAPI-served HTML page at `/debug/traces`, protected by the same JWT auth as other endpoints.

**Backend data store**: In-memory ring buffer holding the last 200 completed request traces. Each trace is a `TraceRecord` dataclass containing the full span tree, token summary, search details, and warnings.

### API Endpoints

```
GET  /debug/traces          → HTML debug page
GET  /debug/traces/api      → JSON: recent traces (summary list)
GET  /debug/traces/api/{id} → JSON: full trace detail for one request
GET  /debug/metrics         → JSON: current metric counters snapshot
```

### Debug Page Features

1. **Recent requests table**: timestamp, request_id, model, query preview, total tokens, latency, status, tool call count, warnings
2. **Request detail view** (click a row):
   - **Timeline**: Horizontal bar chart of span durations
   - **Token breakdown**: Input vs output, system prompt vs history vs tool results
   - **Search details**: Per-search-call table with query, tiers, results count, cache hit, latency
   - **Tool calls**: Table with name, input preview, output size, duration
   - **Embedding stats**: Cache hit rate, API call count, latency
   - **Warnings**: Any triggered threshold warnings
   - **Raw trace**: Collapsible JSON span tree

**Tech**: Single HTML file with inline CSS (Pico CSS via CDN) and vanilla JavaScript. No build step.

## Metrics (Prometheus)

### Counters

| Metric | Labels | Description |
|--------|--------|-------------|
| `agent_requests_total` | model, status, endpoint | Total requests |
| `agent_llm_calls_total` | model | LLM invocations |
| `agent_llm_tokens_input_total` | model | Input tokens consumed |
| `agent_llm_tokens_output_total` | model | Output tokens generated |
| `agent_search_calls_total` | tier | Search calls by tier |
| `agent_embedding_calls_total` | | Embedding API calls |
| `agent_embedding_cache_hits_total` | | Embedding cache hits |
| `agent_embedding_cache_misses_total` | | Embedding cache misses |
| `agent_tool_calls_total` | tool_name | Tool invocations |

### Histograms

| Metric | Labels | Buckets | Description |
|--------|--------|---------|-------------|
| `agent_request_duration_seconds` | model, endpoint | 0.5, 1, 2, 5, 10, 20, 30, 60 | Request latency |
| `agent_llm_call_duration_seconds` | model | 0.5, 1, 2, 5, 10, 20 | LLM API latency |
| `agent_tool_call_duration_seconds` | tool_name | 0.01, 0.05, 0.1, 0.5, 1, 5 | Tool execution time |
| `agent_prompt_tokens` | model | 500, 1k, 2k, 4k, 6k, 8k | Prompt size distribution |
| `agent_search_results_count` | tier | 0, 1, 2, 3, 5, 8, 10, 15 | Results per search |
| `agent_embedding_api_duration_seconds` | | 0.01, 0.05, 0.1, 0.5, 1 | Embedding API latency |

## Grafana Dashboards

### Panel Layout

**Row 1: Request Overview**
- Request rate time series (by model)
- Error rate time series
- P50/P95/P99 request latency time series

**Row 2: Token Usage**
- Tokens per request histogram
- Input vs output tokens stacked bar (by model)
- Average prompt size gauge

**Row 3: Search & Retrieval**
- Search calls by tier (stacked area)
- Average results per search (time series)
- Embedding cache hit rate (gauge)
- Embedding API latency P95

**Row 4: Tool Usage**
- Tool call frequency (bar chart by tool name)
- Tool latency P95 (bar chart by tool name)

## Optimization Hooks

### Warnings (logged + shown in debug UI)

| Condition | Level | Message |
|-----------|-------|---------|
| `prompt_tokens > 6000` | WARN | Large prompt: {n} estimated tokens |
| `tool_results_pct > 60%` | WARN | Retrieval dominates prompt: {pct}% |
| `search.total_raw_results == 0` | WARN | Empty search for: {query_preview} |
| `embedding.cache_hit_rate < 0.5` (hourly) | WARN | Low embedding cache hit rate: {rate} |
| `llm_calls > 5` per request | WARN | Many LLM rounds: {n} calls |
| `request_duration > 30s` | WARN | Slow request: {duration}s |
| `search.distinct_files == 1` | INFO | Narrow search coverage |

### Grafana Alert Rules (optional, production)

| Alert | Condition | Severity |
|-------|-----------|----------|
| High latency | P95 request duration > 20s for 5min | Warning |
| Error spike | Error rate > 5% for 5min | Critical |
| Token spike | P95 input tokens > 8000 for 15min | Warning |

### Future Optimization Candidates

Ranked by expected impact:

1. **Prompt size reduction**: Use token metrics to identify oversized system prompts, excessive history, or too many search results
2. **Search result quality**: Use retrieval metrics to tune `SEARCH_MAX_RESULTS`, `SEARCH_MAX_CHARS`, and early stopping thresholds
3. **Embedding cache tuning**: Use cache hit rate to decide if cache size should increase or if queries are too diverse to cache
4. **Model routing**: Use per-model token/latency data to route simple queries to cheaper models
5. **History compression**: Use history token metrics to decide when to summarize instead of truncate

## Structured Logging

Replace basic `logging.getLogger` with `structlog` JSON output, correlated to trace IDs:

```json
{
  "timestamp": "2026-04-11T13:45:22.123Z",
  "level": "info",
  "event": "search_complete",
  "request_id": "abc-123",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "search.query": "permission model",
  "search.tiers_used": ["lexical", "semantic"],
  "search.results_count": 6,
  "search.duration_ms": 145
}
```

Every log line includes `request_id`, `trace_id`, and `span_id` for correlation.

## Configuration

### Environment Variables

```bash
# Observability toggle
OTEL_ENABLED=true                              # Enable/disable all OTel instrumentation
OTEL_SERVICE_NAME=wiki-agent-backend
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317 # OTLP gRPC endpoint
OTEL_METRICS_EXPORTER=prometheus               # or "otlp" for production

# Debug UI
DEBUG_UI_ENABLED=true                          # Enable /debug/traces endpoints
DEBUG_TRACE_BUFFER_SIZE=200                    # Max traces in memory

# Warning thresholds
WARN_PROMPT_TOKENS=6000
WARN_TOOL_RESULTS_PCT=60
WARN_LLM_CALLS_MAX=5
WARN_REQUEST_DURATION_SECONDS=30
```

## Acceptance Criteria

1. Every `/chat` and `/chat/stream` request produces an OTel trace with the hierarchy described above
2. Token counts (input/output) are captured per LLM call from API response metadata
3. Search calls record tier used, results count, cache hit/miss, and latency
4. Embedding calls record cache hit/miss count and API latency
5. Tool calls record name, duration, and output size
6. Prometheus metrics are exposed at `/metrics` and match the table above
7. Debug UI at `/debug/traces` shows recent requests with drill-down to timeline, token breakdown, and search details
8. Structured JSON logs include `request_id` and `trace_id` correlation
9. Warning thresholds fire and are visible in both logs and debug UI
10. All instrumentation is behind an `OTEL_ENABLED` toggle — setting it to `false` disables all tracing/metrics with negligible performance impact
11. Docker Compose includes optional Jaeger + Prometheus + Grafana services
12. Existing tests still pass with instrumentation enabled

## Risks and Tradeoffs

| Risk | Mitigation |
|------|------------|
| Performance overhead from tracing | OTel SDK is lightweight; all spans are async-exported. Toggle via `OTEL_ENABLED`. |
| In-memory trace buffer uses RAM | Capped at 200 traces (~2MB). Configurable. |
| Token counts may be missing for some providers | Fallback to `len(text) // 4` estimate; log a warning. |
| Debug UI exposes request data | Protected by same JWT auth. Can be disabled via `DEBUG_UI_ENABLED`. |
| Extra Docker containers for dev | Jaeger/Prometheus/Grafana are optional; backend works without them. |
| LangChain callback handler compatibility | Test with current LangGraph version; callback API is stable. |
| structlog migration | Gradual: existing `logging.getLogger` calls still work via structlog's stdlib integration. |

## Implementation Order

1. `observability/setup.py` — OTel SDK init, tracer/meter providers, toggle
2. `observability/metrics.py` — Metric instrument definitions
3. `observability/spans.py` — Span helper context managers
4. `observability/middleware.py` — FastAPI middleware for request tracking
5. `observability/callbacks.py` — LangChain OTel callback handler
6. Instrument `agent.py` — prompt build, history format, agent invoke
7. Instrument `search/orchestrator.py` — search tier spans and attributes
8. Instrument `search/semantic.py` — embedding and ChromaDB spans
9. Instrument `search/lexical.py` — lexical search span
10. Instrument `search_tools.py` — tool-level spans
11. `observability/trace_buffer.py` — In-memory ring buffer
12. `observability/debug_routes.py` — Debug API endpoints
13. `observability/debug_ui.html` — Debug page HTML/JS
14. Wire into `main.py` — startup, middleware, routes
15. Update `pyproject.toml` — new dependencies
16. Update `docker-compose.yml` — Jaeger, Prometheus, Grafana
17. Add Prometheus config and Grafana dashboard JSON
18. Structured logging migration (structlog)
19. Testing and validation
