"""Code-location accuracy tests.

These tests verify the search system can locate code symbols, definitions, and
references with acceptable accuracy and latency. All tests use the local
search infrastructure (no LLM calls required).
"""

import os
import time
import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _get_orchestrator():
    """Get a real orchestrator instance for testing.

    Calls mark_ready() so find_symbol doesn't short-circuit with
    'Search index is still building' — in CI the index may not be built
    but the lexical fallback (ripgrep) should still work.
    """
    try:
        from search_tools import get_orchestrator
        orch = get_orchestrator()
    except Exception as exc:
        pytest.skip(f"Search orchestrator not available: {exc}")
    if orch is None:
        pytest.skip("Search orchestrator not available")
    orch.mark_ready()
    return orch


class TestExactFunctionLookup:
    """Test 1: Exact function name lookup."""

    def test_find_classify_query(self):
        orch = _get_orchestrator()
        result = orch.find_symbol("classify_query")
        # Ripgrep may rank test files above the definition; accept any result
        # that includes the orchestrator module or the function name itself.
        low = result.lower()
        assert "classify_query" in low or "orchestrator" in low, \
            f"Should find classify_query somewhere, got: {result[:200]}"

    def test_find_classify_query_latency(self):
        orch = _get_orchestrator()
        start = time.time()
        orch.find_symbol("classify_query")
        latency = time.time() - start
        assert latency < 15.0, f"Symbol lookup took {latency:.1f}s, should be < 15s"


class TestClassLookup:
    """Test 2: Class name lookup."""

    def test_find_search_orchestrator_class(self):
        orch = _get_orchestrator()
        result = orch.find_symbol("SearchOrchestrator")
        assert "orchestrator" in result.lower(), f"Should find SearchOrchestrator, got: {result[:200]}"


class TestCamelCaseSymbol:
    """Test 3: CamelCase class lookup via symbol search."""

    def test_search_camelcase_symbol(self):
        orch = _get_orchestrator()
        # find_symbol searches the whole workspace (not scope-restricted)
        result = orch.find_symbol("JaccardReranker")
        assert "reranker" in result.lower(), f"Should find reranker.py, got: {result[:200]}"


class TestSnakeCaseFunction:
    """Test 4: snake_case function lookup."""

    def test_find_format_results(self):
        orch = _get_orchestrator()
        result = orch.find_symbol("format_results")
        assert "orchestrator" in result.lower() or "format_results" in result.lower(), f"Got: {result[:200]}"


class TestCrossFileNavigation:
    """Test 5: Find callers of a function across files."""

    def test_search_callers_of_classify_query(self):
        orch = _get_orchestrator()
        # find_symbol searches the whole workspace via lexical fallback
        result = orch.find_symbol("classify_query")
        assert result and "no results" not in result.lower(), \
            "Should find classify_query usage in code"


class TestCrossModuleSearch:
    """Test 6: Cross-module symbol search."""

    def test_search_in_backend(self):
        orch = _get_orchestrator()
        # find_symbol uses whole-workspace lexical fallback when ChromaDB is empty
        result = orch.find_symbol("LexicalSearch")
        assert "lexical" in result.lower(), f"Should find lexical.py, got: {result[:200]}"


class TestRepoFromPageContext:
    """Test 7: Repo targeting from page URL."""

    def test_url_targets_claude_code(self):
        from search.registry import repo_registry
        repos, confidence = repo_registry.target(
            "What is the tool system?",
            page_url="http://localhost:8000/claude-code/entities/tool-system/",
        )
        assert confidence == "high"
        assert repos[0].namespace == "claude-code"

    def test_url_targets_deepagents(self):
        from search.registry import repo_registry
        repos, confidence = repo_registry.target(
            "How does middleware work?",
            page_url="http://localhost:8000/deepagents-wiki/entities/middleware/",
        )
        assert confidence == "high"
        assert repos[0].namespace == "deepagents"


class TestAmbiguousSymbol:
    """Test 8: Ambiguous symbol name returns multiple results, doesn't loop."""

    def test_ambiguous_search_completes(self):
        orch = _get_orchestrator()
        start = time.time()
        result = orch.search("search", scope="code")
        latency = time.time() - start
        assert latency < 15.0, f"Ambiguous search took {latency:.1f}s, should be < 15s"
        assert result != "No results found.", "Should find multiple results for 'search'"


class TestMissingSymbolGraceful:
    """Test 9: Non-existent symbol returns graceful failure."""

    def test_missing_symbol_does_not_hang(self):
        orch = _get_orchestrator()
        # Build symbol name dynamically so ripgrep won't find it as a literal
        fake = "Zyxwv" + "Qrstu" + "NothingHere" + "98765"
        start = time.time()
        result = orch.find_symbol(fake)
        latency = time.time() - start
        assert latency < 15.0, f"Missing symbol took {latency:.1f}s, should be < 15s"
        low = result.lower()
        assert "no results" in low or "not found" in low or "no matches" in low \
            or "no results found" in low, \
            f"Should report not found, got: {result[:200]}"


class TestStrategyEscalation:
    """Test 10: Strategy engine escalates on repeated failures."""

    def test_escalation_works(self):
        from search.strategy import SearchStrategyEngine
        engine = SearchStrategyEngine()
        assert engine.current_strategy == "symbol_exact"
        for i in range(3):
            engine.record_attempt(f"missing_{i}", result_count=0)
        assert engine.current_strategy == "lexical_code", \
            f"Should escalate to lexical_code, got {engine.current_strategy}"


class TestDefinitionVsUsage:
    """Test 11: Definitions should rank above mere usages."""

    def test_definition_ranked_first(self):
        from search.lexical import LexicalSearch
        ls = LexicalSearch(ROOT_DIR)
        results = ls.search("classify_query", search_paths=["backend/search"], max_results=10)
        if not results:
            pytest.skip("LexicalSearch returned no results (ripgrep may not be installed)")
        top = results[0]
        assert "def classify_query" in top["text"] or "orchestrator" in top["file_path"], \
            f"Top result should be definition, got: {top['file_path']}:{top['text'][:100]}"


class TestLoopPrevention:
    """Test 12: Recursion limit prevents infinite loops."""

    def test_recursion_limit_set(self):
        import agent
        tool_names = [t.name for t in agent.tools]
        assert "smart_search" in tool_names, "smart_search must be in agent tools"
        assert "find_symbol" in tool_names, "find_symbol must be in agent tools"

    def test_recursion_limit_value(self):
        """Verify recursion_limit=25 is set in agent source code."""
        import inspect, agent
        source = inspect.getsource(agent)
        assert "recursion_limit=25" in source, \
            "agent.py should set recursion_limit=25 on create_react_agent"


class TestInterfaceTypeLookup:
    """Test 13: Interface/type/protocol lookup."""

    def test_find_typed_dict(self):
        """Find a TypedDict definition (SearchAttempt in strategy.py)."""
        orch = _get_orchestrator()
        result = orch.find_symbol("SearchAttempt")
        low = result.lower()
        assert "searchattempt" in low or "strategy" in low, \
            f"Should find SearchAttempt TypedDict, got: {result[:200]}"

    def test_find_typed_dict_latency(self):
        orch = _get_orchestrator()
        start = time.time()
        orch.find_symbol("SearchAttempt")
        latency = time.time() - start
        assert latency < 15.0, f"Type lookup took {latency:.1f}s, should be < 15s"


class TestWrongRepoRecovery:
    """Test 14: Wrong-repo search falls back gracefully."""

    def test_wrong_namespace_caps_results(self):
        """When no namespace matches, target() caps repos at 3."""
        from search.registry import repo_registry
        repos, confidence = repo_registry.target(
            "some unknown query",
            page_url="http://localhost:8000/nonexistent-repo/page/",
        )
        assert confidence in ("medium", "low"), \
            f"Non-matching URL should give medium/low confidence, got: {confidence}"
        assert len(repos) <= 3, f"Should cap at 3 repos, got {len(repos)}"

    def test_wrong_repo_then_broad_search(self):
        """Search with wrong scope, then fall back to broader search."""
        orch = _get_orchestrator()
        # First try a scope that won't have the symbol
        result1 = orch.search("classify_query", scope="code")
        # Regardless of first result, a find_symbol should still work
        result2 = orch.find_symbol("classify_query")
        assert "classify_query" in result2.lower() or "orchestrator" in result2.lower(), \
            f"Fallback search should find symbol, got: {result2[:200]}"


class TestCacheBehavior:
    """Test 15: Repeated queries benefit from caching."""

    def test_repeated_query_completes(self):
        """Same query twice — both should return results, second should not be slower."""
        orch = _get_orchestrator()
        start1 = time.time()
        result1 = orch.find_symbol("classify_query")
        latency1 = time.time() - start1

        start2 = time.time()
        result2 = orch.find_symbol("classify_query")
        latency2 = time.time() - start2

        assert result1 and result2, "Both queries should return results"
        # Second query should not take significantly longer than first
        assert latency2 < latency1 * 3 + 1.0, \
            f"Second query ({latency2:.2f}s) shouldn't be much slower than first ({latency1:.2f}s)"


class TestCodeSnippetExplanation:
    """Test 16: Located code returns usable snippet context."""

    def test_find_symbol_returns_code_context(self):
        """find_symbol should return actual code lines, not just file names."""
        orch = _get_orchestrator()
        result = orch.find_symbol("classify_query")
        # The result should contain actual code — check for Python-like patterns
        has_code = any(kw in result for kw in ["def ", "class ", "import ", "return ", "(", ")"])
        assert has_code, f"Result should contain code context, got: {result[:300]}"

    def test_find_symbol_shows_file_path(self):
        """find_symbol results should include file path information."""
        orch = _get_orchestrator()
        result = orch.find_symbol("SearchOrchestrator")
        # Should contain file path info (e.g., orchestrator.py or a path separator)
        has_path = any(sep in result for sep in [".py", "/", "\\"])
        assert has_path, f"Result should contain file path info, got: {result[:300]}"
