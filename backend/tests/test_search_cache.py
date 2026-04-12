"""Tests for multi-level search cache (L1 LRU + L2 SQLite)."""
import sys
import os
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from search.cache import MultiLevelCache


def test_l1_cache_hit():
    with tempfile.TemporaryDirectory() as tmp:
        cache = MultiLevelCache(db_path=os.path.join(tmp, "cache.db"), l1_max_entries=10)
        cache.put("q1", "scope1", [{"text": "result"}], token_count=100)
        hit = cache.get("q1", "scope1")
        assert hit is not None
        assert hit[0]["text"] == "result"


def test_l1_cache_miss_l2_hit():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "cache.db")
        cache1 = MultiLevelCache(db_path=db_path, l1_max_entries=10)
        cache1.put("q1", "scope1", [{"text": "from_db"}], token_count=50)
        cache2 = MultiLevelCache(db_path=db_path, l1_max_entries=10)
        hit = cache2.get("q1", "scope1")
        assert hit is not None
        assert hit[0]["text"] == "from_db"


def test_l1_eviction():
    with tempfile.TemporaryDirectory() as tmp:
        cache = MultiLevelCache(db_path=os.path.join(tmp, "cache.db"), l1_max_entries=2)
        cache.put("q1", "s", [{"t": "1"}], 10)
        cache.put("q2", "s", [{"t": "2"}], 10)
        cache.put("q3", "s", [{"t": "3"}], 10)
        stats = cache.stats()
        assert stats["l1_size"] == 2


def test_l2_ttl_expiry():
    with tempfile.TemporaryDirectory() as tmp:
        cache = MultiLevelCache(
            db_path=os.path.join(tmp, "cache.db"),
            l1_max_entries=10,
            l2_ttl_seconds=1,
        )
        cache.put("q1", "s", [{"t": "1"}], 10)
        cache._l1.clear()
        time.sleep(1.1)
        hit = cache.get("q1", "s")
        assert hit is None


def test_cache_clear():
    with tempfile.TemporaryDirectory() as tmp:
        cache = MultiLevelCache(db_path=os.path.join(tmp, "cache.db"), l1_max_entries=10)
        cache.put("q1", "s", [{"t": "1"}], 10)
        cache.clear()
        assert cache.get("q1", "s") is None
        assert cache.stats()["l1_size"] == 0


def test_cache_stats():
    with tempfile.TemporaryDirectory() as tmp:
        cache = MultiLevelCache(db_path=os.path.join(tmp, "cache.db"), l1_max_entries=10)
        cache.put("q1", "s", [{"t": "1"}], 10)
        cache.get("q1", "s")  # hit
        cache.get("q2", "s")  # miss
        stats = cache.stats()
        assert stats["l1_size"] == 1
        assert stats["hits"] >= 1
        assert stats["misses"] >= 1


def test_cache_key_includes_scope():
    with tempfile.TemporaryDirectory() as tmp:
        cache = MultiLevelCache(db_path=os.path.join(tmp, "cache.db"), l1_max_entries=10)
        cache.put("q1", "wiki", [{"t": "wiki_result"}], 10)
        cache.put("q1", "code", [{"t": "code_result"}], 10)
        assert cache.get("q1", "wiki")[0]["t"] == "wiki_result"
        assert cache.get("q1", "code")[0]["t"] == "code_result"


def test_cache_persistence_across_restarts():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "cache.db")
        c1 = MultiLevelCache(db_path=db_path, l1_max_entries=5)
        c1.put("persistent_q", "s", [{"t": "survives"}], 20)
        del c1
        c2 = MultiLevelCache(db_path=db_path, l1_max_entries=5)
        hit = c2.get("persistent_q", "s")
        assert hit is not None
        assert hit[0]["t"] == "survives"
