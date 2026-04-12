"""Multi-level search cache: L1 in-memory LRU + L2 SQLite persistent.

Inspired by Claude Code's dual-limit LRU pattern.
L1: fast in-memory OrderedDict with max entry count.
L2: SQLite with TTL-based expiry, survives restarts.
"""

import hashlib
import json
import logging
import os
import sqlite3
import time
from collections import OrderedDict

logger = logging.getLogger(__name__)


def _cache_key(query: str, scope: str) -> str:
    """Generate a deterministic cache key from query + scope."""
    return hashlib.sha256(f"{query}:{scope}".encode()).hexdigest()


class MultiLevelCache:
    """L1 in-memory LRU + L2 SQLite persistent search cache.

    Args:
        db_path: Path to SQLite database file for L2 cache.
        l1_max_entries: Maximum entries in the L1 LRU cache.
        l2_ttl_seconds: Time-to-live for L2 entries in seconds.
    """

    def __init__(
        self,
        db_path: str = "data/cache.db",
        l1_max_entries: int = 200,
        l2_ttl_seconds: int = 3600,
    ) -> None:
        self._l1: OrderedDict[str, list[dict]] = OrderedDict()
        self._l1_max = l1_max_entries
        self._l2_ttl = l2_ttl_seconds
        self._hits = 0
        self._misses = 0

        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS search_cache (
                key TEXT PRIMARY KEY,
                query TEXT,
                scope TEXT,
                results TEXT,
                token_count INTEGER,
                created_at REAL
            )"""
        )
        self._conn.commit()

    def get(self, query: str, scope: str) -> list[dict] | None:
        """Look up cached results. Checks L1 first, then L2."""
        key = _cache_key(query, scope)

        if key in self._l1:
            self._l1.move_to_end(key)
            self._hits += 1
            return self._l1[key]

        row = self._conn.execute(
            "SELECT results, created_at FROM search_cache WHERE key = ?", (key,)
        ).fetchone()

        if row:
            results_json, created_at = row
            age = time.time() - created_at
            if age <= self._l2_ttl:
                results = json.loads(results_json)
                self._l1_put(key, results)
                self._hits += 1
                return results
            else:
                self._conn.execute("DELETE FROM search_cache WHERE key = ?", (key,))
                self._conn.commit()

        self._misses += 1
        return None

    def put(
        self,
        query: str,
        scope: str,
        results: list[dict],
        token_count: int,
    ) -> None:
        """Store results in both L1 and L2."""
        key = _cache_key(query, scope)
        self._l1_put(key, results)

        self._conn.execute(
            """INSERT OR REPLACE INTO search_cache (key, query, scope, results, token_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (key, query, scope, json.dumps(results), token_count, time.time()),
        )
        self._conn.commit()

    def clear(self) -> None:
        """Clear both L1 and L2 caches."""
        self._l1.clear()
        self._conn.execute("DELETE FROM search_cache")
        self._conn.commit()
        self._hits = 0
        self._misses = 0

    def stats(self) -> dict:
        """Return cache statistics."""
        l2_count = self._conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
        return {
            "l1_size": len(self._l1),
            "l2_size": l2_count,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / max(1, self._hits + self._misses),
        }

    def _l1_put(self, key: str, results: list[dict]) -> None:
        """Add to L1 LRU with eviction."""
        if key in self._l1:
            self._l1.move_to_end(key)
        self._l1[key] = results
        while len(self._l1) > self._l1_max:
            self._l1.popitem(last=False)
