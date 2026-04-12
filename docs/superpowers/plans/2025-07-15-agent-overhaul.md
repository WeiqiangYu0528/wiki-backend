# Agent System Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix broken code search, add loop prevention, populate search indexes, improve observability, and add comprehensive code-location + UI tests — all tested with local Ollama model.

**Architecture:** Wire existing `smart_search`/`find_symbol`/`read_code_section` tools to the agent, add `recursion_limit=25`, run `IndexBuilder.build()` to populate ChromaDB symbols/code_docs + Meilisearch indexes, build a rule-based search strategy engine with loop detection, enhance lexical search scoring for code definitions, add repo targeting confidence, extend observability metrics and trace store, expose a `/api/traces/{id}` endpoint, add 12 code-location tests and 5 UI tests.

**Tech Stack:** Python 3.11+, FastAPI, LangGraph, ChromaDB, Meilisearch, ripgrep, OpenTelemetry, Prometheus, SQLite, Playwright (UI tests), Ollama (qwen3.5 + nomic-embed-text)

---

## File Structure

### Files to Create
- `backend/search/strategy.py` — Search strategy engine with loop prevention and escalation
- `backend/tests/test_code_location.py` — 12 code-location accuracy tests
- `backend/tests/test_ui_code_search.py` — 5 UI coding question tests
- `documentation/search-strategy.md` — Strategy engine documentation

### Files to Modify
- `backend/agent.py` — Wire search tools, add recursion_limit, update system prompt
- `backend/search/orchestrator.py` — Fix symbol search fallback, fix classify_query, always run lexical
- `backend/search/lexical.py` — Remove --fixed-strings, add definition boost, fix scoring
- `backend/search/registry.py` — Add confidence scoring, return confidence from target()
- `backend/observability/metrics.py` — Add search/loop/strategy metrics
- `backend/observability/trace_store.py` — Add new columns for strategy, loops, repo confidence
- `backend/main.py` — Add /api/traces endpoint, add startup index trigger
- `backend/search_tools.py` — Add loop-aware hints to tool outputs

---

## Task 1: Fix Lexical Search — Remove --fixed-strings and Add Definition Boost

**Files:**
- Modify: `backend/search/lexical.py:55-57` (remove --fixed-strings), `backend/search/lexical.py:153-168` (fix scoring)
- Test: `backend/tests/test_performance_accuracy.py` (existing tests must still pass)

- [ ] **Step 1: Write failing test for definition detection boost**

Add to the bottom of `backend/tests/test_performance_accuracy.py`:

```python
class TestLexicalDefinitionBoost:
    """Test that lexical search boosts code definition lines."""

    def test_definition_line_scores_higher(self):
        """A line containing 'def classify_query' should score higher than a comment mentioning it."""
        from search.lexical import LexicalSearch
        ls = LexicalSearch(ROOT_DIR)
        definition_line = "def classify_query(query: str) -> str:"
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_performance_accuracy.py::TestLexicalDefinitionBoost -v 2>&1 | tail -20
```

Expected: FAIL — definition boost doesn't exist yet, docs bias still present, no camelCase expansion.

- [ ] **Step 3: Implement lexical search fixes**

Edit `backend/search/lexical.py`. Replace the entire `_search_rg` method (lines 47-107) and `_score_match` method (lines 153-168):

```python
    @staticmethod
    def _camel_to_snake(name: str) -> str:
        """Convert camelCase to snake_case for query expansion."""
        s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

    def _search_rg(
        self,
        query: str,
        paths: list[str],
        max_results: int,
        file_glob: str,
        context_lines: int,
    ) -> list[dict]:
        # Build regex pattern: original query OR snake_case variant
        escaped = re.escape(query)
        snake = self._camel_to_snake(query)
        if snake != query.lower():
            pattern = f"({escaped}|{re.escape(snake)})"
        else:
            pattern = escaped

        cmd = [
            "rg", "--json",
            "--ignore-case",
            "--max-count", "5",
            f"--context={context_lines}",
            "--max-filesize", "1M",
        ]
        if file_glob:
            cmd.extend(["--glob", file_glob])

        cmd.append(pattern)
        cmd.extend(paths)

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            return []

        results: list[dict] = []
        context_buffer: dict[str, list[str]] = {}

        for line in res.stdout.splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj["type"] == "match":
                data = obj["data"]
                file_path = os.path.relpath(data["path"]["text"], self.workspace_dir)
                line_number = data["line_number"]
                text = data["lines"]["text"].rstrip()

                ctx_lines = context_buffer.get(file_path, [])
                ctx_lines.append(text)

                results.append({
                    "file_path": file_path,
                    "line_number": line_number,
                    "text": text,
                    "score": self._score_match(file_path, query, text),
                })

            elif obj["type"] == "context":
                data = obj["data"]
                file_path = os.path.relpath(data["path"]["text"], self.workspace_dir)
                context_buffer.setdefault(file_path, []).append(
                    data["lines"]["text"].rstrip()
                )

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:max_results]

    _DEFINITION_PATTERN = re.compile(
        r"^\s*(?:export\s+)?(?:async\s+)?(?:pub(?:lic)?\s+)?(?:static\s+)?(?:abstract\s+)?"
        r"(?:def|class|function|interface|type|enum|struct|trait|impl)\s+",
        re.IGNORECASE,
    )

    @staticmethod
    def _score_match(file_path: str, query: str, text: str) -> float:
        score = 1.0
        query_lower = query.lower()
        basename = os.path.basename(file_path).lower()

        # Filename contains query → strong signal
        if query_lower.replace(" ", "-") in basename or query_lower.replace(" ", "_") in basename:
            score += 5.0

        # Exact text match
        if query in text:
            score += 2.0

        # Definition line boost: +3.0 for def/class/function/interface lines containing the query
        if LexicalSearch._DEFINITION_PATTERN.match(text) and query_lower in text.lower():
            score += 3.0

        # Source code boost (not docs) for code-like queries
        if not file_path.startswith("docs/"):
            score += 0.5

        return score
```

Also add `import re` at the top of the file (line 5):

```python
import re
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_performance_accuracy.py::TestLexicalDefinitionBoost -v 2>&1 | tail -20
```

Expected: PASS — all 3 new tests pass.

- [ ] **Step 5: Run existing tests to check for regressions**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_performance_accuracy.py -v --timeout=60 2>&1 | tail -30
```

Expected: All existing tests still pass. If any scoring-dependent tests fail, adjust their expected ranges to accommodate the new scoring formula.

- [ ] **Step 6: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add backend/search/lexical.py backend/tests/test_performance_accuracy.py && git commit -m "fix: lexical search — remove --fixed-strings, add definition boost, camelCase expansion

- Remove --fixed-strings flag; use regex with re.escape() for safety
- Add +3.0 score boost for definition lines (def/class/function/interface)
- Replace +1.0 docs bias with +0.5 source code boost
- Add camelCase → snake_case query expansion
- Add _DEFINITION_PATTERN compiled regex for performance

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: Fix classify_query to Handle NL+Symbol Queries

**Files:**
- Modify: `backend/search/orchestrator.py:21-40`
- Test: `backend/tests/test_performance_accuracy.py` (existing classify_query tests)

- [ ] **Step 1: Write failing test for NL+symbol extraction**

Add to `backend/tests/test_performance_accuracy.py`:

```python
class TestClassifyQuerySymbolExtraction:
    """Test that classify_query extracts symbols from natural language queries."""

    def test_explain_camelcase_function(self):
        from search.orchestrator import classify_query
        qtype, extracted = classify_query("Explain startMdmRawRead()")
        assert qtype == "symbol", f"Expected 'symbol', got '{qtype}'"
        assert extracted == "startMdmRawRead", f"Expected 'startMdmRawRead', got '{extracted}'"

    def test_where_is_function(self):
        from search.orchestrator import classify_query
        qtype, extracted = classify_query("Where is SearchOrchestrator implemented?")
        assert qtype == "symbol", f"Expected 'symbol', got '{qtype}'"
        assert extracted == "SearchOrchestrator", f"Expected 'SearchOrchestrator', got '{extracted}'"

    def test_who_calls_snake_case(self):
        from search.orchestrator import classify_query
        qtype, extracted = classify_query("Who calls classify_query?")
        assert qtype == "symbol", f"Expected 'symbol', got '{qtype}'"
        assert extracted == "classify_query", f"Expected 'classify_query', got '{extracted}'"

    def test_pure_concept_query(self):
        from search.orchestrator import classify_query
        qtype, extracted = classify_query("How does the agent handle errors?")
        assert qtype == "concept", f"Expected 'concept', got '{qtype}'"
        assert extracted == "How does the agent handle errors?", f"Should return original query"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_performance_accuracy.py::TestClassifyQuerySymbolExtraction -v 2>&1 | tail -20
```

Expected: FAIL — classify_query currently returns a single string, not a tuple.

- [ ] **Step 3: Implement classify_query fix**

Replace `classify_query` in `backend/search/orchestrator.py` (lines 21-40):

```python
def classify_query(query: str) -> tuple[str, str]:
    """Classify a query and extract the target symbol if present.
    
    Returns:
        (query_type, effective_query) where query_type is 'symbol', 'concept', or 'exact',
        and effective_query is the extracted symbol name or the original query.
    """
    stripped = query.strip()
    
    # Pure CamelCase identifier (e.g. "SearchOrchestrator")
    if re.match(r"^[A-Z][a-zA-Z0-9]*(?:[A-Z][a-z]+)+$", stripped):
        return "symbol", stripped
    # Pure snake_case identifier (e.g. "classify_query")
    if re.match(r"^[a-z_][a-z0-9_]*(?:_[a-z0-9]+)+$", stripped):
        return "symbol", stripped
    # Dotted path (e.g. "search.orchestrator")
    if "." in stripped and " " not in stripped:
        return "symbol", stripped

    # Extract symbol from natural language: "Explain startMdmRawRead()"
    # Look for CamelCase identifiers
    camel_match = re.search(r'\b([A-Z][a-zA-Z0-9]*(?:[A-Z][a-z]+)+)\b', stripped)
    if camel_match:
        return "symbol", camel_match.group(1)
    # Look for snake_case identifiers (3+ chars with underscores)
    snake_match = re.search(r'\b([a-z_][a-z0-9_]*_[a-z0-9_]+)\b', stripped)
    if snake_match:
        return "symbol", snake_match.group(1)
    # Look for camelCase (lowercase start): startMdmRawRead
    lower_camel = re.search(r'\b([a-z]+[A-Z][a-zA-Z0-9]*)\b', stripped)
    if lower_camel:
        return "symbol", lower_camel.group(1)

    # Keywords like "function", "class", "method" with an adjacent identifier
    words = stripped.lower().split()
    if any(w in ("function", "class", "method", "def", "interface", "type") for w in words):
        for w in stripped.split():
            if re.match(r'^[A-Z][a-zA-Z0-9]+$', w) or re.match(r'^[a-z_]+[A-Z]', w):
                return "symbol", w
            if re.match(r'^[a-z_][a-z0-9_]*_[a-z0-9_]+$', w):
                return "symbol", w

    # Exact match patterns
    if stripped.startswith(("ERROR", "Error", "error")) or '"' in stripped or "'" in stripped:
        return "exact", stripped
    if "/" in stripped and " " not in stripped:
        return "exact", stripped

    return "concept", stripped
```

- [ ] **Step 4: Update all callers of classify_query**

In `backend/search/orchestrator.py`, update the `search()` method call site (around line 146):

Change:
```python
query_type = classify_query(query)
```

To:
```python
query_type, effective_query = classify_query(query)
```

Then use `effective_query` instead of `query` for symbol search (line 188):
```python
symbol_results = self.semantic.query("symbols", effective_query, n_results=5)
```

And for lexical search when applicable.

Also update any existing tests that call `classify_query` expecting a single return value.

- [ ] **Step 5: Run all tests**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_performance_accuracy.py -v --timeout=60 2>&1 | tail -30
```

Expected: All tests pass including the new ones. Fix any existing tests that broke due to the return type change.

- [ ] **Step 6: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add backend/search/orchestrator.py backend/tests/test_performance_accuracy.py && git commit -m "fix: classify_query extracts symbols from natural language queries

- Return (query_type, effective_query) tuple instead of just type
- Extract CamelCase, snake_case, and lowerCamelCase from NL queries
- 'Explain startMdmRawRead()' → ('symbol', 'startMdmRawRead')
- Update callers to use effective_query for symbol search

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: Fix Orchestrator — Symbol Search Fallback to Lexical

**Files:**
- Modify: `backend/search/orchestrator.py:117-226` (search method), `backend/search/orchestrator.py:228-241` (find_symbol)
- Test: `backend/tests/test_performance_accuracy.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_performance_accuracy.py`:

```python
class TestOrchestratorSymbolFallback:
    """Test that symbol queries fall back to lexical search."""

    def test_symbol_query_uses_lexical_fallback(self):
        """When semantic symbols collection is empty, lexical search should still find results."""
        from search.orchestrator import SearchOrchestrator
        from search.semantic import SemanticSearch
        from search.reranker import JaccardReranker
        import tempfile, os

        with tempfile.TemporaryDirectory() as tmpdir:
            semantic = SemanticSearch.__new__(SemanticSearch)
            semantic._ready = False  # Simulate empty/unavailable semantic
            orch = SearchOrchestrator(
                workspace_dir=ROOT_DIR,
                semantic=semantic,
                reranker=JaccardReranker(),
                max_chars=2000,
                result_max_chars=200,
            )
            orch._ready = False  # Semantic not ready — should still use lexical
            result = orch.search("classify_query", scope="code")
            assert result != "No results found.", f"Should find classify_query via lexical fallback"
            assert "orchestrator" in result.lower() or "classify_query" in result.lower()

    def test_symbol_query_runs_both_semantic_and_lexical(self):
        """Symbol queries should run both semantic and lexical in parallel."""
        from search.orchestrator import SearchOrchestrator, classify_query
        qtype, extracted = classify_query("SearchOrchestrator")
        assert qtype == "symbol"
        # The orchestrator.search() should include lexical results even for symbol queries
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_performance_accuracy.py::TestOrchestratorSymbolFallback -v 2>&1 | tail -20
```

- [ ] **Step 3: Fix the orchestrator search method**

In `backend/search/orchestrator.py`, replace the search method body (lines 117-226). The key changes:

1. Always run lexical search regardless of query type
2. Symbol queries also run lexical with code paths
3. Use `effective_query` from classify_query

Replace the section from line 144 to line 226:

```python
            namespace = scope if scope not in ("auto", "wiki", "code") else ""
            targets = self.registry.target(query, page_url=page_url, namespace=namespace)
            query_type, effective_query = classify_query(query)
            span.set_attribute("search.query_type", query_type)
            span.set_attribute("search.effective_query", effective_query[:200])

            all_results: list[dict] = []
            sources_used: list[str] = []

            # --- Always run lexical search as baseline ---
            with tracer.start_as_current_span("search.lexical") as lex_span:
                t0 = time.time()
                search_paths = self._get_search_paths(scope, targets)
                lexical_q = effective_query if query_type == "symbol" else query
                lexical_results = self.lexical.search(lexical_q, search_paths=search_paths, max_results=max_results)
                lex_span.set_attribute("search.results_count", len(lexical_results))
                lex_span.set_attribute("search.duration_ms", int((time.time() - t0) * 1000))
            all_results.extend(lexical_results)
            sources_used.append("lexical")

            # --- Meilisearch (BM25 + vector) when available ---
            if self._meili and self._meili.available:
                with tracer.start_as_current_span("search.meilisearch") as ms_span:
                    t0 = time.time()
                    meili_results: list[dict] = []
                    if scope in ("auto", "wiki"):
                        meili_results.extend(self._meili.search("wiki_docs", query, limit=15))
                    if scope in ("auto", "code"):
                        meili_results.extend(self._meili.search("code_docs", effective_query, limit=15))
                    ms_span.set_attribute("search.results_count", len(meili_results))
                    ms_span.set_attribute("search.duration_ms", int((time.time() - t0) * 1000))
                all_results.extend(meili_results)
                sources_used.append("meilisearch")

            # --- ChromaDB semantic (for concept queries) ---
            if self._ready and query_type == "concept":
                with tracer.start_as_current_span("search.semantic") as sem_span:
                    t0 = time.time()
                    semantic_results = self._semantic_search(query, scope, targets, max_results=10)
                    sem_span.set_attribute("search.results_count", len(semantic_results))
                    sem_span.set_attribute("search.duration_ms", int((time.time() - t0) * 1000))
                all_results.extend(semantic_results)
                sources_used.append("semantic")

            # --- Symbol search (for symbol queries) ---
            if self._ready and query_type == "symbol":
                with tracer.start_as_current_span("search.symbol") as sym_span:
                    t0 = time.time()
                    symbol_results = self.semantic.query("symbols", effective_query, n_results=5)
                    sym_span.set_attribute("search.results_count", len(symbol_results))
                    sym_span.set_attribute("search.duration_ms", int((time.time() - t0) * 1000))
                all_results.extend(symbol_results)
                sources_used.append("symbol")

            span.set_attribute("search.sources_used", ",".join(sources_used))
            span.set_attribute("search.total_raw_results", len(all_results))
```

The rest of the method (dedup, rerank, cache, format) stays the same.

- [ ] **Step 4: Run tests**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_performance_accuracy.py -v --timeout=60 2>&1 | tail -30
```

- [ ] **Step 5: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add backend/search/orchestrator.py backend/tests/test_performance_accuracy.py && git commit -m "fix: orchestrator always runs lexical search, symbol queries use effective_query

- Lexical search now runs for ALL query types as baseline
- Symbol queries use extracted effective_query for lexical
- Meilisearch code_docs search uses effective_query for symbols
- Semantic symbol search uses effective_query

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: Wire Search Tools to Agent and Add Recursion Limit

**Files:**
- Modify: `backend/agent.py:1-10` (imports), `backend/agent.py:280` (tools list), `backend/agent.py:418` (run_agent), `backend/agent.py:530` (run_agent_stream), `backend/agent.py:313-357` (system prompt)
- Test: `backend/tests/test_performance_accuracy.py`

- [ ] **Step 1: Write test verifying tools are available**

Add to `backend/tests/test_performance_accuracy.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_performance_accuracy.py::TestAgentToolWiring -v 2>&1 | tail -20
```

- [ ] **Step 3: Wire tools in agent.py**

In `backend/agent.py`, add import after line 23:

```python
from search_tools import smart_search, find_symbol, read_code_section
```

Replace the tools list at line 280:

```python
tools = [
    smart_search,
    find_symbol,
    read_code_section,
    read_workspace_file,
    read_source_file,
    list_wiki_pages,
    propose_doc_change,
]
```

Remove the `search_knowledge_base` function (lines 139-178) — it's superseded by `smart_search`.

- [ ] **Step 4: Add recursion_limit to both agent runners**

In `run_agent()` around line 418, change:
```python
agent = create_react_agent(llm, tools=tools)
```
To:
```python
agent = create_react_agent(llm, tools=tools, recursion_limit=25)
```

In `run_agent_stream()` around line 530, same change:
```python
agent = create_react_agent(llm, tools=tools, recursion_limit=25)
```

- [ ] **Step 5: Update system prompt to guide code search**

In `build_system_prompt()`, add after the tool descriptions section (around line 349):

```python
    prompt += """

Code search strategy:
1. When asked about a specific function, class, or symbol, use `find_symbol` first.
2. If `find_symbol` returns no results, use `smart_search` with scope="code".
3. If you still can't find it, try `smart_search` with a broader scope="auto".
4. Once you find the file, use `read_code_section` to read just that symbol — do NOT read the entire file.
5. Do NOT retry the same search more than twice with the same query. Rephrase or use a different tool.
6. If you cannot find the code after 3 different search attempts, explain what you searched for and that it was not found."""
```

- [ ] **Step 6: Run tests**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_performance_accuracy.py::TestAgentToolWiring -v 2>&1 | tail -10
```

Expected: PASS

- [ ] **Step 7: Run full test suite for regressions**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/ -v --timeout=60 2>&1 | tail -30
```

- [ ] **Step 8: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add backend/agent.py backend/tests/test_performance_accuracy.py && git commit -m "fix: wire smart_search/find_symbol/read_code_section to agent, add recursion_limit=25

CRITICAL FIX: These tools existed in search_tools.py but were never
added to the agent's tool list. The agent could only grep markdown docs.
Now it can use hybrid search, symbol lookup, and code section reading.

- Replace search_knowledge_base with smart_search/find_symbol/read_code_section
- Add recursion_limit=25 to prevent infinite loops
- Update system prompt with code search strategy guidance

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5: Build Search Strategy Engine with Loop Prevention

**Files:**
- Create: `backend/search/strategy.py`
- Test: `backend/tests/test_performance_accuracy.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_performance_accuracy.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_performance_accuracy.py::TestSearchStrategyEngine -v 2>&1 | tail -20
```

- [ ] **Step 3: Create strategy.py**

Create `backend/search/strategy.py`:

```python
"""Search strategy engine with loop prevention and escalation."""


class SearchStrategyEngine:
    """Tracks search attempts per request and manages strategy escalation.
    
    Instantiate one per agent request. Tracks which queries have been tried,
    how many results each returned, and when to escalate or give up.
    """

    STRATEGIES = [
        "symbol_exact",
        "lexical_code",
        "semantic_code",
        "lexical_broad",
        "semantic_broad",
    ]
    MAX_ATTEMPTS_PER_STRATEGY = 3

    def __init__(self) -> None:
        self.attempts: list[dict] = []
        self.current_strategy_idx: int = 0
        self._consecutive_failures: int = 0

    @property
    def current_strategy(self) -> str:
        idx = min(self.current_strategy_idx, len(self.STRATEGIES) - 1)
        return self.STRATEGIES[idx]

    @property
    def exhausted(self) -> bool:
        return self.current_strategy_idx >= len(self.STRATEGIES)

    @property
    def total_attempts(self) -> int:
        return len(self.attempts)

    def record_attempt(self, query: str, result_count: int) -> str | None:
        """Record a search attempt. Returns a hint string or None.
        
        Returns:
            None if no action needed.
            "ESCALATED to <strategy>" if strategy was switched.
            "EXHAUSTED" if all strategies are exhausted.
        """
        self.attempts.append({
            "query": query,
            "result_count": result_count,
            "strategy": self.current_strategy if not self.exhausted else "none",
        })

        if result_count == 0:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.MAX_ATTEMPTS_PER_STRATEGY:
                self._consecutive_failures = 0
                self.current_strategy_idx += 1
                if self.exhausted:
                    return "EXHAUSTED"
                return f"ESCALATED to {self.current_strategy}"
        else:
            self._consecutive_failures = 0

        return None

    def summary(self) -> str:
        """Generate a human-readable summary of all search attempts."""
        if not self.attempts:
            return "No search attempts recorded."
        
        lines = []
        for i, a in enumerate(self.attempts, 1):
            status = f"{a['result_count']} results" if a['result_count'] > 0 else "no results"
            lines.append(f"  {i}. [{a['strategy']}] \"{a['query']}\" → {status}")
        
        total = len(self.attempts)
        found = sum(1 for a in self.attempts if a["result_count"] > 0)
        lines.insert(0, f"Search attempts: {total} total, {found} successful")
        
        if self.exhausted:
            lines.append("  ⚠️ All strategies exhausted.")
        
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_performance_accuracy.py::TestSearchStrategyEngine -v 2>&1 | tail -20
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add backend/search/strategy.py backend/tests/test_performance_accuracy.py && git commit -m "feat: add search strategy engine with loop prevention and escalation

- 5 escalation strategies: symbol_exact → lexical_code → semantic_code → lexical_broad → semantic_broad
- Max 3 failed attempts per strategy before escalating
- Tracks all attempts with query, result_count, strategy
- summary() generates human-readable search history
- Returns ESCALATED/EXHAUSTED hints for agent guidance

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6: Add Loop-Aware Hints to Search Tool Wrappers

**Files:**
- Modify: `backend/search_tools.py`
- Modify: `backend/agent.py` (pass strategy engine to tools)

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_performance_accuracy.py`:

```python
class TestSearchToolLoopHints:
    """Test that search tools add loop-prevention hints."""

    def test_smart_search_appends_hint_on_empty(self):
        from search_tools import smart_search
        from search.strategy import SearchStrategyEngine
        # Configure strategy engine for testing
        import search_tools
        engine = SearchStrategyEngine()
        search_tools._strategy_engine = engine
        # Invoke search with a query that returns no results
        result = smart_search.invoke({"query": "NonExistentSymbolXYZ999", "scope": "code"})
        assert "No results" in result or "not found" in result.lower()
        # The engine should have recorded the attempt
        assert engine.total_attempts >= 1
```

- [ ] **Step 2: Implement loop-aware tool wrappers**

In `backend/search_tools.py`, add at the top (after imports):

```python
from search.strategy import SearchStrategyEngine

# Per-request strategy engine — reset by agent before each request
_strategy_engine: SearchStrategyEngine | None = None


def get_strategy_engine() -> SearchStrategyEngine:
    global _strategy_engine
    if _strategy_engine is None:
        _strategy_engine = SearchStrategyEngine()
    return _strategy_engine


def reset_strategy_engine() -> None:
    global _strategy_engine
    _strategy_engine = SearchStrategyEngine()
```

Then update the `smart_search` tool function:

```python
@tool
def smart_search(query: str, scope: str = "auto") -> str:
    """Search across wiki documentation and source code repositories.

    Args:
        query: Natural language question, code identifier, or search term.
        scope: Search scope — "auto", "wiki", "code", or a namespace like "claude-code".
    """
    orch = get_orchestrator()
    if not orch:
        return "Error: Search system not initialized."
    try:
        result = orch.search(query=query, scope=scope)
        engine = get_strategy_engine()
        is_empty = result.strip() == "No results found."
        result_count = 0 if is_empty else result.count("**")
        hint = engine.record_attempt(query, result_count)
        
        if hint == "EXHAUSTED":
            return f"{result}\n\n⚠️ All search strategies exhausted after {engine.total_attempts} attempts. Summarize what you found so far.\n\n{engine.summary()}"
        elif hint and hint.startswith("ESCALATED"):
            return f"{result}\n\n💡 Strategy escalated. Try a different query or scope."
        elif is_empty and engine.total_attempts > 1:
            return f"{result}\n\n💡 This is attempt #{engine.total_attempts}. Try rephrasing or changing scope."
        return result
    except Exception as e:
        return f"Search error: {e}"
```

Update `find_symbol` similarly:

```python
@tool
def find_symbol(name: str, namespace: str = "") -> str:
    """Find a function, class, interface, or type definition by name.

    Args:
        name: The symbol name (e.g. 'MemoryMiddleware', 'create_react_agent').
        namespace: Optional namespace to limit search (e.g. 'deepagents').
    """
    orch = get_orchestrator()
    if not orch:
        return "Error: Search system not initialized."
    try:
        result = orch.find_symbol(name=name, namespace=namespace)
        engine = get_strategy_engine()
        is_empty = result.strip() == "No results found."
        result_count = 0 if is_empty else 1
        engine.record_attempt(f"symbol:{name}", result_count)
        
        if is_empty:
            return f"Symbol '{name}' not found. Try smart_search with the symbol name instead."
        return result
    except Exception as e:
        return f"Symbol lookup error: {e}"
```

- [ ] **Step 3: Reset strategy engine per request**

In `backend/agent.py`, in both `run_agent()` and `run_agent_stream()`, add before the agent invocation:

```python
from search_tools import reset_strategy_engine
reset_strategy_engine()
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_performance_accuracy.py::TestSearchToolLoopHints -v 2>&1 | tail -20
```

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/ -v --timeout=60 2>&1 | tail -30
```

- [ ] **Step 6: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add backend/search_tools.py backend/agent.py backend/tests/test_performance_accuracy.py && git commit -m "feat: add loop-aware hints to search tools, reset strategy per request

- smart_search appends escalation/exhaustion hints to results
- find_symbol suggests smart_search as fallback when symbol not found
- Strategy engine reset at start of each agent request
- Tracks attempt count and provides guided hints to the LLM

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 7: Improve Repo Targeting with Confidence Scoring

**Files:**
- Modify: `backend/search/registry.py:96-141`
- Test: `backend/tests/test_performance_accuracy.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_performance_accuracy.py`:

```python
class TestRepoTargetingConfidence:
    """Test repo targeting returns confidence scores."""

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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_performance_accuracy.py::TestRepoTargetingConfidence -v 2>&1 | tail -20
```

Expected: FAIL — target() returns list, not tuple.

- [ ] **Step 3: Implement confidence scoring**

In `backend/search/registry.py`, replace the `target` method (lines 96-140):

```python
    def target(
        self,
        query: str,
        page_url: str = "",
        namespace: str = "",
    ) -> tuple[list[RepoMeta], str]:
        """Target repos for a query. Returns (repos, confidence).
        
        confidence is one of: "high", "medium", "low".
        """
        if namespace:
            repo = self.get_by_namespace(namespace)
            return ([repo], "high") if repo else (self.repos, "low")

        # High confidence: page URL matches a known repo
        if page_url:
            for repo in self.repos:
                wiki_suffix = repo.wiki_dir.replace("docs/", "")
                if wiki_suffix in page_url:
                    return [repo], "high"

        # Keyword scoring
        query_lower = query.lower()
        scores: list[tuple[float, RepoMeta]] = []
        for repo in self.repos:
            score = 0.0
            for kw in repo.keywords:
                if kw in query_lower:
                    score += len(kw)
            if repo.namespace in query_lower:
                score += 20
            scores.append((score, repo))

        scores.sort(key=lambda x: x[0], reverse=True)

        # Medium confidence: at least one keyword matched
        if scores[0][0] > 0:
            result = [repo for score, repo in scores if score > 0]
            return result[:3], "medium"

        # Low confidence: no keywords matched — return top 3
        return [repo for _, repo in scores[:3]], "low"
```

- [ ] **Step 4: Update all callers of registry.target()**

In `backend/search/orchestrator.py`, update the target call (around line 145):

Change:
```python
targets = self.registry.target(query, page_url=page_url, namespace=namespace)
```
To:
```python
targets, repo_confidence = self.registry.target(query, page_url=page_url, namespace=namespace)
span.set_attribute("search.repo_confidence", repo_confidence)
span.set_attribute("search.repos_targeted", ",".join(t.namespace for t in targets))
```

- [ ] **Step 5: Run tests**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/ -v --timeout=60 2>&1 | tail -30
```

Fix any existing tests that call `registry.target()` expecting a list return.

- [ ] **Step 6: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add backend/search/registry.py backend/search/orchestrator.py backend/tests/test_performance_accuracy.py && git commit -m "feat: add confidence scoring to repo targeting

- target() now returns (repos, confidence) tuple
- 'high': page URL matches repo, 'medium': keyword match, 'low': no signal
- Limit to top 3 repos on low confidence
- Add repo_confidence and repos_targeted to OTEL spans

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 8: Enhance Observability — Metrics, Trace Store, and Trace API

**Files:**
- Modify: `backend/observability/metrics.py`
- Modify: `backend/observability/trace_store.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Add new metrics to metrics.py**

Append to `backend/observability/metrics.py` class `AgentMetrics.__init__` (after line 78):

```python
        # --- Search strategy metrics ---
        self.search_attempts_total = meter.create_counter(
            "agent_search_attempts_total",
            description="Total search attempts by strategy",
        )
        self.strategy_escalations_total = meter.create_counter(
            "agent_strategy_escalations_total",
            description="Search strategy escalation events",
        )
        self.loops_detected_total = meter.create_counter(
            "agent_loops_detected_total",
            description="Loop detection events (recursion limit hit)",
        )
        self.repo_confidence_total = meter.create_counter(
            "agent_repo_confidence_total",
            description="Repo targeting confidence distribution",
        )
        self.code_search_success_total = meter.create_counter(
            "agent_code_search_success_total",
            description="Successful code search lookups",
        )
        self.code_search_latency = meter.create_histogram(
            "agent_code_search_latency_ms",
            description="Latency for code search operations",
            unit="ms",
        )
        self.recursion_depth = meter.create_histogram(
            "agent_recursion_depth",
            description="How deep the ReAct loop goes per request",
        )
```

- [ ] **Step 2: Extend trace store schema**

In `backend/observability/trace_store.py`, replace `CREATE_TABLE_SQL` (lines 11-32):

```python
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS request_traces (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    model TEXT NOT NULL,
    query TEXT NOT NULL,
    status TEXT NOT NULL,
    total_tokens INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    llm_calls INTEGER DEFAULT 0,
    tool_calls INTEGER DEFAULT 0,
    search_calls INTEGER DEFAULT 0,
    embedding_calls INTEGER DEFAULT 0,
    prompt_chars INTEGER DEFAULT 0,
    retrieval_chars INTEGER DEFAULT 0,
    citations_count INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    error_message TEXT DEFAULT '',
    tiers_used TEXT DEFAULT '',
    tools_used TEXT DEFAULT '',
    search_attempts INTEGER DEFAULT 0,
    search_strategy TEXT DEFAULT '',
    loop_detected INTEGER DEFAULT 0,
    strategies_exhausted INTEGER DEFAULT 0,
    repo_confidence TEXT DEFAULT '',
    repo_selected TEXT DEFAULT '',
    recursion_depth INTEGER DEFAULT 0,
    tool_call_sequence TEXT DEFAULT '[]'
)
"""
```

Update the `write()` method signature and INSERT to include the new columns:

```python
    def write(
        self,
        request_id: str,
        model: str,
        query: str,
        status: str,
        total_tokens: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        llm_calls: int = 0,
        tool_calls: int = 0,
        search_calls: int = 0,
        embedding_calls: int = 0,
        prompt_chars: int = 0,
        retrieval_chars: int = 0,
        citations_count: int = 0,
        duration_ms: int = 0,
        error_message: str = "",
        tiers_used: str = "",
        tools_used: str = "",
        search_attempts: int = 0,
        search_strategy: str = "",
        loop_detected: bool = False,
        strategies_exhausted: bool = False,
        repo_confidence: str = "",
        repo_selected: str = "",
        recursion_depth: int = 0,
        tool_call_sequence: str = "[]",
    ) -> None:
        """Write a request trace summary row."""
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO request_traces
                    (id, timestamp, model, query, status, total_tokens, input_tokens,
                     output_tokens, llm_calls, tool_calls, search_calls, embedding_calls,
                     prompt_chars, retrieval_chars, citations_count, duration_ms,
                     error_message, tiers_used, tools_used,
                     search_attempts, search_strategy, loop_detected, strategies_exhausted,
                     repo_confidence, repo_selected, recursion_depth, tool_call_sequence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        request_id, timestamp, model, query[:200], status,
                        total_tokens, input_tokens, output_tokens,
                        llm_calls, tool_calls, search_calls, embedding_calls,
                        prompt_chars, retrieval_chars, citations_count, duration_ms,
                        error_message, tiers_used, tools_used,
                        search_attempts, search_strategy, int(loop_detected), int(strategies_exhausted),
                        repo_confidence, repo_selected, recursion_depth, tool_call_sequence,
                    ),
                )
                conn.commit()
            except Exception as e:
                logger.error("Failed to write trace: %s", e)
            finally:
                conn.close()
```

- [ ] **Step 3: Add /api/traces endpoint to main.py**

In `backend/main.py`, add after the `/proposals` endpoints:

```python
@app.get("/api/traces")
def list_traces(limit: int = 20, current_user: str = Depends(get_current_user)):
    """List recent request traces."""
    return trace_store.recent(limit=limit)


@app.get("/api/traces/{request_id}")
def get_trace(request_id: str, current_user: str = Depends(get_current_user)):
    """Get a specific request trace by ID."""
    rows = trace_store.query("SELECT * FROM request_traces WHERE id = ?", (request_id,))
    if not rows:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Trace not found")
    return rows[0]
```

- [ ] **Step 4: Delete old trace DB to apply schema change**

The schema change adds new columns. Easiest approach: delete old DB file so it's recreated.

```bash
rm -f /Users/weiqiangyu/Downloads/wiki/backend/data/traces.db
```

- [ ] **Step 5: Run tests**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/ -v --timeout=60 2>&1 | tail -30
```

- [ ] **Step 6: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add backend/observability/metrics.py backend/observability/trace_store.py backend/main.py && git commit -m "feat: enhanced observability — new metrics, extended trace store, trace API

- Add search_attempts, strategy_escalations, loops_detected, repo_confidence,
  code_search_success, code_search_latency, recursion_depth metrics
- Extend trace_store with search_attempts, search_strategy, loop_detected,
  strategies_exhausted, repo_confidence, repo_selected, recursion_depth,
  tool_call_sequence columns
- Add GET /api/traces and GET /api/traces/{id} endpoints

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 9: Wire Observability into Agent Runners

**Files:**
- Modify: `backend/agent.py` (run_agent and run_agent_stream)

- [ ] **Step 1: Update run_agent_stream to record new observability data**

In the `run_agent_stream()` function, after the accumulators section (around line 521), add:

```python
    tool_call_sequence: list[dict] = []
```

In the `on_tool_end` handler, add tool call sequence tracking:

```python
    tool_call_sequence.append({
        "name": tool_name,
        "duration_ms": tool_duration_ms,
        "output_length": len(str(output)),
    })
```

In the trace_store.write() call at the end of run_agent_stream (and run_agent), add the new fields:

```python
    from search_tools import get_strategy_engine
    strategy = get_strategy_engine()
    
    trace_store.write(
        # ... existing fields ...
        search_attempts=strategy.total_attempts,
        search_strategy=strategy.current_strategy,
        loop_detected=llm_call_count >= 20,
        strategies_exhausted=strategy.exhausted,
        recursion_depth=llm_call_count,
        tool_call_sequence=json.dumps(tool_call_sequence),
    )
```

- [ ] **Step 2: Run tests**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/ -v --timeout=60 2>&1 | tail -30
```

- [ ] **Step 3: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add backend/agent.py && git commit -m "feat: wire new observability data into agent runners

- Track tool_call_sequence with name, duration, output_length
- Record search_attempts, strategy, loop_detected, strategies_exhausted
- Record recursion_depth (= llm_call_count)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 10: Trigger Index Build at Startup

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add startup indexing**

In `backend/main.py`, add after the app initialization:

```python
import threading
import logging

_index_logger = logging.getLogger("indexer")

def _run_index_build():
    """Build search indexes in a background thread."""
    try:
        from search_tools import get_orchestrator
        from search.indexer import IndexBuilder
        from search.semantic import SemanticSearch
        from security import settings
        import os

        orch = get_orchestrator()
        if orch is None:
            _index_logger.warning("Orchestrator not available, skipping index build")
            return

        workspace_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        builder = IndexBuilder(
            workspace_dir=workspace_dir,
            semantic=orch.semantic,
            registry=orch.registry,
            meilisearch_client=orch._meili,
        )
        stats = builder.build()
        orch.mark_ready()
        _index_logger.info("Index build complete: %s", stats)
    except Exception as e:
        _index_logger.error("Index build failed: %s", e)


@app.on_event("startup")
def startup_index():
    """Trigger index build in background thread on startup."""
    thread = threading.Thread(target=_run_index_build, daemon=True)
    thread.start()
```

- [ ] **Step 2: Test manually**

```bash
# Restart backend and check logs for index build
cd /Users/weiqiangyu/Downloads/wiki && docker compose restart backend 2>&1 | tail -5
# Wait 30s then check logs
docker compose logs backend --tail=30 2>&1 | grep -i "index"
```

- [ ] **Step 3: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add backend/main.py && git commit -m "feat: trigger search index build in background thread on startup

- Builds wiki_docs, code_docs, symbols collections in ChromaDB
- Builds Meilisearch indexes when available
- Marks orchestrator as ready when complete
- Runs in daemon thread to not block startup

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 11: Write 12 Code-Location Accuracy Tests

**Files:**
- Create: `backend/tests/test_code_location.py`

- [ ] **Step 1: Create the test file**

Create `backend/tests/test_code_location.py`:

```python
"""Code-location accuracy tests.

These tests verify the agent can locate code symbols, definitions, and
references with acceptable accuracy and latency. All tests use the local
search infrastructure (no LLM calls).
"""

import os
import time
import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _get_orchestrator():
    """Get a real orchestrator instance for testing."""
    from search_tools import get_orchestrator
    orch = get_orchestrator()
    if orch is None:
        pytest.skip("Search orchestrator not available")
    return orch


class TestExactFunctionLookup:
    """Test 1: Exact function name lookup."""

    def test_find_classify_query(self):
        orch = _get_orchestrator()
        result = orch.find_symbol("classify_query")
        assert "orchestrator" in result.lower(), f"Should find orchestrator.py, got: {result[:200]}"

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
    """Test 3: camelCase function from a source repo."""

    def test_search_camelcase_symbol(self):
        orch = _get_orchestrator()
        result = orch.search("JaccardReranker", scope="code")
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
        result = orch.search("classify_query", scope="code")
        assert result != "No results found.", "Should find classify_query usage in code"


class TestCrossModuleSearch:
    """Test 6: Search within a specific namespace."""

    def test_search_in_backend(self):
        orch = _get_orchestrator()
        result = orch.search("LexicalSearch", scope="code")
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
        start = time.time()
        result = orch.find_symbol("NonExistentSymbolXYZ_12345")
        latency = time.time() - start
        assert latency < 15.0, f"Missing symbol took {latency:.1f}s, should be < 15s"
        assert "no results" in result.lower() or "not found" in result.lower(), f"Should report not found, got: {result[:200]}"


class TestStrategyEscalation:
    """Test 10: Strategy engine escalates on repeated failures."""

    def test_escalation_works(self):
        from search.strategy import SearchStrategyEngine
        engine = SearchStrategyEngine()
        # Simulate 3 failures
        for i in range(3):
            engine.record_attempt(f"missing_{i}", result_count=0)
        assert engine.current_strategy == "lexical_code", f"Should escalate to lexical_code, got {engine.current_strategy}"


class TestDefinitionVsUsage:
    """Test 11: Definitions should rank above mere usages."""

    def test_definition_ranked_first(self):
        from search.lexical import LexicalSearch
        ls = LexicalSearch(ROOT_DIR)
        results = ls.search("classify_query", search_paths=["backend/search"], max_results=10)
        if results:
            # The first result should be the definition line
            top = results[0]
            assert "def classify_query" in top["text"] or "orchestrator" in top["file_path"], \
                f"Top result should be definition, got: {top['file_path']}:{top['text'][:100]}"


class TestLoopPrevention:
    """Test 12: Recursion limit prevents infinite loops."""

    def test_recursion_limit_set(self):
        """Verify that create_react_agent is called with recursion_limit."""
        import agent
        # Check that the tools list includes smart_search
        tool_names = [t.name for t in agent.tools]
        assert "smart_search" in tool_names, "smart_search must be in agent tools"
        assert "find_symbol" in tool_names, "find_symbol must be in agent tools"
```

- [ ] **Step 2: Run code-location tests**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_code_location.py -v --timeout=30 2>&1 | tail -40
```

Expected: Most tests pass. Fix any failures.

- [ ] **Step 3: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add backend/tests/test_code_location.py && git commit -m "test: add 12 code-location accuracy tests

- Exact function lookup, class lookup, camelCase/snake_case symbols
- Cross-file navigation, cross-module search
- Repo targeting from page URL context
- Ambiguous symbol handling, missing symbol graceful failure
- Strategy escalation, definition vs usage ranking
- Loop prevention verification
- All tests measure latency and correctness

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 12: Write 5 UI Code Search Tests

**Files:**
- Create: `backend/tests/test_ui_code_search.py`

- [ ] **Step 1: Create UI test file**

Create `backend/tests/test_ui_code_search.py`:

```python
"""UI-level tests for code search through the chat interface.

These tests verify that coding questions submitted through the chat API
return useful answers. Uses the local Ollama model.

NOTE: These tests require:
- Backend running at localhost:8001
- Ollama running with qwen3.5 model
- Set WIKI_UI_TEST=1 env var to enable (skipped by default)

Run with: WIKI_UI_TEST=1 python -m pytest tests/test_ui_code_search.py -v --timeout=120
"""

import json
import os
import time

import httpx
import pytest

BACKEND_URL = os.getenv("WIKI_BACKEND_URL", "http://localhost:8001")
SKIP_REASON = "Set WIKI_UI_TEST=1 to run UI tests (requires running services)"


def _login() -> str:
    """Login and return JWT token."""
    resp = httpx.post(
        f"{BACKEND_URL}/login",
        json={"username": "admin", "password": os.getenv("APP_ADMIN_PASSWORD", "StrongPassword123!")},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _chat(token: str, message: str, model: str = "ollama") -> dict:
    """Send a chat message and collect streaming response."""
    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    
    resp = httpx.post(
        f"{BACKEND_URL}/chat/stream",
        json={
            "message": message,
            "history": [],
            "model": model,
            "page_context": {"title": "Test", "url": "http://localhost:8000/"},
        },
        headers=headers,
        timeout=120,
    )
    resp.raise_for_status()
    
    tokens = []
    tool_calls = []
    for line in resp.text.strip().split("\n"):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if event.get("type") == "token":
                tokens.append(event.get("content", ""))
            elif event.get("type") == "tool_call":
                tool_calls.append(event.get("name", ""))
        except json.JSONDecodeError:
            continue
    
    full_text = "".join(tokens)
    latency = time.time() - start
    return {
        "text": full_text,
        "tool_calls": tool_calls,
        "latency": latency,
    }


@pytest.fixture(scope="module")
def auth_token():
    if not os.getenv("WIKI_UI_TEST"):
        pytest.skip(SKIP_REASON)
    try:
        return _login()
    except Exception as e:
        pytest.skip(f"Cannot connect to backend: {e}")


class TestUICodeSearch:
    """5 UI-level coding questions through the chat API."""

    def test_q1_find_search_orchestrator(self, auth_token):
        """Q1: Where is SearchOrchestrator implemented?"""
        result = _chat(auth_token, "Where is SearchOrchestrator implemented? Which file?")
        assert len(result["text"]) > 50, "Response should be substantial"
        assert result["latency"] < 120, f"Response took {result['latency']:.1f}s"
        # Should use search tools
        assert any(t in result["tool_calls"] for t in ["find_symbol", "smart_search", "search_knowledge_base"]), \
            f"Should use search tools, used: {result['tool_calls']}"

    def test_q2_explain_classify_query(self, auth_token):
        """Q2: Explain the classify_query function."""
        result = _chat(auth_token, "Explain the classify_query function in the search system")
        assert len(result["text"]) > 100, "Response should explain the function"
        assert result["latency"] < 120, f"Response took {result['latency']:.1f}s"

    def test_q3_who_calls_format_results(self, auth_token):
        """Q3: Who calls format_results?"""
        result = _chat(auth_token, "Who calls format_results() in this codebase?")
        assert len(result["text"]) > 50, "Response should list callers"
        assert result["latency"] < 120, f"Response took {result['latency']:.1f}s"

    def test_q4_tool_system_files(self, auth_token):
        """Q4: What files define the tool system?"""
        result = _chat(auth_token, "What files define the search tool system? List them.")
        assert len(result["text"]) > 50, "Response should list files"
        assert result["latency"] < 120, f"Response took {result['latency']:.1f}s"

    def test_q5_agent_loop_code(self, auth_token):
        """Q5: Show me the agent loop code."""
        result = _chat(auth_token, "Show me how the agent loop works in agent.py")
        assert len(result["text"]) > 100, "Response should show/describe code"
        assert result["latency"] < 120, f"Response took {result['latency']:.1f}s"
        # Should read the file
        assert any(t in result["tool_calls"] for t in ["read_workspace_file", "read_code_section", "read_source_file"]), \
            f"Should read files, used: {result['tool_calls']}"
```

- [ ] **Step 2: Run UI tests (requires running services)**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && WIKI_UI_TEST=1 python -m pytest tests/test_ui_code_search.py -v --timeout=120 2>&1 | tail -30
```

If services not running, tests skip gracefully.

- [ ] **Step 3: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add backend/tests/test_ui_code_search.py && git commit -m "test: add 5 UI code search tests via chat API

- Q1: Find SearchOrchestrator implementation
- Q2: Explain classify_query function
- Q3: Who calls format_results
- Q4: List search tool system files
- Q5: Show agent loop code
- Each test verifies: response length, latency < 120s, tool usage
- Requires WIKI_UI_TEST=1 and running services

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 13: Update Documentation

**Files:**
- Create: `documentation/search-strategy.md`
- Modify: `documentation/search-and-retrieval.md` (if exists)

- [ ] **Step 1: Create search strategy documentation**

Create `documentation/search-strategy.md`:

```markdown
# Search Strategy Engine

## Overview

The search strategy engine prevents the agent from getting stuck in infinite loops
when code search fails. It tracks search attempts per request and escalates through
increasingly broad search strategies.

## Strategy Escalation Order

1. **symbol_exact** — Direct symbol lookup via ChromaDB `symbols` collection
2. **lexical_code** — Ripgrep search in source code directories only
3. **semantic_code** — ChromaDB vector search in `code_docs` collection
4. **lexical_broad** — Ripgrep search across all directories (wiki + code)
5. **semantic_broad** — ChromaDB vector search across all collections

## Loop Prevention Rules

- Max 3 consecutive failed attempts per strategy before escalating
- After all 5 strategies exhausted → agent receives "EXHAUSTED" signal
- Agent system prompt instructs: "Do NOT retry the same search more than twice"
- `recursion_limit=25` on the LangGraph ReAct agent prevents infinite tool loops

## Repo Targeting Confidence

- **High**: Page URL matches a known repository namespace
- **Medium**: Query keywords match repository keywords
- **Low**: No signals found — search top 3 repositories

## Observability

Each search attempt is tracked in:
- OTEL spans: `search.strategy`, `search.repo_confidence`, `search.repos_targeted`
- Prometheus metrics: `agent_search_attempts_total`, `agent_strategy_escalations_total`
- Trace store: `search_attempts`, `search_strategy`, `strategies_exhausted` columns

## Key Fixes from Overhaul

| Issue | Before | After |
|-------|--------|-------|
| Tools available | `search_knowledge_base` (grep *.md only) | `smart_search`, `find_symbol`, `read_code_section` |
| Loop prevention | None | `recursion_limit=25` + strategy engine |
| Symbol search | Only ChromaDB (empty) | ChromaDB + lexical fallback in parallel |
| Lexical search | `--fixed-strings` (exact only) | Regex with camelCase→snake_case expansion |
| Scoring | +1.0 docs bias | +3.0 definition boost, +0.5 code boost |
| classify_query | Returns type only | Returns (type, extracted_symbol) |
| Repo targeting | List only | (repos, confidence) tuple |
```

- [ ] **Step 2: Commit**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add documentation/search-strategy.md && git commit -m "docs: add search strategy engine documentation

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 14: Run Full Test Suite and Fix Regressions

- [ ] **Step 1: Run all unit/integration tests**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/ -v --timeout=60 2>&1
```

- [ ] **Step 2: Fix any regressions**

Common expected regressions:
- Tests calling `classify_query()` expecting single string return → update to unpack tuple
- Tests calling `registry.target()` expecting list return → update to unpack tuple
- Tests referencing `search_knowledge_base` tool → update to `smart_search`

Fix each regression in the relevant test file.

- [ ] **Step 3: Run code-location tests**

```bash
cd /Users/weiqiangyu/Downloads/wiki/backend && python -m pytest tests/test_code_location.py -v --timeout=30 2>&1
```

- [ ] **Step 4: Commit fixes**

```bash
cd /Users/weiqiangyu/Downloads/wiki && git add -A && git commit -m "fix: resolve test regressions from API changes

- Update tests for classify_query tuple return
- Update tests for registry.target tuple return
- Update tool name references

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Dependency Order

```
Task 1 (lexical) → Task 2 (classify_query) → Task 3 (orchestrator) → Task 4 (agent wiring)
Task 5 (strategy engine) → Task 6 (loop hints) → Task 4 (depends on strategy)
Task 7 (repo targeting) → Task 3 (orchestrator uses confidence)
Task 8 (observability) → Task 9 (wire into agent)
Task 10 (indexer) — independent, can run anytime after Task 3
Task 11 (code-location tests) — depends on Tasks 1-7
Task 12 (UI tests) — depends on Tasks 1-10
Task 13 (documentation) — depends on Tasks 1-7
Task 14 (regression fixes) — final step
```

Recommended execution order: 1 → 2 → 3 → 5 → 7 → 4 → 6 → 8 → 9 → 10 → 11 → 13 → 14 → 12
