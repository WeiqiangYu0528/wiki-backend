import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from observability.config import ObservabilityConfig

# --- TEST 1: config defaults ---
print("=== TEST 1: ObservabilityConfig defaults ===")
cfg = ObservabilityConfig()
assert cfg.service_name == "mkdocs-agent"
assert cfg.otel_endpoint == "http://localhost:4317"
assert cfg.sqlite_path.endswith("traces.db")
assert cfg.enabled is True
print("PASS")

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
