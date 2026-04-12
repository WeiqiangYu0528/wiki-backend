"""Persistent SQLite embedding cache.

Replaces the in-memory LRU cache. Embeddings don't change for the same
text+model, so no TTL is needed. This eliminates re-embedding costs
across restarts.
"""

import hashlib
import logging
import os
import sqlite3
import struct

logger = logging.getLogger(__name__)


def _cache_key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}:{text}".encode()).hexdigest()


def _pack_embedding(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)


def _unpack_embedding(data: bytes) -> list[float]:
    count = len(data) // 4  # float32 = 4 bytes
    return list(struct.unpack(f"{count}f", data))


class PersistentEmbeddingCache:
    """SQLite-backed embedding cache with no TTL (embeddings are immutable).

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str = "data/embedding_cache.db") -> None:
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS embedding_cache (
                key TEXT PRIMARY KEY,
                model TEXT,
                text_hash TEXT,
                embedding BLOB,
                created_at REAL DEFAULT (julianday('now'))
            )"""
        )
        self._conn.commit()
        self._hits = 0
        self._misses = 0

    def get(self, model: str, text: str) -> list[float] | None:
        """Retrieve a cached embedding."""
        key = _cache_key(model, text)
        row = self._conn.execute(
            "SELECT embedding FROM embedding_cache WHERE key = ?", (key,)
        ).fetchone()
        if row:
            self._hits += 1
            return _unpack_embedding(row[0])
        self._misses += 1
        return None

    def put(self, model: str, text: str, embedding: list[float]) -> None:
        """Store an embedding in the cache."""
        key = _cache_key(model, text)
        text_hash = hashlib.md5(text.encode()).hexdigest()
        self._conn.execute(
            """INSERT OR REPLACE INTO embedding_cache (key, model, text_hash, embedding)
            VALUES (?, ?, ?, ?)""",
            (key, model, text_hash, _pack_embedding(embedding)),
        )
        self._conn.commit()

    def batch_get(self, model: str, texts: list[str]) -> dict[str, list[float]]:
        """Retrieve multiple embeddings at once. Returns {text: embedding} for hits only."""
        results: dict[str, list[float]] = {}
        for text in texts:
            emb = self.get(model, text)
            if emb is not None:
                results[text] = emb
        return results

    def clear(self) -> None:
        """Clear all cached embeddings."""
        self._conn.execute("DELETE FROM embedding_cache")
        self._conn.commit()
        self._hits = 0
        self._misses = 0

    @property
    def stats(self) -> dict[str, int]:
        count = self._conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]
        return {
            "size": count,
            "hits": self._hits,
            "misses": self._misses,
        }
