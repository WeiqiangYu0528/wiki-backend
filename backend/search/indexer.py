"""Index builder for semantic search and symbol extraction.

Runs at backend startup. Uses file checksums for incremental updates.
"""

import hashlib
import json
import logging
import os
import tempfile
import time

from search.chunker import chunk_markdown, chunk_source_file
from search.meilisearch_client import MeilisearchClient
from search.registry import RepoRegistry, repo_registry
from search.semantic import SemanticSearch
from search.symbols import SymbolExtractor

logger = logging.getLogger(__name__)

MANIFEST_FILE = "index_manifest.json"

# File extensions to index per language
_EXTENSIONS = {
    "python": [".py"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx"],
    "csharp": [".cs"],
}

# Directories to skip during source code indexing
_SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", "coverage", ".tox",
    "site-packages", "egg-info",
}

# Maximum file size to index (bytes)
_MAX_FILE_SIZE = 500_000  # 500 KB


def _file_hash(path: str) -> str:
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, IOError):
        return ""


def _lang_for_ext(ext: str) -> str:
    for lang, exts in _EXTENSIONS.items():
        if ext in exts:
            return lang
    return ""


class IndexBuilder:
    """Builds and maintains the search index."""

    def __init__(
        self,
        workspace_dir: str,
        semantic: SemanticSearch,
        registry: RepoRegistry | None = None,
        meilisearch_client: "MeilisearchClient | None" = None,
    ) -> None:
        self.workspace_dir = workspace_dir
        self.semantic = semantic
        self.registry = registry or repo_registry
        self._extractor = SymbolExtractor()
        self._meili = meilisearch_client
        self._manifest_path = os.path.join(
            workspace_dir, "backend", "data", MANIFEST_FILE,
        )
        self._manifest: dict[str, str] = self._load_manifest()
        self.stats: dict[str, int] = {
            "wiki_chunks": 0,
            "code_chunks": 0,
            "symbols": 0,
            "files_scanned": 0,
            "files_skipped": 0,
        }

    def _load_manifest(self) -> dict[str, str]:
        if os.path.exists(self._manifest_path):
            try:
                with open(self._manifest_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupted manifest at %s, starting fresh", self._manifest_path)
                return {}
        return {}

    def _save_manifest(self) -> None:
        manifest_dir = os.path.dirname(self._manifest_path)
        os.makedirs(manifest_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=manifest_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._manifest, f)
            os.rename(tmp_path, self._manifest_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _needs_update(self, path: str) -> bool:
        """Check if file has changed since last index, without updating manifest."""
        current_hash = _file_hash(path)
        if not current_hash:
            return False
        old_hash = self._manifest.get(path)
        return current_hash != old_hash

    def _mark_indexed(self, path: str) -> None:
        """Record current file hash in manifest after successful indexing."""
        current_hash = _file_hash(path)
        if current_hash:
            self._manifest[path] = current_hash

    def build(self) -> dict[str, int]:
        """Build or update the full index. Returns stats."""
        start = time.time()
        logger.info("Starting index build...")

        self._index_wiki_docs()
        self._index_source_code()

        self._save_manifest()
        elapsed = time.time() - start
        logger.info(
            "Index build complete in %.1fs: %d wiki chunks, %d code chunks, %d symbols",
            elapsed, self.stats["wiki_chunks"], self.stats["code_chunks"], self.stats["symbols"],
        )
        return self.stats

    def _index_wiki_docs(self) -> None:
        """Index all wiki markdown files."""
        docs_dir = os.path.join(self.workspace_dir, "docs")
        all_chunks: list[dict] = []

        for root, dirs, files in os.walk(docs_dir):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, self.workspace_dir)

                try:
                    if not self._needs_update(full_path):
                        self.stats["files_skipped"] += 1
                        continue
                except Exception as e:
                    logger.warning("Failed to check %s: %s", rel_path, e)
                    continue

                self.stats["files_scanned"] += 1
                try:
                    with open(full_path, encoding="utf-8") as f:
                        content = f.read()
                    chunks = chunk_markdown(content, file_path=rel_path)
                    for i, c in enumerate(chunks):
                        c["id"] = f"wiki:{rel_path}:{i}"
                    all_chunks.extend(chunks)
                    self._mark_indexed(full_path)
                except Exception as e:
                    logger.warning("Failed to index %s: %s", rel_path, e)

        if all_chunks:
            self.semantic.add_documents("wiki_docs", all_chunks)
            self.stats["wiki_chunks"] = len(all_chunks)
            if self._meili:
                meili_docs = [
                    {
                        "id": c["id"],
                        "content": c["text"],
                        "file_path": c.get("file_path", ""),
                        "section": c.get("section", ""),
                        "heading": c.get("heading", ""),
                        "type": "wiki",
                    }
                    for c in all_chunks
                ]
                self._meili.ensure_index("wiki_docs")
                self._meili.index_documents("wiki_docs", meili_docs)

    def _index_source_code(self) -> None:
        """Index source code files: docstrings, code chunks, and symbols."""
        code_chunks: list[dict] = []
        symbol_docs: list[dict] = []

        for repo in self.registry.repos:
            repo_dir = os.path.join(self.workspace_dir, repo.source_dir)
            if not os.path.isdir(repo_dir):
                continue

            for root, dirs, files in os.walk(repo_dir):
                dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
                for fname in files:
                    ext = os.path.splitext(fname)[1]
                    lang = _lang_for_ext(ext)
                    if not lang:
                        continue

                    full_path = os.path.join(root, fname)
                    if os.path.getsize(full_path) > _MAX_FILE_SIZE:
                        continue

                    rel_path = os.path.relpath(full_path, self.workspace_dir)

                    try:
                        if not self._needs_update(full_path):
                            self.stats["files_skipped"] += 1
                            continue
                    except Exception as e:
                        logger.warning("Failed to check %s: %s", rel_path, e)
                        continue

                    self.stats["files_scanned"] += 1
                    try:
                        with open(full_path, encoding="utf-8", errors="replace") as f:
                            content = f.read()
                    except Exception:
                        continue

                    # Code chunks
                    chunks = chunk_source_file(content, file_path=rel_path, language=lang)
                    for i, c in enumerate(chunks):
                        c["id"] = f"code:{rel_path}:{i}"
                    code_chunks.extend(chunks)

                    # Symbol extraction
                    symbols = self._extractor.extract(rel_path, content, lang)
                    for s in symbols:
                        s["id"] = f"sym:{rel_path}:{s['name']}"
                        s["text"] = f"{s['name']} ({s['kind']}) — {s['signature']}"
                        if s.get("docstring"):
                            s["text"] += f" — {s['docstring']}"
                    symbol_docs.extend(symbols)

                    self._mark_indexed(full_path)

        if code_chunks:
            self.semantic.add_documents("code_docs", code_chunks)
            self.stats["code_chunks"] = len(code_chunks)
            if self._meili:
                meili_docs = [
                    {
                        "id": c["id"],
                        "content": c["text"],
                        "file_path": c.get("file_path", ""),
                        "symbol": c.get("symbol", ""),
                        "kind": c.get("kind", ""),
                        "type": "code",
                    }
                    for c in code_chunks
                ]
                self._meili.ensure_index("code_docs")
                self._meili.index_documents("code_docs", meili_docs)

        if symbol_docs:
            self.semantic.add_documents("symbols", symbol_docs)
            self.stats["symbols"] = len(symbol_docs)
