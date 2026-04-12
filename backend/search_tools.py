"""LangChain tool wrappers for the search service layer."""

import os
import re
import threading

from langchain_core.tools import tool

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_orchestrator = None
_lock = threading.Lock()


def get_orchestrator():
    global _orchestrator
    with _lock:
        if _orchestrator is None:
            from search.orchestrator import SearchOrchestrator
            from search.semantic import SemanticSearch
            from security import settings

            chroma_dir = os.path.join(os.path.dirname(__file__), "data", "chromadb")
            semantic = SemanticSearch(
                persist_dir=chroma_dir,
                ollama_base_url=settings.ollama_base_url,
                ollama_model=settings.ollama_embed_model,
            )
            _orchestrator = SearchOrchestrator(
                workspace_dir=ROOT_DIR,
                semantic=semantic,
                max_results=settings.search_max_results,
                max_chars=settings.search_max_chars,
                result_max_chars=settings.search_result_max_chars,
            )
    return _orchestrator


def set_orchestrator(orch) -> None:
    global _orchestrator
    _orchestrator = orch


@tool
def smart_search(query: str, scope: str = "auto") -> str:
    """Search across wiki documentation and source code repositories.

    The search automatically determines which repos to target and
    which strategy to use (lexical text search, semantic similarity,
    or symbol lookup) based on the query.

    Args:
        query: Natural language question, code identifier, or search term.
        scope: Search scope. Options:
            - "auto" (recommended) — search both wiki and source code
            - "wiki" — search only wiki documentation
            - "code" — search only source code
            - A namespace like "claude-code" — search that repo only
    """
    orch = get_orchestrator()
    if not orch:
        return "Error: Search system not initialized."
    try:
        return orch.search(query=query, scope=scope)
    except Exception as e:
        return f"Search error: {e}"


@tool
def find_symbol(name: str, namespace: str = "") -> str:
    """Find a function, class, interface, or type definition by name.

    Returns the definition location, signature, and docstring.
    Use this when you know the exact name of a code symbol.

    Args:
        name: The symbol name (e.g. 'MemoryMiddleware', 'create_react_agent').
        namespace: Optional namespace to limit search (e.g. 'deepagents').
    """
    orch = get_orchestrator()
    if not orch:
        return "Error: Search system not initialized."
    try:
        return orch.find_symbol(name=name, namespace=namespace)
    except Exception as e:
        return f"Symbol lookup error: {e}"


@tool
def read_code_section(
    file_path: str,
    symbol: str = "",
    start_line: int = 0,
    end_line: int = 0,
) -> str:
    """Read a specific section of a source file. More token-efficient
    than reading the entire file when you only need part of it.

    Specify either:
    - A line range (start_line and end_line), or
    - A symbol name (reads that function/class definition)
    If neither is specified, reads the first 50 lines.

    Args:
        file_path: Path relative to workspace root (e.g. 'deepagents/libs/deepagents/deepagents/graph.py')
        symbol: Optional symbol name to extract (e.g. 'GraphFactory')
        start_line: Start line number (1-indexed)
        end_line: End line number (1-indexed, inclusive)
    """
    from security import settings

    target = os.path.abspath(os.path.join(ROOT_DIR, file_path))
    if not target.startswith(ROOT_DIR + os.sep) and target != ROOT_DIR:
        return "Error: Access denied."
    if not os.path.exists(target):
        return f"Error: File '{file_path}' does not exist."

    try:
        with open(target, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return f"Error reading file: {e}"

    total = len(lines)
    default_lines = settings.read_code_default_lines
    max_symbol_lines = settings.read_code_max_symbol_lines

    if symbol:
        pattern = re.compile(
            rf"^(?:export\s+)?(?:async\s+)?(?:def|class|function|interface|type|enum)\s+{re.escape(symbol)}\b"
        )
        start_idx = None
        for i, line in enumerate(lines):
            if pattern.match(line.strip()):
                start_idx = i
                break

        if start_idx is None:
            return f"Symbol '{symbol}' not found in {file_path}. File has {total} lines."

        end_idx = min(start_idx + max_symbol_lines, total)
        for i in range(start_idx + 1, end_idx):
            if i < total and lines[i].strip() and not lines[i][0].isspace() and pattern.match(lines[i].strip()):
                end_idx = i
                break

        content = "".join(lines[start_idx:end_idx])
        return f"# {file_path} — `{symbol}` (L{start_idx + 1}-{end_idx})\n\n```\n{content}```"

    if start_line > 0:
        s = max(0, start_line - 1)
        e = min(total, end_line if end_line > 0 else s + default_lines)
        content = "".join(lines[s:e])
        return f"# {file_path} (L{s + 1}-{e} of {total})\n\n```\n{content}```"

    content = "".join(lines[:default_lines])
    suffix = f"\n… ({total - default_lines} more lines)" if total > default_lines else ""
    return f"# {file_path} (L1-{min(default_lines, total)} of {total})\n\n```\n{content}```{suffix}"
