import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from search.registry import RepoRegistry, RepoMeta

registry = RepoRegistry()

print("=== TEST 1: all repos registered ===")
assert len(registry.repos) == 6
names = {r.namespace for r in registry.repos}
assert names == {"claude-code", "deepagents", "opencode", "openclaw", "autogen", "hermes-agent"}
print("PASS")

print("\n=== TEST 2: get_by_namespace ===")
repo = registry.get_by_namespace("deepagents")
assert repo is not None
assert repo.source_dir == "deepagents"
assert repo.wiki_dir == "docs/deepagents-wiki"
assert "python" in repo.languages
print("PASS")

print("\n=== TEST 3: target from page context ===")
targets, confidence = registry.target(query="how does memory work", page_url="/deepagents-wiki/entities/memory-system/")
assert targets[0].namespace == "deepagents"
assert confidence == "high"
print(f"PASS — primary target: {targets[0].namespace}, confidence: {confidence}")

print("\n=== TEST 4: target from keyword ===")
targets, confidence = registry.target(query="tool system MCP permissions")
assert targets[0].namespace == "claude-code"
assert confidence == "medium"
print(f"PASS — primary target: {targets[0].namespace}, confidence: {confidence}")

print("\n=== TEST 5: target ambiguous query ===")
targets, confidence = registry.target(query="how does the agent loop and tool system work")
assert len(targets) >= 1
print(f"PASS — {len(targets)} repos targeted, confidence: {confidence}")

print("\n=== TEST 6: explicit namespace ===")
targets, confidence = registry.target(query="anything", namespace="autogen")
assert len(targets) == 1 and targets[0].namespace == "autogen"
assert confidence == "high"
print(f"PASS, confidence: {confidence}")

print("\n=== TEST 7: get nonexistent ===")
assert registry.get_by_namespace("bogus") is None
print("PASS")

print("\n✅ All registry tests passed.")
