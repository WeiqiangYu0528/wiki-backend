# Agent Observability Design Spec

**Date:** 2026-04-11
**Status:** Draft
**Scope:** Backend agent system (`backend/`) only

## Problem

The FastAPI + LangGraph agent system has zero observability. There is no way to see how many LLM calls are made per request, how many tokens are consumed, which tools are expensive, whether retrieval is useful or wasteful, or where latency comes from. This makes it impossible to debug, measure, or optimize the system.

## Proposed Approach

Add full observability using **OpenTelemetry + Jaeger + Prometheus + Grafana**, with a supplementary **SQLite summary table** for fast local queries.

## Assumptions

1. Scope is the `backend/` FastAPI + LangGraph agent only.
2. Deployment: Docker Compose, running locally and on GCP.
3. Request volume: ~100/day — enough to justify dashboards, not enough to worry about trace storage costs.
4. Token counts are sufficient; dollar-cost estimates are not needed (user will calculate).
5. Trace data stored in Jaeger (default 7-day retention); request summaries stored in SQLite indefinitely.
6. No existing observability to migrate or preserve — greenfield instrumentation.

## Architecture

### Service Topology

```
┌─────────────┐     ┌─────────────────┐     ┌──────────┐
│ FastAPI      │────▶│ OTEL Collector  │────▶│ Jaeger   │ (traces, port 16686)
│ Backend      │     │ (sidecar)       │────▶│Prometheus│ (metrics, port 9090)
│ + OTEL SDK   │     └─────────────────┘     └──────────┘
└─────────────┘                                   │
                                            ┌─────▼──────┐
                                            │ Grafana    │ (dashboards, port 3000)
                                            └────────────┘
```

### New Python Dependencies

```
opentelemetry-api
opentelemetry-sdk
opentelemetry-exporter-otlp
opentelemetry-instrumentation-fastapi
opentelemetry-instrumentation-httpx
```

### New Docker Compose Services

```yaml
otel-collector:   # Receives OTLP, exports to Jaeger + Prometheus
jaeger:           # Trace storage + UI (port 16686)
prometheus:       # Metrics storage (port 9090)
grafana:          # Dashboards (port 3000)
```

## Trace & Span Hierarchy

Every user request produces a trace with this span tree:

```
[Trace: request-{uuid}]
│
├── HTTP POST /chat/stream                          ← root span (auto-instrumented)
│   ├── agent.build_prompt                          ← prompt assembly
│   │   └── attributes: prompt_tokens, history_turns, system_prompt_size
│   │
│   ├── agent.react_loop                            ← LangGraph agent execution
│   │   ├── llm.chat_completion [iteration=1]       ← first model call
│   │   │   └── attributes: model, input_tokens, output_tokens, finish_reason
│   │   │
│   │   ├── tool.search_knowledge_base              ← tool invocation
│   │   │   └── attributes: query, results_count, results_selected, latency_ms
│   │   │
│   │   ├── tool.read_workspace_file                ← file read
│   │   │   └── attributes: file_path, file_size_chars, latency_ms
│   │   │
│   │   ├── llm.chat_completion [iteration=2]       ← second model call
│   │   │   └── attributes: model, input_tokens, output_tokens, context_size
│   │   │
│   │   └── tool.propose_doc_change                 ← proposal creation
│   │       └── attributes: files_count, diff_size
│   │
│   ├── search.orchestrator                         ← search instrumentation
│   │   ├── search.classify_query                   ← query type detection
│   │   ├── search.lexical                          ← tier 1
│   │   ├── search.semantic                         ← tier 2
│   │   │   └── embedding.ollama                    ← embedding API call
│   │   │       └── attributes: model, texts_count, cache_hit, latency_ms
│   │   └── search.symbol                           ← tier 3
│   │
│   └── agent.response                              ← final response assembly
│       └── attributes: total_tokens, total_llm_calls, total_tool_calls
```

## Span Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `request.id` | string | UUID for the entire request |
| `request.model` | string | Model used (gpt-4o, deepseek-chat, etc.) |
| `request.query` | string | User query (first 200 chars) |
| `llm.model` | string | Model name for this specific call |
| `llm.input_tokens` | int | Input tokens for this LLM call |
| `llm.output_tokens` | int | Output tokens for this LLM call |
| `llm.total_tokens` | int | Total tokens for this LLM call |
| `llm.iteration` | int | Which iteration of the ReAct loop |
| `llm.finish_reason` | string | stop, length, tool_calls |
| `tool.name` | string | Tool name |
| `tool.input` | string | Tool input (truncated to 500 chars) |
| `tool.output_size` | int | Output size in characters |
| `tool.status` | string | success/error |
| `search.query` | string | The search query used |
| `search.scope` | string | auto, wiki, code, or namespace |
| `search.results_count` | int | Number of raw results |
| `search.tiers_used` | string | Comma-separated tier names |
| `search.cache_hit` | bool | Whether search cache was hit |
| `search.query_type` | string | symbol, concept, exact |
| `embedding.model` | string | Embedding model name |
| `embedding.texts_count` | int | Number of texts embedded |
| `embedding.cache_hits` | int | Cached embedding count |
| `embedding.cache_misses` | int | New embeddings computed |
| `prompt.total_chars` | int | Total prompt size in characters |
| `prompt.history_turns` | int | Number of conversation turns |
| `prompt.retrieval_chars` | int | Characters from retrieved content |
| `prompt.system_prompt_chars` | int | System prompt size |

## Metrics

### Counters

| Metric | Labels | Purpose |
|--------|--------|---------|
| `agent_requests_total` | `model`, `status` | Total requests |
| `agent_llm_calls_total` | `model`, `iteration` | LLM invocations |
| `agent_tool_calls_total` | `tool_name`, `status` | Tool usage frequency |
| `agent_search_calls_total` | `tier`, `cache_hit` | Search tier usage |
| `agent_embedding_calls_total` | `model`, `cache_hit` | Embedding API calls |
| `agent_tokens_total` | `model`, `direction` | Token consumption (input/output) |
| `agent_errors_total` | `stage`, `error_type` | Errors by pipeline stage |

### Histograms

| Metric | Labels | Buckets | Purpose |
|--------|--------|---------|---------|
| `agent_request_duration_seconds` | `model` | 1,2,5,10,30,60,120 | End-to-end latency |
| `agent_llm_call_duration_seconds` | `model` | 0.5,1,2,5,10,30 | Per-LLM-call latency |
| `agent_tool_call_duration_seconds` | `tool_name` | 0.1,0.5,1,2,5 | Per-tool latency |
| `agent_prompt_tokens` | `model` | 500,1k,2k,4k,8k,16k | Prompt size distribution |
| `agent_search_results_count` | `tier` | 0,1,3,5,10,20 | Search yield |
| `agent_retrieval_chars` | — | 500,1k,2k,5k,10k | Context injection size |

### Gauges

| Metric | Purpose |
|--------|---------|
| `agent_embedding_cache_size` | Current cache entries |
| `agent_embedding_cache_hit_ratio` | Rolling hit rate |
| `agent_search_cache_size` | Search result cache entries |

## Instrumentation Plan

### 6.1 New Module: `backend/observability.py`

Central module containing:
- OTEL tracer and meter initialization
- `@traced` decorator for creating spans with automatic error recording
- Token counting utilities
- Prometheus metric object definitions
- SQLite summary writer
- Configuration (OTEL endpoint, service name, SQLite path)

### 6.2 `backend/main.py` Changes

- Import and call `init_observability()` at startup
- Auto-instrument FastAPI with `FastAPIInstrumentor`
- Add middleware to inject `request.id` UUID and set as span attribute
- Record `request.model`, `request.query_length`, `request.history_turns` on root span

### 6.3 `backend/agent.py` Changes

- Import tracing utilities from `observability.py`
- Wrap `build_system_prompt()` with traced span — record prompt size attributes
- Wrap `run_agent_stream()` with traced span `agent.react_loop`
- In `astream_events` loop:
  - `on_chat_model_stream` → accumulate tokens, extract `usage_metadata` from AIMessage
  - `on_tool_start` → create child span `tool.{name}` with input attributes
  - `on_tool_end` → close tool span with output size, latency, status
- After agent completes → record summary metrics (total tokens, calls, etc.)
- Write SQLite summary row

### 6.4 `backend/search/orchestrator.py` Changes

- Import tracing from `observability.py`
- Wrap `search()` with span `search.orchestrator`
- Record `query`, `scope`, `cache_hit`, `query_type`, `tiers_used`, `results_count`
- Wrap each tier block (lexical, semantic, symbol) with child spans
- Record `search.early_stopped` when early stopping triggers

### 6.5 `backend/search/semantic.py` Changes

- Wrap `OllamaEmbeddingFunction.__call__` with span `embedding.ollama`
- Record `texts_count`, `cache_hits`, `cache_misses`, `batch_count`
- Wrap `SemanticSearch.query()` with span `search.semantic.query`
- Record `collection`, `n_results`, `actual_results_count`

### 6.6 `backend/search_tools.py` Changes

- Minimal changes — tool calls already captured by LangGraph events
- Add richer attributes to existing tool spans (search scope, symbol name, line range)

### 6.7 Docker Compose Changes

Add four new services:
- `otel-collector` with OTLP receiver, Jaeger/Prometheus exporters
- `jaeger` all-in-one (port 16686)
- `prometheus` with scrape config for OTEL collector
- `grafana` with provisioned dashboards and Prometheus/Jaeger data sources

### 6.8 Configuration Files

- `backend/otel-collector-config.yaml` — collector pipeline config
- `backend/prometheus.yml` — scrape targets
- `backend/grafana/provisioning/` — data sources and dashboard JSON
- `backend/grafana/dashboards/` — pre-built dashboard definitions

## Grafana Dashboards

### Dashboard 1: Agent Overview

| Panel | Type | Query |
|-------|------|-------|
| Requests/hour | Time series | `rate(agent_requests_total[1h])` |
| Avg latency | Time series | `histogram_quantile(0.5, agent_request_duration_seconds)` |
| P95 latency | Time series | `histogram_quantile(0.95, agent_request_duration_seconds)` |
| Tokens consumed/hour | Time series | `rate(agent_tokens_total[1h])` by direction |
| Error rate | Time series | `rate(agent_errors_total[1h])` |
| Model usage breakdown | Pie chart | `sum(agent_requests_total) by (model)` |

### Dashboard 2: Token Deep-Dive

| Panel | Type | Query |
|-------|------|-------|
| Input vs output tokens | Stacked bar | `agent_tokens_total` by direction |
| Prompt size distribution | Heatmap | `agent_prompt_tokens_bucket` |
| Tokens per model | Table | `sum(agent_tokens_total) by (model)` |
| Avg tokens per request | Stat | `agent_tokens_total / agent_requests_total` |
| LLM calls per request | Histogram | `agent_llm_calls_total / agent_requests_total` |

### Dashboard 3: Search & Retrieval

| Panel | Type | Query |
|-------|------|-------|
| Search tier usage | Stacked bar | `agent_search_calls_total` by tier |
| Embedding cache hit ratio | Gauge | `agent_embedding_cache_hit_ratio` |
| Avg results per search | Stat | `agent_search_results_count` avg |
| Search cache hit rate | Gauge | search cache_hit rate |
| Retrieval context size | Heatmap | `agent_retrieval_chars_bucket` |

## Alerts

| Alert | Threshold | Severity |
|-------|-----------|----------|
| High token request | > 8000 tokens per request | Warning |
| Excessive LLM iterations | > 5 LLM calls per request | Warning |
| Search returning empty | > 3 consecutive empty searches | Info |
| Embedding cache cold | hit ratio < 50% | Info |
| Request timeout | latency > 60s | Critical |
| Prompt size spike | > 12000 chars | Warning |
| Tool failure rate | > 10% error rate on any tool | Warning |

## Optimization Hooks

| Signal | What It Tells You | Action |
|--------|-------------------|--------|
| High `retrieval_chars` vs low `citations_count` | Retrieved context is wasted | Reduce max_results or add relevance filtering |
| Repeated `search.cache_miss` for same concept | Agent rephrasing similar queries | Improve search cache key normalization |
| `llm.iterations > 3` frequently | Agent struggling, looping | Improve system prompt or tool descriptions |
| `embedding.cache_misses` high at steady state | Re-embedding unchanged content | Increase cache size or pre-warm |
| `tiers_used` always includes semantic | Lexical search insufficient | Invest in semantic indexing |
| `read_workspace_file` with large files | Reading entire files wastefully | Encourage `read_code_section` in prompt |

## SQLite Request Summary

Lightweight per-request summary for fast local queries:

```sql
CREATE TABLE request_traces (
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
);
```

## Error Handling

- All exceptions within traced spans are automatically recorded as span events with stack traces.
- LLM API errors (rate limits, timeouts) captured with `error.type`, `error.message`.
- Tool failures record `tool.status=error` and error message on the span.
- Ollama connection errors captured on embedding spans.
- Agent loop exhaustion recorded as `agent.max_iterations_reached=true`.

## Acceptance Criteria

1. Every `/chat` and `/chat/stream` request produces a trace visible in Jaeger.
2. Each trace contains spans for: prompt assembly, each LLM call, each tool call, each search tier.
3. Token counts (input, output, total) are recorded on every LLM call span.
4. Search spans record query, tier, results count, and cache hit status.
5. Embedding spans record texts count, cache hits, cache misses.
6. Prometheus metrics are scrapeable and appear in Grafana.
7. Three Grafana dashboards are pre-provisioned: Overview, Token Deep-Dive, Search & Retrieval.
8. SQLite `request_traces` table is populated for every request.
9. All four infrastructure services (collector, Jaeger, Prometheus, Grafana) start via `docker-compose up`.
10. Existing agent functionality is not broken — all existing tests pass.
11. Observability adds < 50ms overhead per request.
12. No secrets or API keys are logged in traces.

## Risks & Tradeoffs

| Risk | Mitigation |
|------|-----------|
| 4 extra Docker containers increase resource usage | Jaeger and Prometheus are lightweight; can disable in dev via compose profile |
| OTEL SDK adds latency overhead | Batch exporter with async flush; measured < 5ms per span |
| Token counts may be unavailable for some models | Fall back to character-based estimation (chars / 4) |
| Trace data grows over time | Jaeger default 7-day retention; SQLite VACUUM on schedule |
| Breaking changes if OTEL Python SDK updates | Pin specific versions in pyproject.toml |
| Sensitive data in traces (user queries) | Truncate queries to 200 chars; no auth tokens logged |

## Out of Scope

- Hermes agent instrumentation (separate future project).
- Dollar-cost estimation (user calculates from token counts).
- Real-time alerting (Grafana alerts configured but notification channels are user-configured).
- Frontend UI changes (the debug dashboard is Grafana + Jaeger, not a custom page).
