import sys, os, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from search.lexical import LexicalSearch

tmp = tempfile.mkdtemp(prefix="test_lexical_")
docs_dir = os.path.join(tmp, "docs", "test-wiki")
src_dir = os.path.join(tmp, "myrepo", "src")
os.makedirs(docs_dir)
os.makedirs(src_dir)

with open(os.path.join(docs_dir, "memory.md"), "w") as f:
    f.write("# Memory System\n\nThe MemoryMiddleware loads context from AGENTS.md files.\n")
with open(os.path.join(docs_dir, "tools.md"), "w") as f:
    f.write("# Tool System\n\nTools are registered and executed by the agent.\n")
with open(os.path.join(src_dir, "memory.py"), "w") as f:
    f.write('class MemoryMiddleware:\n    """Loads agent memory."""\n    pass\n')
with open(os.path.join(src_dir, "agent.py"), "w") as f:
    f.write('def run_agent():\n    """Run the agent loop."""\n    pass\n')

ls = LexicalSearch(workspace_dir=tmp)

print("=== TEST 1: search wiki docs ===")
results = ls.search("MemoryMiddleware", search_paths=["docs/"])
assert len(results) >= 1
assert any("memory" in r["file_path"].lower() for r in results)
print(f"PASS — {len(results)} results")

print("\n=== TEST 2: search source code ===")
results = ls.search("MemoryMiddleware", search_paths=["myrepo/"])
assert len(results) >= 1
assert any("memory.py" in r["file_path"] for r in results)
print(f"PASS — {len(results)} results")

print("\n=== TEST 3: no results ===")
results = ls.search("xyznonexistent123", search_paths=["docs/"])
assert len(results) == 0
print("PASS")

print("\n=== TEST 4: case insensitive ===")
results = ls.search("memorymiddleware", search_paths=["docs/"])
assert len(results) >= 1
print("PASS")

print("\n=== TEST 5: results have context ===")
results = ls.search("MemoryMiddleware", search_paths=["docs/"])
assert results[0]["text"]
assert results[0]["line_number"] > 0
print("PASS")

shutil.rmtree(tmp)

print("\n✅ All lexical search tests passed.")
