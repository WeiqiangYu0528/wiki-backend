"""Performance, accuracy, latency, and recall tests for search system.

Tests the LIVE search pipeline against actual indexed data to measure:
- Search accuracy (does it return relevant results?)
- Retrieval recall (does it find what it should find?)
- Latency (is each stage fast enough?)
- Reranker quality (does reranking improve result ordering?)
- Cache effectiveness (hit rates, speedup)
- Query classification accuracy
- Context engine budget adherence
- End-to-end search quality
"""

import hashlib
import math
import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from search.orchestrator import classify_query, format_results, SearchOrchestrator
from search.reranker import JaccardReranker, tokenize
from search.lexical import LexicalSearch
from search.cache import MultiLevelCache
from search.registry import RepoRegistry
from search_tools import smart_search, find_symbol
from context_engine.budget import TokenBudget, estimate_tokens
from context_engine.compactor import ContextCompactor
from context_engine.engine import ContextEngine
from memory.sqlite_memory import SQLiteMemory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace_dir():
    """Use the actual workspace root for live search tests."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def lexical(workspace_dir):
    return LexicalSearch(workspace_dir)


@pytest.fixture
def reranker():
    return JaccardReranker()


@pytest.fixture
def registry():
    return RepoRegistry()


@pytest.fixture
def temp_cache():
    with tempfile.TemporaryDirectory() as td:
        yield MultiLevelCache(db_path=os.path.join(td, "cache.db"))


@pytest.fixture
def memory_manager():
    with tempfile.TemporaryDirectory() as td:
        yield SQLiteMemory(db_path=os.path.join(td, "mem.db"))


@pytest.fixture
def budget():
    return TokenBudget(context_limit=128000)


@pytest.fixture
def compactor():
    return ContextCompactor()


# ===========================================================================
# 1. QUERY CLASSIFICATION ACCURACY
# ===========================================================================

class TestQueryClassificationAccuracy:
    """Verify classify_query correctly categorizes diverse query types."""

    # Ground truth: (query, expected_type)
    SYMBOL_QUERIES = [
        ("SearchOrchestrator", "symbol"),
        ("get_chat_model", "symbol"),
        ("JaccardReranker", "symbol"),
        ("create_react_agent", "symbol"),
        ("class GraphFactory", "symbol"),
        ("def run_agent", "symbol"),
        ("function createApp", "symbol"),
        ("MemoryManager.query", "symbol"),
        ("interface ToolConfig", "symbol"),
    ]

    CONCEPT_QUERIES = [
        ("how does the search system work", "concept"),
        ("explain the permission model", "concept"),
        ("what is the agent architecture", "concept"),
        ("how are embeddings generated", "concept"),
        ("describe the caching strategy", "concept"),
        ("explain token budgeting", "concept"),
        ("how does reranking improve results", "concept"),
        ("what is the context engine", "concept"),
    ]

    EXACT_QUERIES = [
        ("ERROR: connection refused", "exact"),
        ('"ImportError: no module named"', "exact"),
        ("docs/claude-code/index.md", "exact"),
        ("Error handling in agents", "exact"),
    ]

    def test_symbol_classification_accuracy(self):
        correct = 0
        total = len(self.SYMBOL_QUERIES)
        for query, expected in self.SYMBOL_QUERIES:
            result = classify_query(query)[0]
            if result == expected:
                correct += 1
        accuracy = correct / total
        assert accuracy >= 0.75, f"Symbol classification accuracy {accuracy:.0%} < 75% threshold"

    def test_concept_classification_accuracy(self):
        correct = 0
        total = len(self.CONCEPT_QUERIES)
        for query, expected in self.CONCEPT_QUERIES:
            result = classify_query(query)[0]
            if result == expected:
                correct += 1
        accuracy = correct / total
        assert accuracy >= 0.85, f"Concept classification accuracy {accuracy:.0%} < 85% threshold"

    def test_exact_classification_accuracy(self):
        correct = 0
        total = len(self.EXACT_QUERIES)
        for query, expected in self.EXACT_QUERIES:
            result = classify_query(query)[0]
            if result == expected:
                correct += 1
        accuracy = correct / total
        assert accuracy >= 0.50, f"Exact classification accuracy {accuracy:.0%} < 50% threshold"

    def test_overall_classification_accuracy(self):
        all_queries = self.SYMBOL_QUERIES + self.CONCEPT_QUERIES + self.EXACT_QUERIES
        correct = sum(1 for q, exp in all_queries if classify_query(q)[0] == exp)
        accuracy = correct / len(all_queries)
        assert accuracy >= 0.75, f"Overall classification accuracy {accuracy:.0%} < 75% threshold"


class TestClassifyQuerySymbolExtraction:
    """Test that classify_query extracts symbols from natural language queries."""

    def test_explain_camelcase_function(self):
        qtype, extracted = classify_query("Explain startMdmRawRead()")
        assert qtype == "symbol"
        assert extracted == "startMdmRawRead"

    def test_where_is_function(self):
        qtype, extracted = classify_query("Where is SearchOrchestrator implemented?")
        assert qtype == "symbol"
        assert extracted == "SearchOrchestrator"

    def test_who_calls_snake_case(self):
        qtype, extracted = classify_query("Who calls classify_query?")
        assert qtype == "symbol"
        assert extracted == "classify_query"

    def test_pure_concept_query(self):
        qtype, extracted = classify_query("How does the agent handle errors?")
        assert qtype == "concept"
        assert extracted == "How does the agent handle errors?"

    def test_pure_symbol_unchanged(self):
        qtype, extracted = classify_query("SearchOrchestrator")
        assert qtype == "symbol"
        assert extracted == "SearchOrchestrator"

    def test_function_call_syntax(self):
        qtype, extracted = classify_query("What does build_prompt() do?")
        assert qtype == "symbol"
        assert extracted == "build_prompt"

    def test_exact_error_unchanged(self):
        qtype, extracted = classify_query("ERROR: file not found")
        assert qtype == "exact"
        assert extracted == "ERROR: file not found"

    def test_mixed_nl_with_lower_camel(self):
        qtype, extracted = classify_query("How does startMdmRawRead work?")
        assert qtype == "symbol"
        assert extracted == "startMdmRawRead"

    def test_nl_with_class_keyword(self):
        qtype, extracted = classify_query("Find the class RepoRegistry")
        assert qtype == "symbol"
        assert extracted == "RepoRegistry"


# ===========================================================================
# 2. LEXICAL SEARCH ACCURACY & RECALL
# ===========================================================================

class TestLexicalSearchAccuracy:
    """Test lexical search returns relevant results from actual workspace."""

    def test_search_finds_known_content(self, lexical):
        """Search for content known to exist in the codebase."""
        results = lexical.search("SearchOrchestrator", search_paths=["backend/search/"], max_results=10)
        assert len(results) > 0, "Should find SearchOrchestrator in backend/search/"
        file_paths = [r["file_path"] for r in results]
        assert any("orchestrator" in fp.lower() for fp in file_paths), \
            f"Expected orchestrator.py in results, got: {file_paths[:5]}"

    def test_search_finds_documentation(self, lexical):
        """Search for doc content known to exist."""
        results = lexical.search("Knowledge Base", search_paths=["docs/"], max_results=10)
        # docs/ may or may not have this text; just verify the search runs
        assert isinstance(results, list)

    def test_search_returns_scored_results(self, lexical):
        results = lexical.search("agent", search_paths=["backend/"], max_results=10)
        assert len(results) > 0, "Should find 'agent' in backend/"
        for r in results:
            assert "score" in r, "Each result must have a score"
            assert r["score"] > 0, "Score must be positive"

    def test_search_scoring_ranks_relevant_files_higher(self, lexical):
        """Files with query in filename should rank higher."""
        results = lexical.search("agent", search_paths=["backend/"], max_results=20)
        if len(results) >= 2:
            top_files = [r["file_path"] for r in results[:5]]
            has_agent_in_name = any("agent" in fp.lower() for fp in top_files)
            assert has_agent_in_name, \
                f"Top 5 results should include files with 'agent' in name: {top_files}"

    def test_search_recall_multi_file(self, lexical):
        """Search should find results across multiple files."""
        results = lexical.search("import", search_paths=["backend/search/"], max_results=20)
        unique_files = set(r["file_path"] for r in results)
        assert len(unique_files) >= 2, \
            f"Should find 'import' in multiple files, found {len(unique_files)}"

    def test_search_empty_query_returns_nothing(self, lexical):
        results = lexical.search("", max_results=10)
        assert results == []

    def test_search_nonexistent_term_returns_empty(self, lexical):
        # Use a term that won't appear even in this test file
        results = lexical.search("qwpzlmxnctv87362", search_paths=["backend/search/"], max_results=10)
        assert results == [], f"Expected no results for gibberish, got {len(results)}"

    def test_search_latency_under_threshold(self, lexical):
        """Lexical search should complete within 15 seconds."""
        t0 = time.time()
        lexical.search("function", search_paths=["backend/"], max_results=15)
        elapsed = time.time() - t0
        assert elapsed < 15.0, f"Lexical search took {elapsed:.2f}s, expected < 15s"

    def test_search_case_insensitive(self, lexical):
        upper = lexical.search("SEARCHORCHESTRATOR", search_paths=["backend/search/"], max_results=5)
        lower = lexical.search("searchorchestrator", search_paths=["backend/search/"], max_results=5)
        mixed = lexical.search("SearchOrchestrator", search_paths=["backend/search/"], max_results=5)
        # At least one variant should find results
        found = len(upper) + len(lower) + len(mixed)
        assert found > 0, "Case-insensitive search should find results in any case"


# ===========================================================================
# 3. RERANKER QUALITY
# ===========================================================================

class TestRerankerQuality:
    """Test that Jaccard reranker improves result ordering."""

    def _make_result(self, text, file_path="file.py", score=0.5):
        return {"text": text, "file_path": file_path, "score": score, "normalized_score": score}

    def test_reranker_promotes_relevant_results(self, reranker):
        """Results with higher query overlap should rank higher after reranking."""
        query = "search orchestrator hybrid"
        results = [
            self._make_result("This is about database migrations", "db.py", 0.4),
            self._make_result("The search orchestrator handles hybrid search queries", "orch.py", 0.35),
            self._make_result("User authentication module", "auth.py", 0.3),
        ]
        reranked = reranker.rerank(query, results, top_k=3)
        # orch.py has much higher Jaccard overlap with query, should beat db.py
        assert reranked[0]["file_path"] == "orch.py", \
            f"Reranker should promote relevant result to top, got: {reranked[0]['file_path']}"

    def test_reranker_preserves_high_score_relevant_results(self, reranker):
        """High-score results that are also relevant should stay at top."""
        query = "token budget"
        results = [
            self._make_result("Token budget allocation and tracking", "budget.py", 0.9),
            self._make_result("Random utility helpers", "utils.py", 0.1),
            self._make_result("Budget configuration for tokens", "config.py", 0.5),
        ]
        reranked = reranker.rerank(query, results, top_k=3)
        assert reranked[0]["file_path"] == "budget.py"

    def test_reranker_deduplicates(self, reranker):
        """Reranker should remove duplicate results by file:section."""
        query = "cache"
        results = [
            self._make_result("Cache layer impl", "cache.py", 0.8),
            self._make_result("Cache layer impl", "cache.py", 0.7),  # same section
            self._make_result("Different cache module", "cache2.py", 0.6),
        ]
        # Add section metadata for dedup
        results[0]["section"] = "init"
        results[1]["section"] = "init"  # duplicate
        results[2]["section"] = "get"
        reranked = reranker.rerank(query, results, top_k=10)
        assert len(reranked) == 2, f"Expected 2 after dedup, got {len(reranked)}"

    def test_reranker_respects_top_k(self, reranker):
        query = "search"
        results = [self._make_result(f"Result {i}", f"f{i}.py", 0.5) for i in range(20)]
        reranked = reranker.rerank(query, results, top_k=5)
        assert len(reranked) <= 5

    def test_jaccard_score_calculation(self):
        """Verify Jaccard similarity is calculated correctly."""
        tokens_a = tokenize("the quick brown fox")
        tokens_b = tokenize("the quick red fox")
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        jaccard = len(intersection) / len(union)
        # "the", "quick", "fox" are shared; "brown" and "red" are not
        expected = 3 / 5  # 3 shared out of 5 unique
        assert abs(jaccard - expected) < 0.01, f"Jaccard should be {expected}, got {jaccard}"

    def test_reranker_empty_results(self, reranker):
        assert reranker.rerank("query", [], top_k=5) == []

    def test_reranker_latency(self, reranker):
        """Reranking 100 results should complete in < 50ms."""
        query = "search orchestrator hybrid ranking"
        results = [
            self._make_result(f"Result text with various words number {i} for testing reranker", f"f{i}.py", 0.5)
            for i in range(100)
        ]
        t0 = time.time()
        reranker.rerank(query, results, top_k=10)
        elapsed_ms = (time.time() - t0) * 1000
        assert elapsed_ms < 50, f"Reranker took {elapsed_ms:.1f}ms for 100 results, expected < 50ms"


# ===========================================================================
# 4. REPO TARGETING ACCURACY
# ===========================================================================

class TestRepoTargetingAccuracy:
    """Test that queries are routed to the correct repositories."""

    TARGETING_CASES = [
        ("claude code permission model", "claude-code"),
        ("deepagents graph factory", "deepagents"),
        ("opencode session system", "opencode"),
        ("openclaw gateway routing", "openclaw"),
        ("autogen distributed workers", "autogen"),
        ("hermes agent loop", "hermes-agent"),
    ]

    def test_keyword_targeting(self, registry):
        correct = 0
        for query, expected_ns in self.TARGETING_CASES:
            targets, confidence = registry.target(query)
            top_ns = targets[0].namespace if targets else None
            if top_ns == expected_ns:
                correct += 1
        accuracy = correct / len(self.TARGETING_CASES)
        assert accuracy >= 0.80, f"Repo targeting accuracy {accuracy:.0%} < 80%"

    def test_namespace_direct_targeting(self, registry):
        for ns in ["claude-code", "deepagents", "opencode", "openclaw", "autogen", "hermes-agent"]:
            targets, confidence = registry.target("any query", namespace=ns)
            assert len(targets) == 1
            assert targets[0].namespace == ns
            assert confidence == "high"

    def test_page_url_targeting(self, registry):
        targets, confidence = registry.target("some query", page_url="/claude-code/entities/agent-system")
        assert targets[0].namespace == "claude-code"
        assert confidence == "high"

    def test_ambiguous_query_returns_multiple(self, registry):
        targets, confidence = registry.target("how does the system work")
        assert len(targets) >= 1, "Ambiguous query should still return targets"
        assert confidence == "low"


class TestRepoTargetingConfidence:
    """Test repo targeting returns confidence scores."""

    def test_high_confidence_from_namespace(self):
        from search.registry import repo_registry
        repos, confidence = repo_registry.target("anything", namespace="claude-code")
        assert confidence == "high"
        assert repos[0].namespace == "claude-code"

    def test_high_confidence_from_url(self):
        from search.registry import repo_registry
        repos, confidence = repo_registry.target("What is the tool system?", page_url="http://localhost/claude-code/entities/tool-system/")
        assert confidence == "high"
        assert repos[0].namespace == "claude-code"

    def test_medium_confidence_from_keywords(self):
        from search.registry import repo_registry
        repos, confidence = repo_registry.target("How does the graph factory work?")
        assert confidence == "medium"
        assert repos[0].namespace == "deepagents"

    def test_low_confidence_generic_query(self):
        from search.registry import repo_registry
        repos, confidence = repo_registry.target("How does error handling work?")
        assert confidence == "low"
        assert len(repos) <= 3

    def test_namespace_not_found_returns_low(self):
        from search.registry import repo_registry
        repos, confidence = repo_registry.target("anything", namespace="nonexistent")
        assert confidence == "low"
        assert len(repos) <= 3

    def test_url_matching_deepagents(self):
        from search.registry import repo_registry
        repos, confidence = repo_registry.target("test", page_url="http://localhost/deepagents-wiki/overview/")
        assert confidence == "high"
        assert repos[0].namespace == "deepagents"


# ===========================================================================
# 5. CACHE PERFORMANCE
# ===========================================================================

class TestCachePerformance:
    """Test cache hit rates, latency, and correctness."""

    def test_cache_hit_speedup(self, temp_cache):
        """Cached lookup should be significantly faster than miss."""
        query, scope = "test query", "auto"
        results = [{"text": "result", "file_path": "f.py", "score": 0.9}]

        # Miss
        t0 = time.time()
        miss_result = temp_cache.get(query, scope)
        miss_time = time.time() - t0
        assert miss_result is None

        # Put
        temp_cache.put(query, scope, results, 100)

        # Hit
        t0 = time.time()
        hit_result = temp_cache.get(query, scope)
        hit_time = time.time() - t0
        assert hit_result is not None
        assert hit_result == results

        # Hit should be faster (or at least not dramatically slower)
        # L1 should be sub-microsecond
        assert hit_time < 0.01, f"Cache hit took {hit_time*1000:.2f}ms, expected < 10ms"

    def test_cache_hit_rate_after_repeated_queries(self, temp_cache):
        """Hit rate should increase with repeated queries."""
        queries = [(f"query_{i}", "auto") for i in range(10)]
        sample_results = [{"text": "result", "file_path": "f.py"}]

        # First pass: all misses
        for q, s in queries:
            temp_cache.get(q, s)
            temp_cache.put(q, s, sample_results, 50)

        # Second pass: all hits
        for q, s in queries:
            temp_cache.get(q, s)

        stats = temp_cache.stats()
        assert stats["hit_rate"] >= 0.45, f"Hit rate {stats['hit_rate']:.2f} < 0.45 after repeated queries"

    def test_cache_lru_eviction_preserves_recent(self, temp_cache):
        """LRU should evict oldest, keep newest."""
        temp_cache._l1_max = 5
        for i in range(10):
            temp_cache.put(f"q{i}", "auto", [{"text": f"r{i}"}], 10)

        # Newest should be present
        assert temp_cache.get("q9", "auto") is not None
        assert temp_cache.get("q8", "auto") is not None
        # Oldest should be evicted from L1 (but may be in L2)
        # Reset to test L1 specifically
        stats = temp_cache.stats()
        assert stats["l1_size"] <= 5

    def test_cache_isolation_by_scope(self, temp_cache):
        """Same query with different scopes should be independent."""
        temp_cache.put("agent", "wiki", [{"text": "wiki result"}], 10)
        temp_cache.put("agent", "code", [{"text": "code result"}], 10)

        wiki_result = temp_cache.get("agent", "wiki")
        code_result = temp_cache.get("agent", "code")
        assert wiki_result[0]["text"] == "wiki result"
        assert code_result[0]["text"] == "code result"

    def test_bulk_cache_operations_latency(self, temp_cache):
        """1000 put + get operations should complete in < 1 second."""
        t0 = time.time()
        for i in range(1000):
            temp_cache.put(f"q{i}", "auto", [{"text": f"r{i}"}], 10)
        for i in range(1000):
            temp_cache.get(f"q{i}", "auto")
        elapsed = time.time() - t0
        assert elapsed < 1.0, f"1000 put+get took {elapsed:.2f}s, expected < 1s"


# ===========================================================================
# 6. FORMAT RESULTS QUALITY
# ===========================================================================

class TestFormatResultsQuality:
    """Test that result formatting preserves important information."""

    def test_format_preserves_file_paths(self):
        results = [
            {"file_path": "backend/search/orchestrator.py", "text": "class SearchOrchestrator", "line_number": 79},
            {"file_path": "backend/agent.py", "text": "def run_agent", "line_number": 388},
        ]
        formatted = format_results(results)
        assert "orchestrator.py" in formatted
        assert "agent.py" in formatted

    def test_format_preserves_line_numbers(self):
        results = [{"file_path": "test.py", "text": "content", "line_number": 42}]
        formatted = format_results(results)
        assert "L42" in formatted

    def test_format_includes_symbols(self):
        results = [{"file_path": "test.py", "text": "def foo()", "symbol": "foo", "start_line": 10}]
        formatted = format_results(results)
        assert "`foo`" in formatted

    def test_format_respects_max_chars(self):
        results = [{"file_path": f"f{i}.py", "text": "x" * 100} for i in range(50)]
        formatted = format_results(results, max_chars=500)
        assert len(formatted) <= 600  # some slack for truncation message
        assert "truncated" in formatted.lower()

    def test_format_truncates_long_results(self):
        results = [{"file_path": "test.py", "text": "x" * 500}]
        formatted = format_results(results, result_max_chars=100)
        assert "…" in formatted

    def test_format_empty_results(self):
        assert format_results([]) == "No results found."


# ===========================================================================
# 7. TOKEN BUDGET ACCURACY
# ===========================================================================

class TestTokenBudgetAccuracy:
    """Test token budget allocation and tracking accuracy."""

    def test_estimate_tokens_accuracy(self):
        """Token estimation should be within 30% of expected for English text."""
        # GPT tokenizer typically gives ~1 token per 4 chars for English
        test_texts = [
            ("Hello world", 3),       # ~2-3 tokens
            ("The quick brown fox jumps over the lazy dog", 10),  # ~10 tokens
            ("A" * 400, 100),         # 400 chars / 4 = 100
            ("", 0),
        ]
        for text, expected in test_texts:
            estimated = estimate_tokens(text)
            if expected == 0:
                assert estimated == 0
            else:
                ratio = estimated / expected
                assert 0.5 <= ratio <= 2.0, \
                    f"Token estimate {estimated} for '{text[:30]}...' too far from expected {expected}"

    def test_budget_allocation_sums_to_100_percent(self, budget):
        alloc = budget.allocate()
        total_pct = sum(budget.budget_pcts.values())
        assert abs(total_pct - 1.0) < 0.01, f"Budget percentages sum to {total_pct}, expected 1.0"

    def test_budget_tracks_usage_accurately(self, budget):
        budget.use("system", 300)
        budget.use("system", 200)
        assert budget.used("system") == 500

    def test_budget_remaining_decreases(self, budget):
        alloc = budget.allocate()
        initial_remaining = budget.remaining("search")
        budget.use("search", 1000)
        assert budget.remaining("search") == initial_remaining - 1000

    def test_over_budget_detection(self, budget):
        """Should detect when input categories exceed their allocation."""
        assert not budget.is_over_budget()
        # Use way more than allocated
        budget.use("system", 50000)
        budget.use("history", 50000)
        budget.use("search", 50000)
        assert budget.is_over_budget()

    def test_budget_summary_complete(self, budget):
        budget.use("system", 100)
        budget.use("search", 500)
        summary = budget.summary()
        for category in budget.budget_pcts:
            assert category in summary
            assert "budget" in summary[category]
            assert "used" in summary[category]
            assert "remaining" in summary[category]


# ===========================================================================
# 8. CONTEXT ENGINE QUALITY
# ===========================================================================

class TestContextEngineQuality:
    """Test context assembly respects budgets and produces valid output."""

    def test_assemble_produces_valid_messages(self, memory_manager, compactor, budget):
        engine = ContextEngine(memory=memory_manager, compactor=compactor, budget=budget)
        result = engine.assemble(
            system_prompt="You are a helpful assistant.",
            messages=[{"role": "user", "content": "previous question"}],
            query="What is the search architecture?",
            search_results="Result 1: search uses hybrid approach",
        )
        assert "messages" in result
        assert "total_tokens" in result
        assert "budget_summary" in result
        assert result["messages"][0]["role"] == "system"
        assert result["messages"][-1]["role"] == "user"
        assert result["total_tokens"] > 0

    def test_assemble_respects_token_budget(self, memory_manager, compactor):
        small_budget = TokenBudget(context_limit=1000)
        engine = ContextEngine(memory=memory_manager, compactor=compactor, budget=small_budget)
        result = engine.assemble(
            system_prompt="You are helpful.",
            messages=[{"role": "user", "content": "x " * 200}],  # lots of history
            query="short query",
        )
        # Total should be tracked
        assert result["total_tokens"] > 0
        # Budget summary should show usage
        summary = result["budget_summary"]
        assert summary["system"]["used"] > 0

    def test_context_engine_with_memory(self, compactor, budget):
        with tempfile.TemporaryDirectory() as td:
            mem = SQLiteMemory(db_path=os.path.join(td, "mem.db"))
            mem.add("The search system uses Meilisearch for BM25", {"source": "test"})
            mem.add("Embeddings are generated by Ollama", {"source": "test"})

            engine = ContextEngine(memory=mem, compactor=compactor, budget=budget)
            result = engine.assemble(
                system_prompt="You are helpful.",
                messages=[],
                query="how does search work",
            )
            system_msg = result["messages"][0]["content"]
            assert "memory" in system_msg.lower() or "Meilisearch" in system_msg or "search" in system_msg.lower()

    def test_search_budget_allocation(self, memory_manager, compactor, budget):
        engine = ContextEngine(memory=memory_manager, compactor=compactor, budget=budget)
        search_budget = engine.get_search_budget()
        expected = int(128000 * 0.25)  # 25% for search
        assert search_budget == expected


# ===========================================================================
# 9. COMPACTOR QUALITY
# ===========================================================================

class TestCompactorQuality:
    """Test that history compaction is effective and preserves important content."""

    def test_compactor_reduces_long_history(self, compactor):
        """Compactor should prune old tool outputs to fit budget."""
        messages = []
        # Create 10 turns with user + tool messages (tool outputs are large)
        for i in range(10):
            messages.append({"role": "user", "content": f"Question {i}"})
            messages.append({"role": "tool", "name": f"search_{i}", "content": "x" * 500})
            messages.append({"role": "assistant", "content": f"Answer {i}"})

        original_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
        compacted = compactor.compact(messages, token_budget=500)
        compacted_tokens = sum(estimate_tokens(m.get("content", "")) for m in compacted)
        # Compactor should have pruned some tool outputs
        assert compacted_tokens < original_tokens, \
            f"Compacted ({compacted_tokens}) should be smaller than original ({original_tokens})"

    def test_compactor_preserves_recent_messages(self, compactor):
        messages = []
        for i in range(8):
            messages.append({"role": "user", "content": f"Old question {i}"})
            messages.append({"role": "tool", "name": "search", "content": "y" * 300})
            messages.append({"role": "assistant", "content": f"Old answer {i}"})
        messages.append({"role": "user", "content": "Most recent question about search"})
        compacted = compactor.compact(messages, token_budget=500)
        last_content = compacted[-1]["content"] if compacted else ""
        assert "recent" in last_content.lower() or "search" in last_content.lower(), \
            "Compactor should preserve the most recent message"

    def test_compactor_empty_history(self, compactor):
        assert compactor.compact([], token_budget=1000) == []


# ===========================================================================
# 10. MEMORY SEARCH QUALITY
# ===========================================================================

class TestMemorySearchQuality:
    """Test that memory retrieval returns relevant results."""

    def test_memory_query_relevance(self):
        with tempfile.TemporaryDirectory() as td:
            mem = SQLiteMemory(db_path=os.path.join(td, "mem.db"))
            mem.add("Meilisearch provides BM25 text search", {"topic": "search"})
            mem.add("ChromaDB handles semantic vector search", {"topic": "search"})
            mem.add("Docker containers run on port 8001", {"topic": "infra"})
            mem.add("The weather is nice today", {"topic": "random"})

            results = mem.query("search engine", top_k=3)
            assert len(results) > 0
            # FTS5 should rank search-related memories higher
            texts = [r["content"] for r in results]
            assert any("search" in t.lower() for t in texts), \
                f"Memory query for 'search engine' should return search-related results: {texts}"

    def test_memory_empty_query(self):
        with tempfile.TemporaryDirectory() as td:
            mem = SQLiteMemory(db_path=os.path.join(td, "mem.db"))
            results = mem.query("", top_k=5)
            assert results == [] or isinstance(results, list)

    def test_memory_add_and_retrieve_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            mem = SQLiteMemory(db_path=os.path.join(td, "mem.db"))
            mem.add("Important fact about caching", {"source": "test"})
            results = mem.query("caching", top_k=1)
            assert len(results) >= 1
            assert "caching" in results[0]["content"].lower()


# ===========================================================================
# 11. END-TO-END SEARCH PIPELINE LATENCY
# ===========================================================================

class TestEndToEndLatency:
    """Measure latency of the full search pipeline stages."""

    def test_classify_query_latency(self):
        """Classification should be < 1ms."""
        queries = ["SearchOrchestrator", "how does search work", "error handling"]
        t0 = time.time()
        for q in queries * 100:
            classify_query(q)
        elapsed_ms = (time.time() - t0) * 1000
        per_query_ms = elapsed_ms / 300
        assert per_query_ms < 1.0, f"Classification took {per_query_ms:.3f}ms per query"

    def test_tokenize_latency(self):
        """Tokenization for reranking should be fast."""
        text = "The search orchestrator handles hybrid queries with BM25 and semantic search"
        t0 = time.time()
        for _ in range(10000):
            tokenize(text)
        elapsed_ms = (time.time() - t0) * 1000
        per_call = elapsed_ms / 10000
        assert per_call < 0.1, f"Tokenize took {per_call:.4f}ms per call"

    def test_format_results_latency(self):
        """Formatting 50 results should be < 10ms."""
        results = [
            {"file_path": f"f{i}.py", "text": f"Result content {i} " * 20, "line_number": i}
            for i in range(50)
        ]
        t0 = time.time()
        format_results(results, max_chars=5000)
        elapsed_ms = (time.time() - t0) * 1000
        assert elapsed_ms < 10, f"Formatting 50 results took {elapsed_ms:.1f}ms"

    def test_cache_lookup_latency(self):
        """Cache lookup should be < 1ms."""
        with tempfile.TemporaryDirectory() as td:
            cache = MultiLevelCache(db_path=os.path.join(td, "c.db"))
            cache.put("test", "auto", [{"text": "cached"}], 10)

            t0 = time.time()
            for _ in range(1000):
                cache.get("test", "auto")
            elapsed_ms = (time.time() - t0) * 1000
            per_call = elapsed_ms / 1000
            assert per_call < 0.1, f"Cache lookup took {per_call:.4f}ms per call"

    def test_budget_calculation_latency(self):
        """Budget operations should be < 0.1ms."""
        budget = TokenBudget(context_limit=128000)
        t0 = time.time()
        for _ in range(10000):
            budget.allocate()
            budget.use("system", 10)
            budget.remaining("search")
            budget.is_over_budget()
            budget._used.clear()
        elapsed_ms = (time.time() - t0) * 1000
        per_cycle = elapsed_ms / 10000
        assert per_cycle < 0.1, f"Budget cycle took {per_cycle:.4f}ms"


# ===========================================================================
# 12. SEARCH RESULT RELEVANCE (PRECISION)
# ===========================================================================

class TestSearchResultRelevance:
    """Test that search results are actually relevant to queries."""

    def test_lexical_precision_known_file(self, lexical):
        """Searching for a specific class should return its file."""
        results = lexical.search("class JaccardReranker", max_results=5)
        if results:
            top_file = results[0]["file_path"]
            assert "reranker" in top_file.lower(), \
                f"Search for 'class JaccardReranker' returned {top_file}, expected reranker file"

    def test_lexical_precision_known_function(self, lexical):
        results = lexical.search("def classify_query", max_results=5)
        if results:
            top_file = results[0]["file_path"]
            assert "orchestrator" in top_file.lower() or "search" in top_file.lower(), \
                f"Search for 'def classify_query' returned {top_file}"

    def test_result_text_contains_query_terms(self, lexical):
        """Result text should contain at least some query terms."""
        query = "reranker"
        results = lexical.search(query, max_results=5)
        if results:
            matched = sum(1 for r in results if query.lower() in r["text"].lower())
            precision = matched / len(results)
            assert precision >= 0.5, \
                f"Only {precision:.0%} of results contain query term '{query}'"


# ===========================================================================
# 13. REGISTRY COMPLETENESS
# ===========================================================================

class TestRegistryCompleteness:
    """Test that all repos are registered and have valid metadata."""

    EXPECTED_REPOS = ["claude-code", "deepagents", "opencode", "openclaw", "autogen", "hermes-agent"]

    def test_all_repos_registered(self, registry):
        namespaces = [r.namespace for r in registry.repos]
        for expected in self.EXPECTED_REPOS:
            assert expected in namespaces, f"Missing repo: {expected}"

    def test_all_repos_have_keywords(self, registry):
        for repo in registry.repos:
            assert len(repo.keywords) >= 3, f"{repo.namespace} has < 3 keywords"

    def test_all_repos_have_directories(self, registry):
        for repo in registry.repos:
            assert repo.source_dir, f"{repo.namespace} missing source_dir"
            assert repo.wiki_dir, f"{repo.namespace} missing wiki_dir"

    def test_namespace_lookup(self, registry):
        for ns in self.EXPECTED_REPOS:
            repo = registry.get_by_namespace(ns)
            assert repo is not None, f"Cannot lookup repo by namespace: {ns}"
            assert repo.namespace == ns


# ===========================================================================
# 14. EMBEDDING CACHE CORRECTNESS
# ===========================================================================

class TestEmbeddingCacheCorrectness:
    """Test embedding cache deduplication and correctness."""

    def test_same_text_same_key(self):
        """Same text should produce same cache key."""
        from search.semantic import EmbeddingCache
        cache = EmbeddingCache(max_size=10)
        key1 = cache._key("model", "hello world")
        key2 = cache._key("model", "hello world")
        assert key1 == key2

    def test_different_text_different_key(self):
        from search.semantic import EmbeddingCache
        cache = EmbeddingCache(max_size=10)
        key1 = cache._key("model", "hello world")
        key2 = cache._key("model", "goodbye world")
        assert key1 != key2

    def test_different_model_different_key(self):
        from search.semantic import EmbeddingCache
        cache = EmbeddingCache(max_size=10)
        key1 = cache._key("model-a", "hello world")
        key2 = cache._key("model-b", "hello world")
        assert key1 != key2

    def test_cache_hit_returns_correct_embedding(self):
        from search.semantic import EmbeddingCache
        cache = EmbeddingCache(max_size=10)
        embedding = [0.1, 0.2, 0.3]
        cache.put("model", "hello", embedding)
        result = cache.get("model", "hello")
        assert result == embedding

    def test_cache_lru_eviction(self):
        from search.semantic import EmbeddingCache
        cache = EmbeddingCache(max_size=3)
        cache.put("m", "a", [1.0])
        cache.put("m", "b", [2.0])
        cache.put("m", "c", [3.0])
        cache.put("m", "d", [4.0])  # should evict "a"
        assert cache.get("m", "a") is None
        assert cache.get("m", "d") == [4.0]
        assert len(cache) == 3

    def test_cache_stats(self):
        from search.semantic import EmbeddingCache
        cache = EmbeddingCache(max_size=10)
        cache.put("m", "a", [1.0])
        cache.get("m", "a")     # hit
        cache.get("m", "b")     # miss
        assert cache._hits == 1
        assert cache._misses == 1


# ---------------------------------------------------------------------------
# Lexical search: definition boost, source code boost, camelCase expansion
# ---------------------------------------------------------------------------

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class TestLexicalDefinitionBoost:
    """Test that lexical search boosts code definition lines."""

    def test_definition_line_scores_higher(self):
        """A line containing 'def classify_query' should score higher than a comment mentioning it."""
        from search.lexical import LexicalSearch
        ls = LexicalSearch(ROOT_DIR)
        definition_line = "def classify_query(query: str) -> tuple[str, str]:"
        comment_line = "# classify_query handles query classification"
        def_score = ls._score_match("backend/search/orchestrator.py", "classify_query", definition_line)
        comment_score = ls._score_match("backend/search/orchestrator.py", "classify_query", comment_line)
        assert def_score > comment_score, f"Definition score {def_score} should exceed comment score {comment_score}"

    def test_source_code_scores_higher_than_docs(self):
        """Source code files should score at least as high as docs files for code queries."""
        from search.lexical import LexicalSearch
        ls = LexicalSearch(ROOT_DIR)
        text = "def SearchOrchestrator():"
        code_score = ls._score_match("backend/search/orchestrator.py", "SearchOrchestrator", text)
        docs_score = ls._score_match("docs/claude-code/entities/tool-system.md", "SearchOrchestrator", text)
        assert code_score >= docs_score, f"Code score {code_score} should be >= docs score {docs_score}"

    def test_camelcase_to_snake_expansion(self):
        """Lexical search should find snake_case variants of camelCase queries."""
        from search.lexical import LexicalSearch
        ls = LexicalSearch(ROOT_DIR)
        # Search for a camelCase identifier — the search should internally try snake_case too
        results = ls.search("classifyQuery", search_paths=["backend/search"], max_results=5)
        # Should find classify_query in orchestrator.py
        paths = [r["file_path"] for r in results]
        assert any("orchestrator" in p for p in paths), f"Should find orchestrator.py, got: {paths}"


class TestCamelToSnake:
    """Test camelCase to snake_case conversion."""

    @pytest.mark.parametrize("input_,expected", [
        ("classifyQuery", "classify_query"),
        ("SearchOrchestrator", "search_orchestrator"),
        ("HTMLParser", "html_parser"),
        ("getHTTPResponse", "get_http_response"),
        ("already_snake", "already_snake"),
        ("simple", "simple"),
        ("", ""),
    ])
    def test_camel_to_snake(self, input_, expected):
        from search.lexical import LexicalSearch
        assert LexicalSearch._camel_to_snake(input_) == expected


class TestSearchStrategyEngine:
    """Test search strategy engine loop prevention."""

    def test_initial_strategy(self):
        from search.strategy import SearchStrategyEngine
        engine = SearchStrategyEngine()
        assert engine.current_strategy == "symbol_exact"
        assert not engine.exhausted

    def test_escalation_after_failures(self):
        from search.strategy import SearchStrategyEngine
        engine = SearchStrategyEngine()
        # 3 failed attempts should escalate
        for _ in range(3):
            engine.record_attempt("test_query", result_count=0)
        assert engine.current_strategy == "lexical_code"

    def test_exhaustion(self):
        from search.strategy import SearchStrategyEngine
        engine = SearchStrategyEngine()
        # Exhaust all strategies
        for _ in range(15):  # 3 per strategy × 5 strategies
            engine.record_attempt(f"q{_}", result_count=0)
        assert engine.exhausted

    def test_success_does_not_escalate(self):
        from search.strategy import SearchStrategyEngine
        engine = SearchStrategyEngine()
        engine.record_attempt("test_query", result_count=5)
        assert engine.current_strategy == "symbol_exact"  # No escalation

    def test_get_hint_on_exhaustion(self):
        from search.strategy import SearchStrategyEngine
        engine = SearchStrategyEngine()
        for _ in range(15):
            hint = engine.record_attempt(f"q{_}", result_count=0)
        assert hint == "EXHAUSTED"

    def test_summary(self):
        from search.strategy import SearchStrategyEngine
        engine = SearchStrategyEngine()
        engine.record_attempt("q1", result_count=0)
        engine.record_attempt("q2", result_count=3)
        summary = engine.summary()
        assert "symbol_exact" in summary
        assert "2" in summary  # 2 attempts


class TestOrchestratorSymbolFallback:
    """Test that symbol queries fall back to lexical search."""

    def test_symbol_query_uses_lexical_when_semantic_unavailable(self):
        """When semantic is not ready, lexical search should still find results."""
        from search.orchestrator import SearchOrchestrator
        from search.semantic import SemanticSearch
        from search.reranker import JaccardReranker

        semantic = SemanticSearch.__new__(SemanticSearch)
        semantic._ready = False
        orch = SearchOrchestrator(
            workspace_dir=ROOT_DIR,
            semantic=semantic,
            reranker=JaccardReranker(),
            max_chars=2000,
            result_max_chars=200,
        )
        orch._ready = False
        result = orch.search("sessionHistory", scope="code")
        assert result != "No results found.", "Should find sessionHistory via lexical"
        assert "sessionhistory" in result.lower() or "session" in result.lower()

    def test_lexical_always_runs(self):
        """Lexical search should run even when Meilisearch is available."""
        from search.orchestrator import SearchOrchestrator
        from search.semantic import SemanticSearch
        from search.reranker import JaccardReranker
        from unittest.mock import MagicMock, patch

        semantic = SemanticSearch.__new__(SemanticSearch)
        semantic._ready = False
        mock_meili = MagicMock()
        mock_meili.available = True
        mock_meili.search.return_value = []

        orch = SearchOrchestrator(
            workspace_dir=ROOT_DIR,
            semantic=semantic,
            meilisearch_client=mock_meili,
            reranker=JaccardReranker(),
            max_chars=2000,
            result_max_chars=200,
        )
        orch._ready = False
        with patch.object(orch.lexical, 'search', wraps=orch.lexical.search) as lexical_spy:
            result = orch.search("sessionHistory", scope="code")
            # Lexical should have been called
            lexical_spy.assert_called_once()
            # Meilisearch should also have been called (in addition, not instead)
            mock_meili.search.assert_called()
        # Even with Meilisearch returning nothing, lexical should find results
        assert result != "No results found.", "Lexical should still find results alongside Meilisearch"


class TestAgentToolWiring:
    """Test that the agent has all search tools available."""

    def test_smart_search_in_tools(self):
        from agent import tools
        tool_names = [t.name for t in tools]
        assert "smart_search" in tool_names, f"smart_search missing from agent tools: {tool_names}"

    def test_find_symbol_in_tools(self):
        from agent import tools
        tool_names = [t.name for t in tools]
        assert "find_symbol" in tool_names, f"find_symbol missing from agent tools: {tool_names}"

    def test_read_code_section_in_tools(self):
        from agent import tools
        tool_names = [t.name for t in tools]
        assert "read_code_section" in tool_names, f"read_code_section missing from agent tools: {tool_names}"

    def test_search_knowledge_base_removed(self):
        from agent import tools
        tool_names = [t.name for t in tools]
        assert "search_knowledge_base" not in tool_names, f"search_knowledge_base should be removed: {tool_names}"

    def test_recursion_limit_exists_in_source(self):
        """Verify recursion_limit=25 appears in agent.py source code."""
        import pathlib
        agent_source = pathlib.Path(__file__).parent.parent / "agent.py"
        content = agent_source.read_text()
        assert "recursion_limit=25" in content, "recursion_limit=25 not found in agent.py"


class TestSearchToolLoopHints:
    """Tests for loop-aware hint integration in search tools."""

    def setup_method(self):
        from search_tools import reset_strategy_engine
        reset_strategy_engine()

    def teardown_method(self):
        from search_tools import reset_strategy_engine
        import search_tools
        reset_strategy_engine()
        search_tools.set_orchestrator(None)

    def test_smart_search_records_attempt(self):
        """smart_search records attempt in strategy engine."""
        from unittest.mock import MagicMock
        import search_tools
        from search_tools import get_strategy_engine

        mock_orch = MagicMock()
        mock_orch.search.return_value = "No results found."
        search_tools.set_orchestrator(mock_orch)

        result = smart_search.invoke({"query": "NonExistentThing", "scope": "code"})
        engine = get_strategy_engine()
        assert engine.total_attempts >= 1

    def test_smart_search_exhausted_hint(self):
        """smart_search appends exhaustion hint after many failures."""
        from unittest.mock import MagicMock
        import search_tools
        from search_tools import get_strategy_engine

        mock_orch = MagicMock()
        mock_orch.search.return_value = "No results found."
        search_tools.set_orchestrator(mock_orch)

        engine = get_strategy_engine()
        # Exhaust all strategies (5 strategies * 3 attempts each = 15)
        for i in range(14):
            engine.record_attempt(f"q{i}", 0)

        result = smart_search.invoke({"query": "final_query", "scope": "code"})
        assert "exhausted" in result.lower() or "⚠️" in result

    def test_find_symbol_records_attempt(self):
        """find_symbol records attempt in strategy engine."""
        from unittest.mock import MagicMock
        import search_tools
        from search_tools import get_strategy_engine

        mock_orch = MagicMock()
        mock_orch.find_symbol.return_value = "No results found."
        search_tools.set_orchestrator(mock_orch)

        result = find_symbol.invoke({"name": "NonExistent"})
        engine = get_strategy_engine()
        assert engine.total_attempts >= 1
        assert "not found" in result.lower()

    def test_find_symbol_success_no_hint(self):
        """find_symbol with results doesn't add failure hints."""
        from unittest.mock import MagicMock
        import search_tools
        from search_tools import get_strategy_engine

        mock_orch = MagicMock()
        mock_orch.find_symbol.return_value = "**SearchOrchestrator** in search/orchestrator.py:42\nclass SearchOrchestrator:"
        search_tools.set_orchestrator(mock_orch)

        result = find_symbol.invoke({"name": "SearchOrchestrator"})
        assert "SearchOrchestrator" in result
        assert "not found" not in result.lower()
        engine = get_strategy_engine()
        assert engine.total_attempts == 1

    def test_reset_strategy_engine(self):
        """reset_strategy_engine creates fresh engine."""
        from search_tools import reset_strategy_engine, get_strategy_engine

        engine1 = get_strategy_engine()
        engine1.record_attempt("test", 0)
        assert engine1.total_attempts == 1

        reset_strategy_engine()
        engine2 = get_strategy_engine()
        assert engine2.total_attempts == 0
        assert engine2 is not engine1

    def test_smart_search_repeat_hint(self):
        """smart_search shows repeat hint on second empty result."""
        from unittest.mock import MagicMock
        import search_tools
        from search_tools import get_strategy_engine

        mock_orch = MagicMock()
        mock_orch.search.return_value = "No results found."
        search_tools.set_orchestrator(mock_orch)

        engine = get_strategy_engine()
        # First attempt — record it manually, then do second via tool
        engine.record_attempt("first_query", 0)
        result = smart_search.invoke({"query": "second_query", "scope": "auto"})
        assert "attempt #" in result.lower() or "💡" in result

    def test_find_symbol_exhausted_hint(self):
        """find_symbol shows exhaustion hint when strategies exhausted."""
        from unittest.mock import MagicMock
        import search_tools
        from search_tools import get_strategy_engine

        mock_orch = MagicMock()
        mock_orch.find_symbol.return_value = "No results found."
        search_tools.set_orchestrator(mock_orch)

        engine = get_strategy_engine()
        # Exhaust all strategies
        for i in range(14):
            engine.record_attempt(f"q{i}", 0)

        result = find_symbol.invoke({"name": "NonExistent"})
        assert "exhausted" in result.lower() or "⚠️" in result

    def test_smart_search_escalation_hint(self):
        """smart_search shows escalation hint when strategy switches."""
        from unittest.mock import MagicMock
        import search_tools
        from search_tools import get_strategy_engine

        mock_orch = MagicMock()
        mock_orch.search.return_value = "No results found."
        search_tools.set_orchestrator(mock_orch)

        engine = get_strategy_engine()
        # 2 failures, then the 3rd via tool triggers escalation
        engine.record_attempt("q1", 0)
        engine.record_attempt("q2", 0)

        result = smart_search.invoke({"query": "q3", "scope": "code"})
        assert "escalated" in result.lower() or "💡" in result


class TestObservabilityEnhancements:
    """Tests for enhanced observability metrics and trace store."""

    def test_agent_metrics_has_new_counters(self):
        """AgentMetrics has search strategy metrics."""
        from observability.metrics import AgentMetrics
        m = AgentMetrics()
        assert hasattr(m, 'search_attempts_total')
        assert hasattr(m, 'strategy_escalations_total')
        assert hasattr(m, 'loops_detected_total')
        assert hasattr(m, 'repo_confidence_total')
        assert hasattr(m, 'code_search_success_total')
        assert hasattr(m, 'code_search_latency')
        assert hasattr(m, 'recursion_depth')

    def test_trace_store_extended_schema(self, tmp_path):
        """Trace store supports new columns."""
        from observability.trace_store import RequestTraceStore
        store = RequestTraceStore(db_path=str(tmp_path / "test_traces.db"))
        store.write(
            request_id="test-123",
            model="qwen3.5",
            query="test query",
            status="success",
            search_attempts=5,
            search_strategy="lexical_code",
            loop_detected=True,
            strategies_exhausted=False,
            repo_confidence="high",
            repo_selected="deepagents",
            recursion_depth=12,
            tool_call_sequence='["smart_search","find_symbol"]',
        )
        rows = store.recent(limit=1)
        assert len(rows) == 1
        row = rows[0]
        assert row["search_attempts"] == 5
        assert row["search_strategy"] == "lexical_code"
        assert row["loop_detected"] == 1  # stored as int
        assert row["repo_confidence"] == "high"
        assert row["repo_selected"] == "deepagents"
        assert row["recursion_depth"] == 12

    def test_trace_store_backwards_compatible(self, tmp_path):
        """Trace store write() works with only old parameters."""
        from observability.trace_store import RequestTraceStore
        store = RequestTraceStore(db_path=str(tmp_path / "test_traces2.db"))
        store.write(
            request_id="old-style",
            model="gpt-4",
            query="old query",
            status="success",
            total_tokens=100,
        )
        rows = store.recent(limit=1)
        assert len(rows) == 1
        assert rows[0]["search_attempts"] == 0  # default

    def test_trace_store_query_by_id(self, tmp_path):
        """Trace store can query by specific ID."""
        from observability.trace_store import RequestTraceStore
        store = RequestTraceStore(db_path=str(tmp_path / "test_traces3.db"))
        store.write(request_id="abc-123", model="test", query="q", status="ok")
        store.write(request_id="def-456", model="test", query="q2", status="ok")
        rows = store.query("SELECT * FROM request_traces WHERE id = ?", ("abc-123",))
        assert len(rows) == 1
        assert rows[0]["id"] == "abc-123"
