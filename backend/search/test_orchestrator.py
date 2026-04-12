import sys, os, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from search.orchestrator import SearchOrchestrator, classify_query, format_results

# --- Test 1: classify_query ---
print("=== TEST 1: classify_query ===")
assert classify_query("MemoryMiddleware") == "symbol"
assert classify_query("how does the tool system work") == "concept"
assert classify_query("ERROR: file not found") == "exact"
assert classify_query("create_react_agent function") == "symbol"
assert classify_query("what is the architecture of the agent loop") == "concept"
print("PASS")

# --- Test 2: orchestrator init ---
print("\n=== TEST 2: orchestrator init ===")
tmp = tempfile.mkdtemp()
try:
    from search.semantic import SemanticSearch
    sem = SemanticSearch(persist_dir=os.path.join(tmp, "chroma"))
    orch = SearchOrchestrator(workspace_dir=tmp, semantic=sem)
    assert orch is not None
    assert orch._max_results == 8
    assert orch._max_chars == 2000
    print("PASS")
finally:
    shutil.rmtree(tmp)

# --- Test 3: format_results with new limits ---
print("\n=== TEST 3: format_results ===")
results = [
    {"file_path": "docs/test.md", "text": "x" * 500, "score": 0.9, "line_number": 10},
    {"file_path": "docs/other.md", "text": "y" * 500, "score": 0.5, "line_number": 20},
]
formatted = format_results(results, max_chars=400, result_max_chars=100)
assert len(formatted) < 500
assert "docs/test.md" in formatted
assert "x" * 200 not in formatted
print("PASS")

# --- Test 4: format_results empty ---
print("\n=== TEST 4: format_results empty ===")
assert format_results([], max_chars=1000) == "No results found."
print("PASS")

# --- Test 5: session cache ---
print("\n=== TEST 5: session cache ===")
tmp2 = tempfile.mkdtemp()
try:
    sem2 = SemanticSearch(persist_dir=os.path.join(tmp2, "chroma"))
    orch2 = SearchOrchestrator(workspace_dir=tmp2, semantic=sem2)
    orch2._session_cache["test:auto"] = "cached result"
    assert orch2.search("test", scope="auto") == "cached result"
    orch2.clear_cache()
    assert len(orch2._session_cache) == 0
    print("PASS")
finally:
    shutil.rmtree(tmp2)

print("\n✅ All orchestrator tests passed.")
