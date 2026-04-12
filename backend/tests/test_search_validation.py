"""Search validation test suite.

Covers: classify_query, format_results, JaccardReranker,
SearchOrchestrator (empty query, cache integration),
and PersistentEmbeddingCache dedup.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from search.orchestrator import classify_query, format_results
from search.reranker import JaccardReranker
from search.cache import MultiLevelCache
from search.embedding_cache import PersistentEmbeddingCache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def cache(tmp_dir):
    return MultiLevelCache(db_path=os.path.join(tmp_dir, "cache.db"))


@pytest.fixture()
def reranker():
    return JaccardReranker()


def _make_orchestrator(tmp_dir, cache=None, reranker=None):
    """Build a SearchOrchestrator with mocks for heavy dependencies."""
    from unittest.mock import MagicMock

    semantic_mock = MagicMock()
    semantic_mock.query.return_value = []

    registry_mock = MagicMock()
    registry_mock.target.return_value = []

    from search.orchestrator import SearchOrchestrator

    return SearchOrchestrator(
        workspace_dir=tmp_dir,
        semantic=semantic_mock,
        registry=registry_mock,
        meilisearch_client=None,
        reranker=reranker,
        cache=cache,
    )


# ===========================================================================
# 1–3  classify_query
# ===========================================================================


class TestClassifyQuery:
    def test_classify_query_symbol_camelcase(self):
        assert classify_query("MemoryMiddleware")[0] == "symbol"
        assert classify_query("SearchOrchestrator")[0] == "symbol"
        assert classify_query("MyClass")[0] == "symbol"

    def test_classify_query_symbol_snake_case(self):
        assert classify_query("my_function")[0] == "symbol"
        assert classify_query("get_search_results")[0] == "symbol"

    def test_classify_query_symbol_dotted(self):
        assert classify_query("module.method")[0] == "symbol"

    def test_classify_query_concept(self):
        assert classify_query("how does caching work")[0] == "concept"
        assert classify_query("parallel search pipeline")[0] == "concept"

    def test_classify_query_exact_quoted(self):
        assert classify_query('"exact phrase"')[0] == "exact"
        assert classify_query("some 'quoted' text")[0] == "exact"

    def test_classify_query_exact_error(self):
        assert classify_query("ERROR: connection refused")[0] == "exact"
        assert classify_query("Error: file not found")[0] == "exact"

    def test_classify_query_exact_path(self):
        # Paths with `/` and no spaces → "exact" (only if no `.` which triggers symbol first)
        assert classify_query("src/utils/helper")[0] == "exact"


# ===========================================================================
# 4–7  format_results
# ===========================================================================


class TestFormatResults:
    def test_format_results_empty(self):
        assert format_results([]) == "No results found."

    def test_format_results_normal(self):
        results = [
            {"file_path": "a.py", "text": "hello world", "line_number": 10},
            {"file_path": "b.py", "text": "foo bar"},
        ]
        out = format_results(results)
        assert "**a.py** (L10)" in out
        assert "hello world" in out
        assert "**b.py**" in out
        assert "foo bar" in out

    def test_format_results_with_symbol(self):
        results = [
            {"file_path": "c.py", "text": "body", "line_number": 5, "symbol": "MyClass"},
        ]
        out = format_results(results)
        assert "`MyClass`" in out

    def test_format_results_truncation(self):
        results = [
            {"file_path": f"file{i}.py", "text": "x" * 100}
            for i in range(50)
        ]
        out = format_results(results, max_chars=300)
        assert "more results truncated" in out

    def test_format_results_long_text_trimmed(self):
        long_text = "a" * 500
        results = [{"file_path": "f.py", "text": long_text}]
        out = format_results(results, result_max_chars=50)
        assert out.endswith("…")
        assert "a" * 50 in out
        assert "a" * 51 not in out.split("…")[0].split("\n")[-1]


# ===========================================================================
# 8–11  JaccardReranker
# ===========================================================================


class TestReranker:
    def test_reranker_ordering(self, reranker):
        results = [
            {"file_path": "low.py", "text": "unrelated content", "score": 0.5},
            {"file_path": "high.py", "text": "search query overlap tokens", "score": 0.5},
        ]
        ranked = reranker.rerank("search query overlap", results, top_k=5)
        assert ranked[0]["file_path"] == "high.py"

    def test_reranker_dedup(self, reranker):
        results = [
            {"file_path": "a.py", "section": "intro", "text": "hello", "score": 0.9},
            {"file_path": "a.py", "section": "intro", "text": "hello again", "score": 0.8},
            {"file_path": "b.py", "section": "body", "text": "world", "score": 0.7},
        ]
        ranked = reranker.rerank("hello", results, top_k=10)
        keys = [f"{r['file_path']}:{r['section']}" for r in ranked]
        assert len(keys) == len(set(keys))
        assert len(ranked) == 2

    def test_reranker_top_k(self, reranker):
        results = [
            {"file_path": f"f{i}.py", "text": f"token{i}", "score": float(i)}
            for i in range(20)
        ]
        ranked = reranker.rerank("token0", results, top_k=3)
        assert len(ranked) <= 3

    def test_reranker_empty_input(self, reranker):
        assert reranker.rerank("anything", []) == []


# ===========================================================================
# 12–13  SearchOrchestrator
# ===========================================================================


class TestSearchOrchestrator:
    def test_search_empty_query(self, tmp_dir):
        orch = _make_orchestrator(tmp_dir)
        assert orch.search("") == "No results found."
        assert orch.search("   ") == "No results found."

    def test_search_cache_integration(self, tmp_dir, cache):
        orch = _make_orchestrator(tmp_dir, cache=cache)

        # First call populates cache (lexical fallback returns nothing → "No results found.")
        result1 = orch.search("unique_test_query", scope="auto")

        # Manually seed the cache with known results so second call is a cache hit
        cache.put("seeded_query", "auto", [{"file_path": "cached.py", "text": "from cache"}], 10)

        hits_before = cache._hits
        result2 = orch.search("seeded_query", scope="auto")
        assert cache._hits == hits_before + 1
        assert "cached.py" in result2
        assert "from cache" in result2


# ===========================================================================
# 14  PersistentEmbeddingCache
# ===========================================================================


class TestEmbeddingCache:
    def test_embedding_cache_dedup(self, tmp_dir):
        ec = PersistentEmbeddingCache(db_path=os.path.join(tmp_dir, "emb.db"))
        model = "test-model"
        vec = [0.1, 0.2, 0.3]

        # Miss
        assert ec.get(model, "hello") is None
        assert ec.stats["misses"] == 1

        # Store
        ec.put(model, "hello", vec)

        # Hit (same text)
        cached = ec.get(model, "hello")
        assert cached is not None
        assert len(cached) == 3
        assert abs(cached[0] - 0.1) < 1e-5
        assert ec.stats["hits"] == 1

        # Different text → miss
        assert ec.get(model, "world") is None
        assert ec.stats["misses"] == 2
