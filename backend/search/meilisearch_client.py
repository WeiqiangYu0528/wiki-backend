# backend/search/meilisearch_client.py
"""Meilisearch client for hybrid BM25 + vector search.

Wraps the meilisearch Python client with our domain-specific index
configuration and search interface. Supports hybrid search when
MEILI_EXPERIMENTAL_VECTOR_STORE is enabled.
"""

import logging
from typing import Any

try:
    import meilisearch
except ImportError:
    meilisearch = None  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_INDEX_SETTINGS = {
    "searchableAttributes": ["content", "section", "heading", "symbol"],
    "filterableAttributes": ["type", "repo", "file_path", "kind"],
    "sortableAttributes": ["file_path"],
    "rankingRules": [
        "words", "typo", "proximity", "attribute", "sort", "exactness",
    ],
}


class MeilisearchClient:
    """Client for Meilisearch with hybrid search support.

    Args:
        url: Meilisearch server URL.
        api_key: API key for authentication (empty for dev).
    """

    def __init__(self, url: str = "http://localhost:7700", api_key: str = "") -> None:
        self._url = url
        self._api_key = api_key
        if meilisearch is None:
            logger.warning("meilisearch package not installed — client will be non-functional")
            self._client = None
        else:
            self._client = meilisearch.Client(url, api_key)

    @property
    def available(self) -> bool:
        """Check if Meilisearch is reachable."""
        if not self._client:
            return False
        try:
            self._client.health()
            return True
        except Exception:
            return False

    def ensure_index(self, index_name: str, primary_key: str = "id") -> None:
        """Create an index if it doesn't exist and apply settings."""
        if not self._client:
            return
        try:
            self._client.create_index(index_name, {"primaryKey": primary_key})
        except Exception:
            pass
        try:
            index = self._client.index(index_name)
            index.update_settings(DEFAULT_INDEX_SETTINGS)
        except Exception as e:
            logger.warning("Failed to update index settings for %s: %s", index_name, e)

    def index_documents(
        self,
        index_name: str,
        documents: list[dict],
        primary_key: str = "id",
    ) -> None:
        """Add or update documents in an index."""
        if not self._client or not documents:
            return
        try:
            index = self._client.index(index_name)
            for i in range(0, len(documents), 1000):
                batch = documents[i:i + 1000]
                index.add_documents(batch, primary_key)
        except Exception as e:
            logger.error("Failed to index %d documents to %s: %s", len(documents), index_name, e)

    def search(
        self,
        index_name: str,
        query: str,
        limit: int = 15,
        filter_expr: str | None = None,
    ) -> list[dict]:
        """Search an index. Returns normalized results."""
        if not self._client or not query.strip():
            return []
        try:
            index = self._client.index(index_name)
            params: dict[str, Any] = {
                "limit": limit,
                "showRankingScore": True,
            }
            if filter_expr:
                params["filter"] = filter_expr
            raw = index.search(query, params)
            results: list[dict] = []
            for hit in raw.get("hits", []):
                results.append({
                    "id": hit.get("id", ""),
                    "text": hit.get("content", ""),
                    "content": hit.get("content", ""),
                    "file_path": hit.get("file_path", ""),
                    "section": hit.get("section", ""),
                    "heading": hit.get("heading", ""),
                    "symbol": hit.get("symbol", ""),
                    "kind": hit.get("kind", ""),
                    "normalized_score": hit.get("_rankingScore", 0.0),
                    "source": "meilisearch",
                })
            return results
        except Exception as e:
            logger.warning("Meilisearch search failed: %s", e)
            return []

    def delete_index(self, index_name: str) -> None:
        """Delete an index."""
        if not self._client:
            return
        try:
            self._client.delete_index(index_name)
        except Exception:
            pass

    def document_count(self, index_name: str) -> int:
        """Return document count in an index."""
        if not self._client:
            return 0
        try:
            stats = self._client.index(index_name).get_stats()
            return stats.get("numberOfDocuments", 0)
        except Exception:
            return 0
