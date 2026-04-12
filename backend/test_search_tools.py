import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# --- Test 1: Tool imports ---
print("=== TEST 1: tool imports ===")
from search_tools import smart_search, find_symbol, read_code_section
assert callable(smart_search.invoke)
assert callable(find_symbol.invoke)
assert callable(read_code_section.invoke)
print("PASS")

# --- Test 2: read_code_section with line range ---
print("\n=== TEST 2: read_code_section line range ===")
result = read_code_section.invoke({
    "file_path": "backend/agent.py",
    "start_line": 1,
    "end_line": 5,
})
assert "import" in result
assert len(result.splitlines()) <= 15
print("PASS")

# --- Test 3: read_code_section bad path ---
print("\n=== TEST 3: read_code_section bad path ===")
result = read_code_section.invoke({"file_path": "nonexistent.py"})
assert "Error" in result or "not found" in result.lower() or "does not exist" in result.lower()
print("PASS")

# --- Test 4: smart_search invocable ---
print("\n=== TEST 4: smart_search invocable ===")
result = smart_search.invoke({"query": "MemoryMiddleware", "scope": "wiki"})
assert isinstance(result, str)
print(f"PASS — returned {len(result)} chars")

# --- Test 5: tools list updated in agent ---
print("\n=== TEST 5: agent tools list ===")
from agent import tools
names = [t.name for t in tools]
assert "smart_search" in names
assert "find_symbol" in names
assert "read_code_section" in names
assert "search_knowledge_base" not in names
print(f"PASS — tools: {names}")

print("\n✅ All search tool tests passed.")
