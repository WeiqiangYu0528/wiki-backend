"""System component validation test suite for the wiki agent backend.

Tests cross-cutting concerns: cache performance, persistence, TTL expiry,
budget arithmetic, compaction behaviour, memory eviction, and FTS5 ranking.
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_engine.budget import TokenBudget, estimate_tokens
from context_engine.compactor import ContextCompactor
from context_engine.engine import ContextEngine
from memory.sqlite_memory import SQLiteMemory
from search.cache import MultiLevelCache
from search.embedding_cache import PersistentEmbeddingCache


# ---------------------------------------------------------------------------
# MultiLevelCache tests
# ---------------------------------------------------------------------------

def test_l1_cache_hit_performance():
    """L1 hit should be faster than a cache miss (L2 fallback)."""
    with tempfile.TemporaryDirectory() as tmp:
        cache = MultiLevelCache(db_path=os.path.join(tmp, "c.db"), l1_max_entries=50)
        cache.put("q", "s", [{"t": "v"}], 10)

        # Warm L1 hit — measure many iterations for stable timing
        iterations = 2000
        start = time.perf_counter()
        for _ in range(iterations):
            cache.get("q", "s")
        l1_time = time.perf_counter() - start

        # Miss — query not in cache at all → hits L2 (miss) every time
        start = time.perf_counter()
        for _ in range(iterations):
            cache.get("never_stored", "s")
        miss_time = time.perf_counter() - start

        # L1 hit path should be faster than miss path (L2 lookup)
        assert l1_time < miss_time, (
            f"L1 hit ({l1_time:.4f}s) should be faster than miss ({miss_time:.4f}s)"
        )


def test_l2_cache_persistence():
    """A new MultiLevelCache instance reads entries from the same L2 db."""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "c.db")
        c1 = MultiLevelCache(db_path=db, l1_max_entries=10)
        c1.put("pq", "ps", [{"data": "persistent"}], 42)
        del c1  # discard in-memory L1

        c2 = MultiLevelCache(db_path=db, l1_max_entries=10)
        result = c2.get("pq", "ps")
        assert result is not None
        assert result[0]["data"] == "persistent"


def test_l2_ttl_expiry():
    """L2 entries expire after ttl_seconds."""
    with tempfile.TemporaryDirectory() as tmp:
        cache = MultiLevelCache(
            db_path=os.path.join(tmp, "c.db"),
            l1_max_entries=10,
            l2_ttl_seconds=1,
        )
        cache.put("q", "s", [{"t": "1"}], 10)
        cache._l1.clear()  # force L2-only lookup
        time.sleep(1.1)
        assert cache.get("q", "s") is None


# ---------------------------------------------------------------------------
# PersistentEmbeddingCache tests
# ---------------------------------------------------------------------------

def test_embedding_cache_size_growth():
    """Cache size grows with new texts, stays constant for repeated puts."""
    with tempfile.TemporaryDirectory() as tmp:
        ec = PersistentEmbeddingCache(db_path=os.path.join(tmp, "emb.db"))
        emb = [0.1, 0.2, 0.3]

        ec.put("model-a", "hello", emb)
        ec.put("model-a", "world", emb)
        assert ec.stats["size"] == 2

        # Re-putting same key should not increase size (INSERT OR REPLACE)
        ec.put("model-a", "hello", emb)
        assert ec.stats["size"] == 2

        # New text → size grows
        ec.put("model-a", "foo", emb)
        assert ec.stats["size"] == 3


def test_embedding_cache_batch_get():
    """batch_get returns only cached entries."""
    with tempfile.TemporaryDirectory() as tmp:
        ec = PersistentEmbeddingCache(db_path=os.path.join(tmp, "emb.db"))
        ec.put("m", "a", [1.0, 2.0])
        ec.put("m", "b", [3.0, 4.0])

        result = ec.batch_get("m", ["a", "b", "c"])
        assert "a" in result
        assert "b" in result
        assert "c" not in result
        assert len(result) == 2
        # Verify values round-trip correctly (float32 precision)
        assert abs(result["a"][0] - 1.0) < 1e-5
        assert abs(result["b"][1] - 4.0) < 1e-5


# ---------------------------------------------------------------------------
# TokenBudget tests
# ---------------------------------------------------------------------------

def test_token_budget_allocation_accuracy():
    """allocate() values must sum to exactly the context_limit."""
    budget = TokenBudget(context_limit=128000)
    alloc = budget.allocate()

    # int() truncation may lose fractions — sum should be close but ≤ limit
    total = sum(alloc.values())
    # With default percentages summing to 1.0, truncation can lose at most
    # len(categories) tokens.  Verify within that tolerance.
    assert total <= budget.context_limit
    assert total >= budget.context_limit - len(alloc), (
        f"Allocation total {total} too far from limit {budget.context_limit}"
    )


def test_token_budget_over_budget_detection():
    """Using more than input allocation triggers is_over_budget()."""
    budget = TokenBudget(context_limit=1000)
    alloc = budget.allocate()

    # Input budget = everything except output + safety
    input_budget = sum(v for k, v in alloc.items() if k not in ("output", "safety"))

    assert not budget.is_over_budget()

    # Use exactly the input budget — should not be over yet
    budget.use("history", input_budget)
    assert not budget.is_over_budget()

    # One more token tips it over
    budget.use("history", 1)
    assert budget.is_over_budget()


# ---------------------------------------------------------------------------
# ContextCompactor tests
# ---------------------------------------------------------------------------

def _make_compactor_messages():
    """Build a message list with old tool outputs and 4+ protected turns."""
    return [
        # Turn 1 (old — should be prunable)
        {"role": "user", "content": "turn 1 question"},
        {"role": "assistant", "content": "turn 1 answer"},
        {"role": "tool", "content": "x" * 500, "name": "search"},
        # Turn 2 (old — should be prunable)
        {"role": "user", "content": "turn 2"},
        {"role": "assistant", "content": "turn 2 answer"},
        {"role": "tool", "content": "y" * 500, "name": "read_file"},
        # Turn 3 (protected)
        {"role": "user", "content": "turn 3"},
        {"role": "assistant", "content": "turn 3 answer"},
        # Turn 4 (protected)
        {"role": "user", "content": "turn 4"},
        {"role": "assistant", "content": "turn 4 answer"},
        # Turn 5 (protected)
        {"role": "user", "content": "turn 5"},
        {"role": "assistant", "content": "turn 5 answer"},
        # Turn 6 (protected)
        {"role": "user", "content": "turn 6"},
        {"role": "assistant", "content": "turn 6 answer"},
    ]


def test_compactor_reduces_history():
    """Old tool outputs outside protected zone are pruned."""
    compactor = ContextCompactor(protected_turns=4, trigger_pct=0.01)
    messages = _make_compactor_messages()

    result = compactor.compact(messages, token_budget=500)

    # The two old tool messages should have been pruned
    assert compactor.last_pruned_count == 2
    assert compactor.last_chars_saved > 0

    # Pruned messages replaced with short placeholder
    for msg in result:
        if msg.get("role") == "tool":
            assert len(msg["content"]) < 500, "Tool output should be pruned"
            assert "[Tool output pruned" in msg["content"]


def test_compactor_preserves_recent():
    """Last 4 turns are never pruned even when over budget."""
    compactor = ContextCompactor(protected_turns=4, trigger_pct=0.01)

    # Add tool output inside a protected turn to ensure it survives
    messages = _make_compactor_messages()
    # Inject a large tool output into the last protected turn
    messages.insert(-1, {"role": "tool", "content": "z" * 500, "name": "recent_tool"})

    result = compactor.compact(messages, token_budget=500)

    # The recent tool output (inside protected zone) should survive intact
    recent_tool_msgs = [
        m for m in result
        if m.get("role") == "tool" and m.get("name") == "recent_tool"
    ]
    assert len(recent_tool_msgs) == 1
    assert recent_tool_msgs[0]["content"] == "z" * 500


# ---------------------------------------------------------------------------
# ContextEngine tests
# ---------------------------------------------------------------------------

def test_context_engine_budget_tracking():
    """assemble() returns budget_summary with accurate used values."""
    with tempfile.TemporaryDirectory() as tmp:
        memory = SQLiteMemory(db_path=os.path.join(tmp, "mem.db"), max_items=100)
        compactor = ContextCompactor(protected_turns=4, trigger_pct=0.9)
        budget = TokenBudget(context_limit=128000)

        engine = ContextEngine(memory=memory, compactor=compactor, budget=budget)

        messages = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
        ]
        search_results = "Python was created by Guido van Rossum."

        result = engine.assemble(
            system_prompt="You are a helpful assistant.",
            messages=messages,
            query="Tell me about Python",
            search_results=search_results,
        )

        assert "budget_summary" in result
        assert "total_tokens" in result
        assert "messages" in result

        summary = result["budget_summary"]
        # System prompt was used
        assert summary["system"]["used"] > 0
        # History was tracked
        assert summary["history"]["used"] > 0
        # Search results were tracked
        assert summary["search"]["used"] > 0
        assert summary["search"]["used"] == estimate_tokens(search_results)


# ---------------------------------------------------------------------------
# SQLiteMemory tests
# ---------------------------------------------------------------------------

def test_memory_eviction():
    """Adding beyond max_items evicts oldest entries."""
    with tempfile.TemporaryDirectory() as tmp:
        mem = SQLiteMemory(db_path=os.path.join(tmp, "mem.db"), max_items=5)
        for i in range(8):
            mem.add(f"memory number {i}", metadata={"idx": i})

        assert mem.count() == 5

        # The oldest entries (0, 1, 2) should have been evicted.
        # Remaining should be the 5 most recent: 3..7
        results = mem._conn.execute(
            "SELECT content FROM memories ORDER BY created_at ASC"
        ).fetchall()
        contents = [r[0] for r in results]
        assert "memory number 0" not in contents
        assert "memory number 7" in contents


def test_memory_fts5_ranking():
    """Query matching a specific term ranks that result higher."""
    with tempfile.TemporaryDirectory() as tmp:
        mem = SQLiteMemory(db_path=os.path.join(tmp, "mem.db"), max_items=100)
        mem.add("The weather today is sunny and warm")
        mem.add("Python is a popular programming language")
        mem.add("SQLite provides full text search via FTS5")

        results = mem.query("Python programming", top_k=3)
        assert len(results) > 0
        # The Python-related memory should be the top result
        assert "Python" in results[0]["content"]
