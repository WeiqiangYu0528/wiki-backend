"""Integration test: verify full search pipeline works end-to-end."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from search.orchestrator import SearchOrchestrator, classify_query
from search.registry import repo_registry
from search.semantic import SemanticSearch, EmbeddingCache
from agent import tools, _format_history, ROOT_DIR
from security import settings

print("=" * 60)
print("SEARCH INTEGRATION TEST")
print("=" * 60)

# --- Test 1: Agent tools ---
print("\n--- Test 1: Agent has correct tools ---")
names = [t.name for t in tools]
assert "smart_search" in names
assert "find_symbol" in names
assert "read_code_section" in names
assert "search_knowledge_base" not in names
print(f"PASS — tools: {names}")

# --- Test 2: Lexical search ---
print("\n--- Test 2: Lexical search on real workspace ---")
from search.lexical import LexicalSearch
ls = LexicalSearch(workspace_dir=ROOT_DIR)
results = ls.search("MemoryMiddleware", search_paths=["docs/"])
assert len(results) > 0
print(f"PASS — {len(results)} results")

# --- Test 3: Query classification ---
print("\n--- Test 3: Query classification ---")
assert classify_query("MemoryMiddleware") == ("symbol", "MemoryMiddleware")
assert classify_query("how does routing work") == ("concept", "how does routing work")
assert classify_query("ERROR: connection refused") == ("exact", "ERROR: connection refused")
print("PASS")

# --- Test 4: Registry targeting ---
print("\n--- Test 4: Registry targeting ---")
targets, confidence = repo_registry.target("tool permissions", page_url="/claude-code/entities/tool-system/")
assert targets[0].namespace == "claude-code"
assert confidence == "high"
print(f"PASS — targeted {targets[0].namespace}, confidence: {confidence}")

# --- Test 5: read_code_section ---
print("\n--- Test 5: read_code_section ---")
from search_tools import read_code_section
result = read_code_section.invoke({"file_path": "backend/agent.py", "start_line": 1, "end_line": 10})
assert "import" in result
print("PASS")

# --- Test 6: History truncation ---
print("\n--- Test 6: History truncation ---")
long_history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
truncated = _format_history(long_history)
max_msgs = settings.max_history_turns * 2
assert len(truncated) <= max_msgs, f"Expected <= {max_msgs}, got {len(truncated)}"
print(f"PASS — {len(truncated)} messages (max {max_msgs})")

# --- Test 7: Configurable settings ---
print("\n--- Test 7: Settings ---")
assert settings.embedding_provider == "ollama"
assert settings.ollama_embed_model == "all-minilm"
assert settings.embedding_dimensions == 384
assert settings.max_history_turns == 6
assert settings.search_max_results == 8
assert settings.search_max_chars == 2000
print("PASS")

# --- Test 8: Embedding cache ---
print("\n--- Test 8: Embedding cache ---")
cache = EmbeddingCache(max_size=5)
cache.put("test", "model", [1.0, 2.0])
assert cache.get("test", "model") == [1.0, 2.0]
assert cache.hits == 1
print("PASS")

print("\n" + "=" * 60)
print("✅ ALL INTEGRATION TESTS PASSED")
print("=" * 60)
