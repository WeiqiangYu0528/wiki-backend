"""Tests for memory manager (SQLite FTS5 + embedding hybrid)."""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.sqlite_memory import SQLiteMemory


def test_add_and_query():
    with tempfile.TemporaryDirectory() as tmp:
        mem = SQLiteMemory(db_path=os.path.join(tmp, "mem.db"))
        mem.add("The agent uses Meilisearch for hybrid search", {"source": "test"})
        mem.add("ChromaDB provides deep semantic search", {"source": "test"})
        results = mem.query("search engine", top_k=2)
        assert len(results) > 0
        assert any("Meilisearch" in r["content"] or "search" in r["content"] for r in results)


def test_query_empty_db():
    with tempfile.TemporaryDirectory() as tmp:
        mem = SQLiteMemory(db_path=os.path.join(tmp, "mem.db"))
        results = mem.query("anything", top_k=5)
        assert results == []


def test_clear():
    with tempfile.TemporaryDirectory() as tmp:
        mem = SQLiteMemory(db_path=os.path.join(tmp, "mem.db"))
        mem.add("some memory", {})
        assert mem.count() == 1
        mem.clear()
        assert mem.count() == 0


def test_metadata_stored():
    with tempfile.TemporaryDirectory() as tmp:
        mem = SQLiteMemory(db_path=os.path.join(tmp, "mem.db"))
        mem.add("test content", {"source": "user", "tags": "search,optimization"})
        results = mem.query("test", top_k=1)
        assert len(results) == 1
        assert results[0]["metadata"]["source"] == "user"


def test_persistence():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "mem.db")
        m1 = SQLiteMemory(db_path=db)
        m1.add("persistent memory", {"source": "test"})
        del m1
        m2 = SQLiteMemory(db_path=db)
        assert m2.count() == 1
        results = m2.query("persistent", top_k=1)
        assert len(results) == 1


def test_max_items_enforcement():
    with tempfile.TemporaryDirectory() as tmp:
        mem = SQLiteMemory(db_path=os.path.join(tmp, "mem.db"), max_items=3)
        for i in range(5):
            mem.add(f"memory item {i}", {"index": str(i)})
        assert mem.count() == 3
