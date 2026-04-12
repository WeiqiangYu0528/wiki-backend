# Observability & Tracing

## Architecture
The system uses OpenTelemetry for distributed tracing, Prometheus for metrics, and a SQLite trace store for request-level summaries.

```
Agent Request → OTEL Spans → Jaeger (traces)
                           → Prometheus (metrics)
             → SQLite trace_store (summaries)
             → /api/traces (API access)
```

## Metrics (OTEL/Prometheus)
All metrics use the `agent_` prefix and are defined in `backend/observability/metrics.py`.

### Counters
| Metric | Description |
|--------|-------------|
| `agent_requests_total` | Total agent requests by model/status |
| `agent_llm_calls_total` | LLM invocations by model/iteration |
| `agent_tool_calls_total` | Tool calls by name/status |
| `agent_search_calls_total` | Search calls by tier |
| `agent_embedding_calls_total` | Embedding API calls |
| `agent_tokens_total` | Tokens consumed by model/direction |
| `agent_errors_total` | Errors by stage/type |
| `agent_search_attempts_total` | Search attempts by strategy |
| `agent_strategy_escalations_total` | Strategy escalation events |
| `agent_loops_detected_total` | Loop detection events |
| `agent_repo_confidence_total` | Repo targeting confidence distribution |
| `agent_code_search_success_total` | Successful code search lookups |

### Histograms
| Metric | Description | Unit |
|--------|-------------|------|
| `agent_request_duration_seconds` | End-to-end request latency | s |
| `agent_llm_call_duration_seconds` | Per-LLM-call latency | s |
| `agent_tool_call_duration_seconds` | Per-tool-call latency | s |
| `agent_prompt_tokens` | Prompt size in estimated tokens | tokens |
| `agent_search_results_count` | Search results returned | count |
| `agent_retrieval_chars` | Retrieved content chars in prompt | chars |
| `agent_code_search_duration_seconds` | Code search latency | s |
| `agent_recursion_depth` | ReAct loop depth per request | count |

## Trace Store (SQLite)
Extended schema in `backend/observability/trace_store.py` captures per-request summaries:
- Token usage (total, input, output)
- Tool calls (count, sequence with name/duration/output_length)
- Search behavior (attempts, strategy, exhaustion, loop detection)
- Repo targeting (confidence, selected repo)
- Timing (duration_ms)

## API Endpoints
- `GET /api/traces?limit=20` — Recent request traces (requires auth)
  - **limit** parameter is capped at 100 for performance (max 100 rows returned)
  - Returns list of most recent trace summaries as JSON
- `GET /api/traces/{request_id}` — Specific trace by ID (requires auth)

## Grafana Dashboards
Pre-configured dashboards available at `http://localhost:19999`:
- Agent Overview: request rate, latency, error rate
- Token Usage: consumption by model, input vs output
- Search Performance: attempts, strategy distribution, success rate

## Local Development
```bash
# Start observability stack
docker compose up -d jaeger prometheus grafana

# View traces: http://localhost:16686 (Jaeger)
# View metrics: http://localhost:9090 (Prometheus)  
# View dashboards: http://localhost:19999 (Grafana)
```
of Prometheus.

---

## Architecture

```
Backend (Python)
    │
    ├── TracerProvider + BatchSpanProcessor
    │       │
    │       └── OTLP gRPC ──► OTEL Collector (:4317)
    │                              │
    │                              ├──► Jaeger (:16686)     [Traces]
    │                              │
    │                              └──► Prometheus (:9090)  [Metrics]
    │                                       │
    │                                       └──► Grafana (:19999)
    │
    ├── MeterProvider + PeriodicExportingMetricReader (15s)
    │       │
    │       └── OTLP gRPC ──► OTEL Collector (:4317)
    │                              │
    │                              └──► Prometheus (:9090)
    │
    └── RequestTraceStore (SQLite)
            └── Per-request audit log
```

---

## OTEL Initialization

**Module**: `observability/tracing.py` and `observability/metrics.py`

### Tracing Setup

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

def init_tracing():
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.OTEL_OTEL_ENDPOINT)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
```

### Metrics Setup

```python
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

def init_metrics():
    exporter = OTLPMetricExporter(endpoint=settings.OTEL_OTEL_ENDPOINT)
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=15000)
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
```

### Configuration

| Setting              | Default                    | Description                  |
|----------------------|----------------------------|------------------------------|
| `OTEL_ENABLED`       | `true`                     | Master toggle for telemetry  |
| `OTEL_OTEL_ENDPOINT` | `http://localhost:4317`    | OTLP gRPC endpoint          |

When `OTEL_ENABLED` is `false`, all tracing and metrics are no-ops — the
instrumentation code still runs but produces no output.

---

## Trace Pipeline

### Span Hierarchy

A typical chat request produces the following span tree:

```
[http_request] POST /chat/stream                    ← Root span
│   duration: 3.2s
│   attributes: method=POST, path=/chat/stream, status=200
│
├── [auth] jwt_validation                           ← Auth check
│       duration: 0.1ms
│
├── [context] assemble_context                      ← Context engine
│       duration: 12ms
│   │
│   ├── [memory] fts5_recall                        ← Memory lookup
│   │       duration: 2ms
│   │       attributes: query="agent tools", results=5
│   │
│   ├── [context] calculate_budget                  ← Token budget
│   │       duration: 0.1ms
│   │
│   └── [context] compact_history                   ← History compaction
│           duration: 3ms
│           attributes: turns_before=8, turns_after=6
│
├── [agent] react_loop                              ← Agent execution
│       duration: 3.1s
│       attributes: iterations=2, tools_called=1
│   │
│   ├── [llm] chat_completion                       ← First LLM call (tool decision)
│   │       duration: 0.8s
│   │       attributes: model=qwen3.5, prompt_tokens=2048, completion_tokens=45
│   │
│   ├── [tool] search_knowledge_base                ← Tool execution
│   │       duration: 0.6s
│   │       attributes: query="agent architecture", scope="claude-code"
│   │   │
│   │   ├── [cache] lookup                          ← Cache check
│   │   │       duration: 0.05ms
│   │   │       attributes: hit=false, level=miss
│   │   │
│   │   ├── [search] meilisearch                    ← Meilisearch
│   │   │       duration: 120ms
│   │   │       attributes: index=wiki_docs, results=6
│   │   │
│   │   ├── [search] chromadb                       ← ChromaDB
│   │   │       duration: 80ms
│   │   │       attributes: collection=claude-code, results=4
│   │   │
│   │   ├── [search] rerank                         ← Reranking
│   │   │       duration: 2ms
│   │   │       attributes: input=10, output=8
│   │   │
│   │   └── [cache] store                           ← Cache write
│   │           duration: 1ms
│   │
│   └── [llm] chat_completion                       ← Second LLM call (final answer)
│           duration: 1.7s
│           attributes: model=qwen3.5, prompt_tokens=4096, completion_tokens=512
│
└── [trace_store] record                            ← Audit log write
        duration: 1ms
```

### Span Attributes

Common attributes attached to spans:

| Attribute           | Type    | Description                          |
|---------------------|---------|--------------------------------------|
| `request.id`        | string  | Unique request identifier            |
| `request.method`    | string  | HTTP method (GET, POST)              |
| `request.path`      | string  | URL path                             |
| `request.status`    | int     | HTTP status code                     |
| `model`             | string  | LLM model name                       |
| `prompt_tokens`     | int     | Input tokens for LLM call            |
| `completion_tokens` | int     | Output tokens from LLM call          |
| `tool.name`         | string  | Tool being called                    |
| `search.query`      | string  | Search query text                    |
| `search.scope`      | string  | Search namespace                     |
| `search.results`    | int     | Number of search results             |
| `cache.hit`         | bool    | Whether cache was hit                |
| `cache.level`       | string  | Cache level (l1, l2, miss)           |

---

## Metrics

**Module**: `observability/metrics.py`

All metrics use the OTEL Meter API and are exported to Prometheus via the OTEL
Collector.

### Counters

| Metric Name           | Labels              | Description                              |
|-----------------------|----------------------|------------------------------------------|
| `requests_total`      | method, path, status | Total HTTP requests                      |
| `llm_calls_total`     | model, status        | Total LLM API calls                      |
| `tool_calls_total`    | tool_name, status    | Total tool invocations                   |
| `search_calls_total`  | backend, query_type  | Total search backend calls               |
| `tokens_total`        | type (prompt/completion) | Total tokens consumed                |
| `errors_total`        | error_type           | Total errors by category                 |

### Histograms

| Metric Name            | Labels        | Buckets                    | Description                    |
|------------------------|---------------|----------------------------|--------------------------------|
| `request_duration`     | method, path  | 0.1, 0.5, 1, 2, 5, 10, 30 | Request duration (seconds)     |
| `llm_call_duration`    | model         | 0.1, 0.5, 1, 2, 5, 10, 30 | LLM call duration (seconds)    |
| `tool_call_duration`   | tool_name     | 0.01, 0.05, 0.1, 0.5, 1, 5 | Tool call duration (seconds)  |
| `prompt_tokens_hist`   | model         | 100, 500, 1K, 5K, 10K, 50K | Prompt token count distribution|
| `search_results_hist`  | backend       | 0, 1, 2, 4, 8, 16, 32     | Search results count           |
| `retrieval_chars_hist` | —             | 100, 500, 1K, 2K, 5K, 10K | Retrieved content size (chars) |
| `embedding_cache_size` | —             | Gauge-style                | Current embedding cache entries|

---

## RequestTraceStore

**Module**: `observability/trace_store.py`

A SQLite database that stores per-request summaries for audit, debugging, and
analytics. Every request gets a row with 19 fields.

### Schema

```sql
CREATE TABLE IF NOT EXISTS request_traces (
    id TEXT PRIMARY KEY,                -- Request UUID
    timestamp TEXT NOT NULL,            -- ISO 8601 timestamp (UTC)
    model TEXT NOT NULL,                -- LLM model used
    query TEXT NOT NULL,                -- User query text (truncated to 200 chars)
    status TEXT NOT NULL,               -- Request status
    total_tokens INTEGER DEFAULT 0,     -- Total tokens used
    input_tokens INTEGER DEFAULT 0,     -- Prompt/input tokens
    output_tokens INTEGER DEFAULT 0,    -- Completion/output tokens
    llm_calls INTEGER DEFAULT 0,        -- Number of LLM API calls
    tool_calls INTEGER DEFAULT 0,       -- Number of tool invocations
    search_calls INTEGER DEFAULT 0,     -- Number of search API calls
    embedding_calls INTEGER DEFAULT 0,  -- Number of embedding calls
    prompt_chars INTEGER DEFAULT 0,     -- Characters in prompt context
    retrieval_chars INTEGER DEFAULT 0,  -- Characters retrieved for context
    citations_count INTEGER DEFAULT 0,  -- Number of citations
    duration_ms INTEGER DEFAULT 0,      -- Total request duration (ms)
    error_message TEXT DEFAULT '',      -- Error message (if any)
    tiers_used TEXT DEFAULT '',         -- Tiers used during search (comma-separated)
    tools_used TEXT DEFAULT '',         -- Tools used during request (comma-separated)
    search_attempts INTEGER DEFAULT 0,  -- Number of search attempts made
    search_strategy TEXT DEFAULT '',    -- Strategy used for search escalation
    loop_detected INTEGER DEFAULT 0,    -- Whether infinite loop was detected (0/1)
    strategies_exhausted INTEGER DEFAULT 0, -- Whether all strategies exhausted (0/1)
    repo_confidence TEXT DEFAULT '',    -- Confidence for repo targeting
    repo_selected TEXT DEFAULT '',      -- Selected repository name
    recursion_depth INTEGER DEFAULT 0,  -- Max recursion depth reached
    tool_call_sequence TEXT DEFAULT '[]' -- JSON array of tool call details
);

CREATE INDEX IF NOT EXISTS idx_request_traces_timestamp
ON request_traces(timestamp);

CREATE INDEX IF NOT EXISTS idx_request_traces_model
ON request_traces(model);
```

### 27 Fields

| #  | Field                   | Type    | Description                                          |
|----|-------------------------|---------|------------------------------------------------------|
| 1  | `id`                    | TEXT    | Request UUID (primary key)                           |
| 2  | `timestamp`             | TEXT    | ISO 8601 timestamp in UTC                            |
| 3  | `model`                 | TEXT    | LLM model used (e.g., claude-3-5-sonnet-20241022)   |
| 4  | `query`                 | TEXT    | User query (truncated to 200 characters)             |
| 5  | `status`                | TEXT    | Request status (success, error, etc.)                |
| 6  | `total_tokens`          | INTEGER | Total tokens used (input + output)                   |
| 7  | `input_tokens`          | INTEGER | Prompt/input tokens                                  |
| 8  | `output_tokens`         | INTEGER | Completion/output tokens                            |
| 9  | `llm_calls`             | INTEGER | Number of LLM API calls made                         |
| 10 | `tool_calls`            | INTEGER | Total number of tool invocations                     |
| 11 | `search_calls`          | INTEGER | Number of search API calls                           |
| 12 | `embedding_calls`       | INTEGER | Number of embedding API calls                        |
| 13 | `prompt_chars`          | INTEGER | Characters in final prompt sent to LLM               |
| 14 | `retrieval_chars`       | INTEGER | Characters of retrieved content used in prompt       |
| 15 | `citations_count`       | INTEGER | Number of citations included in response             |
| 16 | `duration_ms`           | INTEGER | Total request duration in milliseconds               |
| 17 | `error_message`         | TEXT    | Error message if request failed (empty if success)   |
| 18 | `tiers_used`            | TEXT    | Search tiers used (comma-separated: web, code, etc.) |
| 19 | `tools_used`            | TEXT    | Tools invoked (comma-separated names)                |
| 20 | `search_attempts`       | INTEGER | Total number of search attempts made                 |
| 21 | `search_strategy`       | TEXT    | Search strategy used (web_only, code_first, etc.)   |
| 22 | `loop_detected`         | INTEGER | Whether infinite loop was detected (0 or 1)          |
| 23 | `strategies_exhausted`  | INTEGER | Whether all search strategies were exhausted (0 or 1)|
| 24 | `repo_confidence`       | TEXT    | Confidence level for repository targeting            |
| 25 | `repo_selected`         | TEXT    | Name of selected repository (if applicable)          |
| 26 | `recursion_depth`       | INTEGER | Maximum recursion/loop depth reached                 |
| 27 | `tool_call_sequence`    | TEXT    | JSON array of tool call details (name, duration)     |

### Schema Migration

On initialization, the trace store runs a schema migration that uses `ALTER TABLE` statements to add any missing columns from previous versions. This allows graceful upgrades without data loss:

```python
# From backend/observability/trace_store.py _init_db()
for col, typedef in [
    ("tiers_used", "TEXT DEFAULT ''"),
    ("tools_used", "TEXT DEFAULT ''"),
    ("search_attempts", "INTEGER DEFAULT 0"),
    # ... (all new columns are added with ALTER TABLE if not present)
]:
    try:
        conn.execute(f"ALTER TABLE request_traces ADD COLUMN {col} {typedef}")
    except sqlite3.OperationalError:
        pass  # column already exists
```

### Thread Safety

The `RequestTraceStore` class uses a thread lock (`threading.Lock`) to ensure thread-safe access to the SQLite database:
- **write()** method locks during INSERT/REPLACE operations
- **query()** method locks during SELECT operations
- All database connections are created within the lock context to prevent race conditions

### Querying the Trace Store

```bash
# Recent requests
sqlite3 data/traces.db \
  "SELECT id, datetime(timestamp, 'unixepoch'), model, duration_ms, tool_count
   FROM request_traces ORDER BY timestamp DESC LIMIT 20;"

# Average latency by model
sqlite3 data/traces.db \
  "SELECT model, COUNT(*), AVG(duration_ms), AVG(total_tokens)
   FROM request_traces GROUP BY model;"

# Errors in the last hour
sqlite3 data/traces.db \
  "SELECT * FROM request_traces
   WHERE error IS NOT NULL AND timestamp > unixepoch() - 3600;"

# Cache hit rate
sqlite3 data/traces.db \
  "SELECT
     SUM(cache_hit) as hits,
     COUNT(*) - SUM(cache_hit) as misses,
     ROUND(100.0 * SUM(cache_hit) / COUNT(*), 1) as hit_rate_pct
   FROM request_traces
   WHERE path LIKE '/chat%';"
```

---

## Jaeger Usage

Jaeger provides the trace visualization UI at `http://localhost:16686`.

### Finding Traces

1. Open `http://localhost:16686` in a browser
2. Select **Service**: `wiki-agent-backend`
3. Set **Operation**: `POST /chat/stream` (or leave "all")
4. Click **Find Traces**
5. Click on a trace to see the full span tree

### Useful Queries

- **Slow requests**: Set Min Duration to `2s` to find slow requests
- **Errors**: Filter by `error=true` tag
- **Specific tool calls**: Search for `tool.name=search_knowledge_base`
- **Cache misses**: Search for `cache.hit=false`

### Trace Comparison

Jaeger supports comparing two traces side-by-side. Useful for:
- Comparing a fast request vs. a slow request
- Comparing cache hit vs. cache miss performance
- Before/after optimization comparison

---

## Prometheus Queries

Prometheus is available at `http://localhost:9090`.

### Example PromQL Queries

```promql
# Request rate (requests per second, 5-minute window)
rate(requests_total[5m])

# P95 request latency
histogram_quantile(0.95, rate(request_duration_bucket[5m]))

# LLM calls per model
sum by (model) (rate(llm_calls_total[5m]))

# Token consumption rate
sum by (type) (rate(tokens_total[5m]))

# Error rate percentage
100 * sum(rate(errors_total[5m])) / sum(rate(requests_total[5m]))

# Search backend usage
sum by (backend) (rate(search_calls_total[5m]))

# Average search results per query
histogram_quantile(0.5, rate(search_results_hist_bucket[5m]))

# Tool call frequency
sum by (tool_name) (rate(tool_calls_total[5m]))

# P99 LLM call duration
histogram_quantile(0.99, rate(llm_call_duration_bucket[5m]))

# Embedding cache size
embedding_cache_size
```

---

## Grafana Dashboards

Grafana is available at `http://localhost:19999` (default credentials:
`admin`/`admin`).

### Datasource

Pre-configured Prometheus datasource pointing to `http://prometheus:9090`.

### Recommended Dashboard Panels

#### Overview Row
- **Request Rate**: `rate(requests_total[5m])` — line chart
- **Error Rate**: `100 * sum(rate(errors_total[5m])) / sum(rate(requests_total[5m]))` — gauge
- **P95 Latency**: `histogram_quantile(0.95, rate(request_duration_bucket[5m]))` — stat

#### LLM Row
- **Token Consumption**: `sum by (type) (rate(tokens_total[5m]))` — stacked area
- **LLM Call Duration P50/P95/P99**: histogram quantiles — line chart
- **Calls by Model**: `sum by (model) (rate(llm_calls_total[5m]))` — bar chart

#### Search Row
- **Search Backend Usage**: `sum by (backend) (rate(search_calls_total[5m]))` — pie chart
- **Cache Hit Rate**: derived from `search_calls_total` with cache tags — gauge
- **Search Results Distribution**: `search_results_hist` — histogram

#### Tools Row
- **Tool Call Frequency**: `sum by (tool_name) (rate(tool_calls_total[5m]))` — bar chart
- **Tool Call Duration**: `histogram_quantile(0.95, rate(tool_call_duration_bucket[5m]))` — line

---

## Debugging Guide

### Request is Slow

1. **Find the trace in Jaeger** — look at the span tree to identify the
   slowest span
2. Common bottlenecks:
   - **LLM call duration**: The model is slow. Check if using a local Ollama
     model (slow) vs. API provider (faster).
   - **Search duration**: Meilisearch or ChromaDB is slow. Check their logs.
   - **Embedding generation**: Ollama embedding is slow. Check the embedding
     cache hit rate.
   - **Multiple ReAct iterations**: Agent called tools multiple times. Check
     if the system prompt needs tuning.

### No Traces Appearing

1. **Check OTEL_ENABLED**: Must be `true`
2. **Check OTEL Collector**: `docker compose logs otel-collector`
3. **Check Jaeger**: `docker compose logs jaeger`
4. **Check connectivity**: `curl -v http://localhost:4317` from the backend
   container
5. **Check service name**: Jaeger UI should show `wiki-agent-backend`

### Metrics Not in Prometheus

1. **Check OTEL Collector config**: It should have a Prometheus exporter on
   port 8889
2. **Check Prometheus scrape config**: Should scrape `otel-collector:8889`
3. **Check OTEL Collector logs**: `docker compose logs otel-collector`
4. **Verify metrics export**: `curl http://localhost:8889/metrics` should show
   OTEL metrics

### High Error Rate

1. **Check errors_total by type**: Identify the error category
2. **Check Jaeger for error traces**: Filter by `error=true`
3. **Check backend logs**: `docker compose logs backend`
4. **Common causes**:
   - Ollama not responding (embedding failures)
   - Meilisearch not indexed (empty search results)
   - LLM provider API errors (rate limits, auth issues)
   - JWT token expiry

---

## OTEL Collector Configuration

The OTEL Collector receives telemetry from the backend and exports to Jaeger
and Prometheus.

```yaml
# otel-collector-config.yaml (simplified)
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

exporters:
  otlp/jaeger:
    endpoint: jaeger:4317
    tls:
      insecure: true

  prometheus:
    endpoint: 0.0.0.0:8889

processors:
  batch:
    timeout: 5s
    send_batch_size: 1024

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

---

## Related Documentation

- [System Architecture](system-architecture.md) — How observability fits in
- [Configuration](configuration.md) — OTEL environment variables
- [Deployment](deployment.md) — Docker Compose service setup
- [Known Issues](known-issues.md) — Grafana default credentials
