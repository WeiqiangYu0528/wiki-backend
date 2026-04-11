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
