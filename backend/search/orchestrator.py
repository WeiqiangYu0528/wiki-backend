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

logger = logging.getLogger(__name__)


def classify_query(query: str) -> str:
    """Classify a query as 'symbol', 'concept', or 'exact'."""
    if re.match(r"^[A-Z][a-zA-Z0-9]*(?:[A-Z][a-z]+)+$", query.strip()):
        return "symbol"
    if re.match(r"^[a-z_][a-z0-9_]*(?:_[a-z0-9]+)+$", query.strip()):
        return "symbol"
    if "." in query and " " not in query:
        return "symbol"
    words = query.lower().split()
    if any(w in ("function", "class", "method", "def", "interface", "type") for w in words):
        for w in query.split():
            if re.match(r"^[A-Z][a-zA-Z0-9]+$", w) or re.match(r"^[a-z_]+[A-Z]", w):
                return "symbol"
            if re.match(r"^[a-z_][a-z0-9_]*_[a-z0-9_]+$", w):
                return "symbol"
    if query.startswith(("ERROR", "Error", "error")) or '"' in query or "'" in query:
        return "exact"
    if "/" in query and " " not in query:
        return "exact"
    return "concept"


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
    """Orchestrates multi-tier search with repo targeting and escalation."""

    def __init__(
        self,
        workspace_dir: str,
        semantic: SemanticSearch,
        registry: RepoRegistry | None = None,
        max_results: int = 8,
        max_chars: int = 2000,
        result_max_chars: int = 200,
    ) -> None:
        self.workspace_dir = workspace_dir
        self.registry = registry or repo_registry
        self.lexical = LexicalSearch(workspace_dir)
        self.semantic = semantic
        self._ready = False
        self._max_results = max_results
        self._max_chars = max_chars
        self._result_max_chars = result_max_chars
        self._session_cache: dict[str, str] = {}

    @property
    def is_ready(self) -> bool:
        return self._ready

    def mark_ready(self) -> None:
        self._ready = True

    def clear_cache(self) -> None:
        self._session_cache.clear()

    def search(
        self,
        query: str,
        scope: str = "auto",
        page_url: str = "",
        max_results: int = 0,
    ) -> str:
        """Run a multi-tier search with early stopping."""
        if not query.strip():
            return "No results found."

        max_results = max_results or self._max_results
        tracer = get_tracer()

        with tracer.start_as_current_span("search.orchestrator") as span:
            span.set_attribute("search.query", query[:200])
            span.set_attribute("search.scope", scope)

            cache_key = f"{query}:{scope}"
            if cache_key in self._session_cache:
                logger.debug("Search cache hit for: %s", query[:50])
                span.set_attribute("search.cache_hit", True)
                return self._session_cache[cache_key]

            span.set_attribute("search.cache_hit", False)

            namespace = scope if scope not in ("auto", "wiki", "code") else ""
            targets = self.registry.target(query, page_url=page_url, namespace=namespace)
            query_type = classify_query(query)
            span.set_attribute("search.query_type", query_type)

            all_results: list[dict] = []
            tiers_used: list[str] = []

            if scope == "wiki":
                search_paths = [r.wiki_dir for r in targets]
            elif scope == "code":
                search_paths = [r.source_dir for r in targets]
            elif namespace:
                t = targets[0] if targets else None
                search_paths = [t.wiki_dir, t.source_dir] if t else ["docs/"]
            else:
                search_paths = []
                for t in targets[:3]:
                    search_paths.extend([t.wiki_dir, t.source_dir])

            # --- Tier 1: Lexical ---
            with tracer.start_as_current_span("search.lexical") as lex_span:
                t0 = time.time()
                if query_type in ("symbol", "exact"):
                    lexical_results = self.lexical.search(query, search_paths=search_paths, max_results=max_results)
                else:
                    lexical_results = self.lexical.search(query, search_paths=search_paths, max_results=5)
                lex_span.set_attribute("search.results_count", len(lexical_results))
                lex_span.set_attribute("search.duration_ms", int((time.time() - t0) * 1000))
            all_results.extend(lexical_results)
            tiers_used.append("lexical")

            # Early stopping
            distinct_files = len({r.get("file_path", "") for r in all_results})
            high_confidence = len(all_results) >= 5 and distinct_files >= 2

            # --- Tier 2: Semantic ---
            if self._ready and not high_confidence and (query_type == "concept" or len(all_results) < 3):
                with tracer.start_as_current_span("search.semantic") as sem_span:
                    t0 = time.time()
                    semantic_results = self._semantic_search(query, scope, targets, max_results)
                    sem_span.set_attribute("search.results_count", len(semantic_results))
                    sem_span.set_attribute("search.duration_ms", int((time.time() - t0) * 1000))
                all_results.extend(semantic_results)
                tiers_used.append("semantic")
            elif high_confidence:
                span.set_attribute("search.early_stopped", True)

            # --- Tier 3: Symbol ---
            if self._ready and query_type == "symbol" and len(all_results) < 3:
                with tracer.start_as_current_span("search.symbol") as sym_span:
                    t0 = time.time()
                    symbol_results = self.semantic.query("symbols", query, n_results=5)
                    sym_span.set_attribute("search.results_count", len(symbol_results))
                    sym_span.set_attribute("search.duration_ms", int((time.time() - t0) * 1000))
                all_results.extend(symbol_results)
                tiers_used.append("symbol")

            span.set_attribute("search.tiers_used", ",".join(tiers_used))
            span.set_attribute("search.total_raw_results", len(all_results))
            logger.info("Search '%s' → tiers: %s, raw results: %d", query[:40], tiers_used, len(all_results))

            seen: set[str] = set()
            unique: list[dict] = []
            for r in all_results:
                key = f"{r.get('file_path', '')}:{r.get('line_number', r.get('start_line', ''))}"
                if key not in seen:
                    seen.add(key)
                    unique.append(r)

            unique.sort(key=lambda r: r.get("score", 0), reverse=True)
            final_count = min(len(unique), max_results)
            span.set_attribute("search.final_results_count", final_count)

            result = format_results(unique[:max_results], max_chars=self._max_chars, result_max_chars=self._result_max_chars)
            self._session_cache[cache_key] = result
            return result

    def find_symbol(self, name: str, namespace: str = "") -> str:
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
