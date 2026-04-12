"""Search service layer for the wiki agent."""

from search.orchestrator import SearchOrchestrator, format_results, classify_query
from search.indexer import IndexBuilder
from search.registry import repo_registry, RepoRegistry, RepoMeta
from search.semantic import SemanticSearch
from search.lexical import LexicalSearch
from search.symbols import SymbolExtractor

__all__ = [
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
