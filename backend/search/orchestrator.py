"""Search orchestrator: repo targeting, tier escalation, result ranking."""

import logging
import re
import time
from typing import Optional

from opentelemetry import trace

from observability import get_tracer, AgentMetrics
from search.lexical import LexicalSearch
from search.registry import RepoMeta, RepoRegistry, repo_registry
from search.semantic import SemanticSearch
from search.meilisearch_client import MeilisearchClient
from search.reranker import JaccardReranker
from search.cache import MultiLevelCache

logger = logging.getLogger(__name__)


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
    # Look for function call patterns first: word()
    func_call = re.search(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(\)', stripped)
    if func_call:
        return "symbol", func_call.group(1)
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


def format_results(
    results: list[dict],
    max_chars: int = 2000,
    result_max_chars: int = 200,
) -> str:
    """Format search results into a concise string for the agent."""
    if not results:
        return "No results found."

    parts: list[str] = []
    total = 0
    for r in results:
        file_path = r.get("file_path", "unknown")
        text = r.get("text", "").strip()
        line = r.get("line_number") or r.get("start_line", "")
        symbol = r.get("symbol", "")

        if len(text) > result_max_chars:
            text = text[:result_max_chars] + "…"

        if symbol:
            entry = f"**{file_path}** (L{line}) — `{symbol}`\n{text}"
        elif line:
            entry = f"**{file_path}** (L{line})\n{text}"
        else:
            entry = f"**{file_path}**\n{text}"

        if total + len(entry) > max_chars:
            parts.append(f"\n… ({len(results) - len(parts)} more results truncated)")
            break
        parts.append(entry)
        total += len(entry)

    return "\n\n".join(parts)


class SearchOrchestrator:
    """Orchestrates parallel hybrid search with reranking and budget trimming."""

    def __init__(
        self,
        workspace_dir: str,
        semantic: SemanticSearch,
        registry: RepoRegistry | None = None,
        meilisearch_client: "MeilisearchClient | None" = None,
        reranker: "JaccardReranker | None" = None,
        cache: "MultiLevelCache | None" = None,
        max_results: int = 8,
        max_chars: int = 2000,
        result_max_chars: int = 200,
    ) -> None:
        self.workspace_dir = workspace_dir
        self.registry = registry or repo_registry
        self.lexical = LexicalSearch(workspace_dir)
        self.semantic = semantic
        self._meili = meilisearch_client
        self._reranker = reranker
        self._cache = cache
        self._ready = False
        self._max_results = max_results
        self._max_chars = max_chars
        self._result_max_chars = result_max_chars

    @property
    def is_ready(self) -> bool:
        return self._ready

    def mark_ready(self) -> None:
        self._ready = True

    def clear_cache(self) -> None:
        if self._cache:
            self._cache.clear()

    def search(
        self,
        query: str,
        scope: str = "auto",
        page_url: str = "",
        max_results: int = 0,
        token_budget: int = 0,
    ) -> str:
        """Run parallel hybrid search with reranking and budget trimming."""
        if not query.strip():
            return "No results found."

        max_results = max_results or self._max_results
        tracer = get_tracer()

        with tracer.start_as_current_span("search.orchestrator") as span:
            span.set_attribute("search.query", query[:200])
            span.set_attribute("search.scope", scope)

            # Cache check
            if self._cache:
                cached = self._cache.get(query, scope)
                if cached is not None:
                    span.set_attribute("search.cache_hit", True)
                    return format_results(cached, max_chars=self._max_chars, result_max_chars=self._result_max_chars)
            span.set_attribute("search.cache_hit", False)

            namespace = scope if scope not in ("auto", "wiki", "code") else ""
            targets = self.registry.target(query, page_url=page_url, namespace=namespace)
            query_type, effective_query = classify_query(query)
            span.set_attribute("search.query_type", query_type)
            span.set_attribute("search.effective_query", effective_query[:200])
            # Use extracted symbol for lexical/meilisearch when query is symbol type
            search_query = effective_query if query_type == "symbol" else query

            all_results: list[dict] = []
            sources_used: list[str] = []

            # Meilisearch (BM25 + vector)
            if self._meili and self._meili.available:
                with tracer.start_as_current_span("search.meilisearch") as ms_span:
                    t0 = time.time()
                    if scope in ("auto", "wiki"):
                        all_results.extend(self._meili.search("wiki_docs", search_query, limit=15))
                    if scope in ("auto", "code"):
                        all_results.extend(self._meili.search("code_docs", search_query, limit=15))
                    ms_span.set_attribute("search.results_count", len(all_results))
                    ms_span.set_attribute("search.duration_ms", int((time.time() - t0) * 1000))
                sources_used.append("meilisearch")
            else:
                # Fallback to ripgrep lexical search
                with tracer.start_as_current_span("search.lexical") as lex_span:
                    t0 = time.time()
                    search_paths = self._get_search_paths(scope, targets)
                    lexical_results = self.lexical.search(search_query, search_paths=search_paths, max_results=max_results)
                    lex_span.set_attribute("search.results_count", len(lexical_results))
                    lex_span.set_attribute("search.duration_ms", int((time.time() - t0) * 1000))
                all_results.extend(lexical_results)
                sources_used.append("lexical")

            # ChromaDB semantic (for concept queries)
            if self._ready and query_type == "concept":
                with tracer.start_as_current_span("search.semantic") as sem_span:
                    t0 = time.time()
                    semantic_results = self._semantic_search(query, scope, targets, max_results=10)
                    sem_span.set_attribute("search.results_count", len(semantic_results))
                    sem_span.set_attribute("search.duration_ms", int((time.time() - t0) * 1000))
                all_results.extend(semantic_results)
                sources_used.append("semantic")

            # Symbol search (for symbol queries)
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

            # Normalize scores to 0-1
            for r in all_results:
                if "normalized_score" not in r:
                    r["normalized_score"] = r.get("score", 0.0)

            # Dedup by (file_path, section/line)
            seen: set[str] = set()
            unique: list[dict] = []
            for r in all_results:
                key = f"{r.get('file_path', '')}:{r.get('section', r.get('start_line', ''))}"
                if key not in seen:
                    seen.add(key)
                    unique.append(r)

            # Rerank
            if self._reranker and unique:
                with tracer.start_as_current_span("search.rerank"):
                    unique = self._reranker.rerank(query, unique, top_k=max_results)
            else:
                unique.sort(key=lambda r: r.get("normalized_score", 0), reverse=True)
                unique = unique[:max_results]

            span.set_attribute("search.final_results_count", len(unique))

            # Cache the results
            if self._cache and unique:
                token_count = sum(len(r.get("text", "")) // 4 for r in unique)
                self._cache.put(query, scope, unique, token_count)

            return format_results(unique, max_chars=self._max_chars, result_max_chars=self._result_max_chars)

    def find_symbol(self, name: str, namespace: str = "") -> str:
        """Find a symbol by name. Unchanged from v1."""
        if not self._ready:
            return "Search index is still building. Please try again in a moment."
        where = {"file_path": {"$contains": namespace}} if namespace else None
        results = self.semantic.query("symbols", name, n_results=10, where=where)
        if not results:
            paths = []
            if namespace:
                repo = self.registry.get_by_namespace(namespace)
                if repo:
                    paths = [repo.source_dir]
            results = self.lexical.search(name, search_paths=paths or None, max_results=5)
        return format_results(results, max_chars=self._max_chars, result_max_chars=self._result_max_chars)

    def _semantic_search(self, query: str, scope: str, targets: list[RepoMeta], max_results: int) -> list[dict]:
        results: list[dict] = []
        if scope in ("auto", "wiki"):
            results.extend(self.semantic.query("wiki_docs", query, n_results=max_results))
        if scope in ("auto", "code"):
            results.extend(self.semantic.query("code_docs", query, n_results=max_results))
        return results

    def _get_search_paths(self, scope: str, targets: list[RepoMeta]) -> list[str]:
        if scope == "wiki":
            return [r.wiki_dir for r in targets]
        if scope == "code":
            return [r.source_dir for r in targets]
        paths = []
        for t in targets[:3]:
            paths.extend([t.wiki_dir, t.source_dir])
        return paths
