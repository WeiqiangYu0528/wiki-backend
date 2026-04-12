# Agent System Overhaul — Design Spec

## Problem Statement

The wiki agent system has critical failures in code search, loop prevention, and observability:

1. **Code search broken**: `smart_search`, `find_symbol`, `read_code_section` tools exist in `search_tools.py` but are **never wired** to the agent (line 280 of `agent.py` only includes basic tools). The agent can only grep markdown docs.
2. **Infinite loops**: `create_react_agent()` has no `recursion_limit`. When search returns "No results found", the agent retries the same failing tool indefinitely.
3. **Zero code/symbol indexes**: ChromaDB has 730 wiki doc embeddings but 0 code embeddings, 0 symbol embeddings. Meilisearch has 0 indexes. The indexer infrastructure exists but was never executed.
4. **Lexical search weak for code**: Uses `--fixed-strings` (no regex), scoring biased toward `docs/` paths, no definition detection boost.
5. **No strategy escalation**: Symbol queries don't fall back to lexical. No failed-query memory. No strategy switching.
6. **Observability gaps**: No loop detection metrics, no search result quality tracking, no per-request workflow traces.

## Approach

**Approach A: Quick-wire + Index** — Fix critical wiring bugs, populate indexes, add recursion limits, build rule-based search strategy engine with loop prevention. Fastest path to a working system.

---

## Section 1: Core Architecture Fixes

### 1a. Wire search tools to agent

**File**: `backend/agent.py` line 280

**Current**:
```python
tools = [read_workspace_file, read_source_file, search_knowledge_base, list_wiki_pages, propose_doc_change]
```

**New**:
```python
from search_tools import smart_search, find_symbol, read_code_section

tools = [
    smart_search,        # Hybrid search across wiki + code
    find_symbol,         # Symbol-specific lookup
    read_code_section,   # Token-efficient file section reading
    read_workspace_file, # Full file reading
    read_source_file,    # Source file by namespace
    list_wiki_pages,     # Page listing
    propose_doc_change,  # Doc change proposals
]
```

Remove the old `search_knowledge_base` tool (basic grep on `*.md` only). The `smart_search` tool supersedes it with hybrid search across all content types.

### 1b. Add recursion limit

**File**: `backend/agent.py` lines 418 and 530

```python
agent = create_react_agent(llm, tools=tools, recursion_limit=25)
```

After 25 iterations the agent stops. The system prompt will instruct the model to summarize findings if it runs out of iterations.

### 1c. Populate indexes at startup

**File**: `backend/main.py` or new `backend/indexer.py`

On application startup (or via CLI command):
1. Run `IndexBuilder.build()` to populate:
   - ChromaDB `symbols` collection (tree-sitter extracted function/class definitions)
   - ChromaDB `code_docs` collection (code file chunk embeddings)
   - Meilisearch `wiki_docs` + `code_docs` indexes
2. Save `data/index_manifest.json` for incremental updates
3. Mark orchestrator as ready: `orchestrator.mark_ready()`

This can be a `@app.on_event("startup")` hook or a separate `python -m indexer` command.

### 1d. Fix lexical search

**File**: `backend/search/lexical.py`

Changes:
- Remove `--fixed-strings` flag → use regex mode with `re.escape()` for safety
- Add `--type` filters for code files (py, ts, js, go, rs, cs, java)
- Add definition detection boost: +3.0 for lines matching `def|class|function|interface|type|enum` followed by the query term
- Remove `docs/` path bias: replace +1.0 docs boost with +1.0 source code boost
- Add camelCase → snake_case query expansion (search both variants)

### 1e. Fix orchestrator symbol path

**File**: `backend/search/orchestrator.py`

Current problem: When `query_type == "symbol"`, only semantic search runs. If symbol collection is empty, returns nothing.

Fix: Symbol queries now run BOTH semantic AND lexical in parallel:
```python
if query_type == "symbol":
    # Parallel: semantic symbols + lexical code search
    symbol_results = self.semantic.query("symbols", query, n_results=5)
    lexical_results = self.lexical.search(query, search_paths=code_paths, max_results=5)
    all_results.extend(symbol_results)
    all_results.extend(lexical_results)
```

Also ensure lexical search runs for ALL query types as a baseline, not just when Meilisearch is unavailable.

### 1f. Fix classify_query for mixed NL+symbol

**File**: `backend/search/orchestrator.py`

Add symbol extraction from natural language queries:
```python
def classify_query(query: str) -> tuple[str, str]:
    """Returns (query_type, extracted_symbol_or_original_query)."""
    # Extract symbol from patterns like "Explain startMdmRawRead()"
    symbol_match = re.search(r'([A-Z][a-zA-Z0-9]+(?:[A-Z][a-z]+)+|[a-z_][a-z0-9_]*(?:_[a-z0-9]+)+)\s*\(?', query)
    if symbol_match:
        return "symbol", symbol_match.group(1)
    # ... existing classification logic
```

This extracts `startMdmRawRead` from "Explain startMdmRawRead()" and classifies as symbol.

---

## Section 2: Search Strategy Engine & Loop Prevention

### 2a. Search Strategy Engine

**New file**: `backend/search/strategy.py`

```python
class SearchStrategyEngine:
    """Tracks search attempts per request and manages strategy escalation."""
    
    STRATEGIES = ["symbol_exact", "lexical_code", "semantic_code", "lexical_broad", "semantic_broad"]
    MAX_ATTEMPTS_PER_STRATEGY = 3
    
    def __init__(self):
        self.attempted_queries: set[str] = set()
        self.attempt_count: int = 0
        self.current_strategy_idx: int = 0
        self.results_per_strategy: dict[str, int] = {}
        self.failed_strategies: set[str] = set()
    
    @property
    def current_strategy(self) -> str:
        return self.STRATEGIES[min(self.current_strategy_idx, len(self.STRATEGIES) - 1)]
    
    @property
    def exhausted(self) -> bool:
        return self.current_strategy_idx >= len(self.STRATEGIES)
    
    def record_attempt(self, query: str, result_count: int) -> str | None:
        """Record a search attempt. Returns warning message if loop detected."""
        self.attempted_queries.add(query)
        self.attempt_count += 1
        strategy = self.current_strategy
        
        self.results_per_strategy.setdefault(strategy, 0)
        self.results_per_strategy[strategy] += result_count
        
        if result_count == 0:
            attempts_this_strategy = sum(1 for q in self.attempted_queries 
                                          if self.results_per_strategy.get(strategy, 0) == 0)
            if attempts_this_strategy >= self.MAX_ATTEMPTS_PER_STRATEGY:
                self.failed_strategies.add(strategy)
                self.current_strategy_idx += 1
                if self.exhausted:
                    return "EXHAUSTED"
                return f"ESCALATED to {self.current_strategy}"
        return None
```

### 2b. Loop Detection in Tool Wrappers

Wrap tool outputs with context signals:

```python
# In smart_search tool wrapper
result = orch.search(query=query, scope=scope)
if result == "No results found.":
    hint = strategy_engine.record_attempt(query, 0)
    if hint == "EXHAUSTED":
        return "⚠️ All search strategies exhausted. Please summarize your findings."
    elif hint:
        return f"No results found. Strategy escalated: {hint}. Try a different query."
    return "No results found. Try rephrasing or a more specific/broader query."
```

### 2c. Repo Targeting with Confidence

**File**: `backend/search/registry.py`

Add confidence scoring:
```python
def target(self, query: str, page_url: str = "", page_title: str = "") -> tuple[list[RepoMeta], str]:
    """Returns (repos, confidence) where confidence is 'high'|'medium'|'low'."""
    
    # High confidence: page URL contains repo namespace
    for repo in self.repos:
        if repo.namespace in page_url or repo.namespace in page_title:
            return [repo], "high"
    
    # Medium confidence: keyword match
    matches = [(repo, score) for repo, score in keyword_scores if score > 0]
    if matches:
        matches.sort(key=lambda x: x[1], reverse=True)
        return [m[0] for m in matches[:2]], "medium"
    
    # Low confidence: return top 3 repos
    return self.repos[:3], "low"
```

### 2d. Graceful Failure Message

When all strategies are exhausted, the agent returns a structured failure:
```
I searched for "startMdmRawRead" using 5 strategies across 3 repositories:
- Symbol exact: 0 results in claude-code, openclaw
- Lexical code: 0 results
- Semantic code: 0 results  
- Lexical broad: 0 results
- Semantic broad: 0 results

The symbol was not found in the indexed codebases. Possible reasons:
- The function may be in a repository not yet indexed
- The function name may be spelled differently
- The source code may not be present in this workspace
```

---

## Section 3: Observability & Metrics

### 3a. Enhanced Trace Store

**File**: `backend/observability/trace_store.py`

Add columns to `request_traces` table:
```sql
ALTER TABLE request_traces ADD COLUMN search_strategy TEXT DEFAULT '';
ALTER TABLE request_traces ADD COLUMN search_attempts INTEGER DEFAULT 0;
ALTER TABLE request_traces ADD COLUMN search_result_counts TEXT DEFAULT '{}';  -- JSON
ALTER TABLE request_traces ADD COLUMN tool_call_sequence TEXT DEFAULT '[]';    -- JSON array
ALTER TABLE request_traces ADD COLUMN loop_detected BOOLEAN DEFAULT FALSE;
ALTER TABLE request_traces ADD COLUMN strategies_exhausted BOOLEAN DEFAULT FALSE;
ALTER TABLE request_traces ADD COLUMN repo_confidence TEXT DEFAULT '';
ALTER TABLE request_traces ADD COLUMN repo_selected TEXT DEFAULT '';
ALTER TABLE request_traces ADD COLUMN recursion_depth INTEGER DEFAULT 0;
```

### 3b. New Prometheus Metrics

**File**: `backend/observability/metrics.py`

```python
# Search metrics
search_attempts_total = meter.create_counter("agent_search_attempts_total")
search_results_histogram = meter.create_histogram("agent_search_result_count")
strategy_escalations_total = meter.create_counter("agent_strategy_escalations_total")

# Loop detection
loops_detected_total = meter.create_counter("agent_loops_detected_total")
recursion_depth_histogram = meter.create_histogram("agent_recursion_depth")

# Repo targeting
repo_confidence_counter = meter.create_counter("agent_repo_confidence_total")

# Code search quality
code_search_success = meter.create_counter("agent_code_search_success_total")
code_search_latency = meter.create_histogram("agent_code_search_latency_ms")
```

### 3c. Structured Logging

Every search step emits structured JSON:
```json
{
  "event": "search_attempt",
  "request_id": "abc-123",
  "strategy": "symbol_exact", 
  "query": "startMdmRawRead",
  "repo": "openclaw",
  "results": 0,
  "latency_ms": 45,
  "escalated": true
}
```

### 3d. Workflow Trace API

**New endpoint**: `GET /api/traces/{request_id}`

Returns full execution timeline:
```json
{
  "request_id": "abc-123",
  "query": "Explain startMdmRawRead()",
  "model": "ollama",
  "total_duration_ms": 4200,
  "recursion_depth": 8,
  "token_usage": {"input": 3400, "output": 850},
  "steps": [
    {"type": "tool_call", "name": "find_symbol", "input": {"name": "startMdmRawRead"}, "output_length": 0, "duration_ms": 120},
    {"type": "strategy_escalation", "from": "symbol_exact", "to": "lexical_code"},
    {"type": "tool_call", "name": "smart_search", "input": {"query": "startMdmRawRead", "scope": "code"}, "output_length": 450, "duration_ms": 230},
    {"type": "llm_call", "input_tokens": 2100, "output_tokens": 400, "duration_ms": 3200}
  ],
  "repo_confidence": "medium",
  "repo_selected": "openclaw",
  "loop_detected": false,
  "strategies_exhausted": false
}
```

---

## Section 4: Testing

### 4a. Code-Location Tests (12 tests)

**New file**: `backend/tests/test_code_location.py`

| # | Test Name | Query | Expected Behavior |
|---|-----------|-------|-------------------|
| 1 | test_exact_function_lookup | `find_symbol("SearchOrchestrator")` | Finds `backend/search/orchestrator.py` |
| 2 | test_camelcase_function | `find_symbol("startMdmRawRead")` | Finds in source code or graceful failure |
| 3 | test_snake_case_function | `find_symbol("classify_query")` | Finds `orchestrator.py` definition |
| 4 | test_class_lookup | `smart_search("JaccardReranker class", scope="code")` | Finds `backend/search/reranker.py` |
| 5 | test_cross_file_navigation | `smart_search("who calls SearchOrchestrator")` | Finds callers in search_tools.py, agent.py |
| 6 | test_cross_module_search | `smart_search("MemoryMiddleware", scope="deepagents")` | Finds in deepagents source |
| 7 | test_repo_from_page_context | Search with page_url containing "claude-code" | Targets claude-code repo |
| 8 | test_ambiguous_symbol | `find_symbol("search")` | Returns multiple results, doesn't loop |
| 9 | test_missing_symbol_graceful | `find_symbol("NonExistentXYZ123")` | Returns "not found" within 3 attempts |
| 10 | test_loop_prevention | 25+ iterations | Agent stops, doesn't hang |
| 11 | test_strategy_escalation | Symbol not in index | Escalates to lexical, finds via ripgrep |
| 12 | test_definition_vs_usage | `find_symbol("format_results")` | Definition ranked above usage |

Each test measures: `found` (bool), `latency_ms`, `looped` (bool), `attempts`, `strategies_used`.

### 4b. UI Tests (5 coding questions)

**New file**: `backend/tests/test_ui_code_search.py` (using browser-use)

| # | Question | Verification |
|---|----------|-------------|
| 1 | "Where is SearchOrchestrator implemented?" | Response contains file path |
| 2 | "Explain the classify_query function" | Response has function description |
| 3 | "Who calls format_results?" | Response lists callers |
| 4 | "What files define the tool system in claude-code?" | Response lists relevant files |
| 5 | "Show me the agent loop code" | Response contains code snippet |

### 4c. Performance/Latency Requirements

- Code symbol lookup: < 15s for indexed symbols
- Strategy exhaustion: < 30s (no infinite loops)
- Loop detection: Agent stops within 25 iterations
- Cache hit: < 100ms for repeated queries

---

## Section 5: Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `backend/agent.py` | MODIFY | Wire search tools, add recursion_limit, update system prompt |
| `backend/search/orchestrator.py` | MODIFY | Fix symbol search path, parallel lexical+semantic, fix classify_query |
| `backend/search/lexical.py` | MODIFY | Remove --fixed-strings, add definition boost, camelCase expansion |
| `backend/search/registry.py` | MODIFY | Add confidence scoring, page context signals |
| `backend/search/strategy.py` | CREATE | Search strategy engine with loop prevention |
| `backend/observability/metrics.py` | MODIFY | Add search/loop/repo metrics |
| `backend/observability/trace_store.py` | MODIFY | Add trace columns |
| `backend/main.py` | MODIFY | Add /api/traces endpoint, startup indexing |
| `backend/tests/test_code_location.py` | CREATE | 12 code-location tests |
| `backend/tests/test_ui_code_search.py` | CREATE | 5 UI coding question tests |
| `documentation/search-strategy.md` | CREATE | Strategy engine documentation |
| `documentation/diagrams/search-strategy.excalidraw` | CREATE | Strategy escalation diagram |

---

## Acceptance Criteria

1. ✅ Agent can find `SearchOrchestrator` by name in < 15s
2. ✅ Agent gracefully fails for non-existent symbols (no loop)
3. ✅ Agent stops within 25 iterations (recursion_limit)
4. ✅ Strategy escalation works: symbol → lexical → semantic → broad
5. ✅ Repo targeting uses page context with confidence scoring
6. ✅ `/api/traces/{id}` returns full workflow trace
7. ✅ Prometheus metrics for search attempts, loops, escalations
8. ✅ 12 code-location tests pass with local Ollama
9. ✅ 5 UI tests pass with local Ollama
10. ✅ No paid API tokens used in any test

## Risks

1. **Index population may be slow** — tree-sitter parsing 14,711 files could take minutes. Mitigation: run as CLI command, not blocking startup.
2. **Local Ollama latency** — qwen3.5 is slower than cloud APIs. Tests may need longer timeouts.
3. **ChromaDB collection compatibility** — Adding new collections to existing ChromaDB may need migration. Mitigation: test with fresh DB first.
4. **Regex in lexical search** — Removing `--fixed-strings` could cause regex injection. Mitigation: `re.escape()` all user queries.
