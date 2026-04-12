"""Search service layer for the wiki agent."""

from search.cache import MultiLevelCache
from search.registry import repo_registry, RepoRegistry, RepoMeta


def __getattr__(name: str):
    """Lazy-load heavy modules that depend on optional packages (e.g. chromadb)."""
    _lazy = {
        "SearchOrchestrator": ("search.orchestrator", "SearchOrchestrator"),
        "format_results": ("search.orchestrator", "format_results"),
        "classify_query": ("search.orchestrator", "classify_query"),
        "IndexBuilder": ("search.indexer", "IndexBuilder"),
        "SemanticSearch": ("search.semantic", "SemanticSearch"),
        "LexicalSearch": ("search.lexical", "LexicalSearch"),
        "SymbolExtractor": ("search.symbols", "SymbolExtractor"),
    }
    if name in _lazy:
        import importlib
        module_name, attr = _lazy[name]
        module = importlib.import_module(module_name)
        return getattr(module, attr)
    raise AttributeError(f"module 'search' has no attribute {name!r}")


__all__ = [
    "MultiLevelCache",
    "SearchOrchestrator",
    "IndexBuilder",
    "SemanticSearch",
    "LexicalSearch",
    "SymbolExtractor",
    "repo_registry",
    "RepoRegistry",
    "RepoMeta",
    "format_results",
    "classify_query",
]
