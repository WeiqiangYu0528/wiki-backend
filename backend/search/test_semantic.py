import sys, os, shutil, tempfile, hashlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from search.semantic import EmbeddingCache, OllamaEmbeddingFunction, SemanticSearch

OLLAMA_URL = "http://localhost:11434"


def ollama_available() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


# ---------- TEST 1: EmbeddingCache ----------
print("=== TEST 1: EmbeddingCache ===")
cache = EmbeddingCache(max_size=3)

cache.put("m", "a", [1.0])
cache.put("m", "b", [2.0])
cache.put("m", "c", [3.0])
assert cache.get("m", "a") == [1.0]
assert cache.get("m", "b") == [2.0]
assert cache.get("m", "z") is None
assert len(cache) == 3
assert cache.hits == 2
assert cache.misses == 1

# LRU eviction: 'c' is LRU (a and b were accessed above), adding 'd' evicts 'c'
cache.put("m", "d", [4.0])
assert len(cache) == 3
assert cache.get("m", "c") is None  # evicted
assert cache.get("m", "a") == [1.0]

cache.clear()
assert len(cache) == 0
assert cache.hits == 0
assert cache.misses == 0
print("PASS")


# ---------- TEST 2: OllamaEmbeddingFunction cache integration ----------
print("\n=== TEST 2: OllamaEmbeddingFunction cache integration ===")
ef = OllamaEmbeddingFunction(base_url=OLLAMA_URL, model="all-minilm")

# Manually inject a cached embedding
ef._cache.put("all-minilm", "hello world", [0.1] * 384)
result = ef(["hello world"])
assert len(result) == 1
assert list(result[0]) == [0.1] * 384
assert ef.cache_stats["hits"] == 1
assert ef.cache_stats["misses"] == 0
print("PASS")


# ---------- LIVE OLLAMA TESTS ----------
if not ollama_available():
    print("\nSKIP Tests 3-5 — Ollama not reachable")
    sys.exit(0)

tmp_dir = tempfile.mkdtemp(prefix="test_chroma_ollama_")

try:
    ss = SemanticSearch(persist_dir=tmp_dir, ollama_base_url=OLLAMA_URL, ollama_model="all-minilm")

    # ---------- TEST 3: add + query ----------
    print("\n=== TEST 3: add + query ===")
    ss.add_documents("wiki", [
        {"id": "d1", "text": "The tool system manages permission checks and tool execution.", "file_path": "tool-system.md", "section": "Overview"},
        {"id": "d2", "text": "MemoryMiddleware loads AGENTS.md files for persistent context.", "file_path": "memory-system.md", "section": "Overview"},
        {"id": "d3", "text": "The gateway routes messages between channels and agents.", "file_path": "gateway.md", "section": "Overview"},
    ])
    results = ss.query("wiki", "permission system tool", n_results=2)
    assert len(results) > 0
    assert any("tool-system" in r["file_path"] for r in results)
    print(f"PASS — top result: {results[0]['file_path']}")

    # ---------- TEST 4: cache stats after add+query ----------
    print("\n=== TEST 4: cache stats ===")
    stats = ss.embed_fn.cache_stats
    assert stats["size"] > 0
    assert stats["hits"] > 0
    print(f"PASS — cache size={stats['size']}, hits={stats['hits']}, misses={stats['misses']}")

    # ---------- TEST 5: empty/nonexistent queries ----------
    print("\n=== TEST 5: edge cases ===")
    assert ss.query("wiki", "", n_results=5) == []
    assert ss.query("nonexistent", "test", n_results=5) == []
    print("PASS")

    print("\n✅ All tests passed.")
finally:
    shutil.rmtree(tmp_dir)
