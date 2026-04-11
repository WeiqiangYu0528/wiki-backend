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
