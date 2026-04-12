"""Tests for persistent SQLite embedding cache."""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from search.embedding_cache import PersistentEmbeddingCache


def _make_embedding(dim: int = 768) -> list[float]:
    return [0.1 * i for i in range(dim)]


def test_put_and_get():
    with tempfile.TemporaryDirectory() as tmp:
        cache = PersistentEmbeddingCache(db_path=os.path.join(tmp, "emb.db"))
        emb = _make_embedding(4)
        cache.put("model1", "hello world", emb)
        result = cache.get("model1", "hello world")
        assert result is not None
        assert len(result) == 4
        assert abs(result[0] - 0.0) < 1e-5
        assert abs(result[1] - 0.1) < 1e-5


def test_cache_miss():
    with tempfile.TemporaryDirectory() as tmp:
        cache = PersistentEmbeddingCache(db_path=os.path.join(tmp, "emb.db"))
        assert cache.get("model1", "not cached") is None


def test_model_aware_keys():
    with tempfile.TemporaryDirectory() as tmp:
        cache = PersistentEmbeddingCache(db_path=os.path.join(tmp, "emb.db"))
        emb_a = [1.0, 2.0]
        emb_b = [3.0, 4.0]
        cache.put("model_a", "same text", emb_a)
        cache.put("model_b", "same text", emb_b)
        assert cache.get("model_a", "same text") == emb_a
        assert cache.get("model_b", "same text") == emb_b


def test_persistence_across_instances():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "emb.db")
        c1 = PersistentEmbeddingCache(db_path=db)
        c1.put("m", "text", [1.0, 2.0, 3.0])
        del c1
        c2 = PersistentEmbeddingCache(db_path=db)
        result = c2.get("m", "text")
        assert result is not None
        assert len(result) == 3


def test_batch_get():
    with tempfile.TemporaryDirectory() as tmp:
        cache = PersistentEmbeddingCache(db_path=os.path.join(tmp, "emb.db"))
        cache.put("m", "a", [1.0])
        cache.put("m", "b", [2.0])
        results = cache.batch_get("m", ["a", "c", "b"])
        assert results["a"] == [1.0]
        assert results["b"] == [2.0]
        assert "c" not in results
