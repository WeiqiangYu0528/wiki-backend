"""SQLite FTS5 memory implementation.

Uses FTS5 full-text search for keyword matching. Embedding-based
similarity is a future enhancement (requires Ollama integration).
Currently uses FTS5 rank scoring only.
"""

import json
import logging
import os
import sqlite3
import uuid

from memory.base import MemoryManager

logger = logging.getLogger(__name__)


class SQLiteMemory(MemoryManager):
    """SQLite FTS5 memory backend.

    Args:
        db_path: Path to the SQLite database file.
        max_items: Maximum memories to retain (oldest evicted first).
    """

    def __init__(
        self,
        db_path: str = "data/memory.db",
        max_items: int = 1000,
    ) -> None:
        self._max_items = max_items
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                content=memories,
                content_rowid=rowid
            );
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES('delete', old.rowid, old.content);
            END;
        """)
        self._conn.commit()

    def query(self, query: str, top_k: int = 5) -> list[dict]:
        """Search memories using FTS5 keyword matching."""
        if not query.strip():
            return []

        safe_query = " ".join(
            word for word in query.split() if word.strip()
        )
        if not safe_query:
            return []

        try:
            fts_query = " OR ".join(safe_query.split())
            rows = self._conn.execute(
                """SELECT m.id, m.content, m.metadata, rank
                FROM memories_fts f
                JOIN memories m ON f.rowid = m.rowid
                WHERE memories_fts MATCH ?
                ORDER BY rank
                LIMIT ?""",
                (fts_query, top_k),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = self._conn.execute(
                """SELECT id, content, metadata, 0.0
                FROM memories
                WHERE content LIKE ?
                ORDER BY created_at DESC
                LIMIT ?""",
                (f"%{safe_query}%", top_k),
            ).fetchall()

        return [
            {
                "id": row[0],
                "content": row[1],
                "metadata": json.loads(row[2]) if row[2] else {},
                "score": abs(row[3]) if row[3] else 0.0,
            }
            for row in rows
        ]

    def add(self, content: str, metadata: dict | None = None) -> None:
        """Store a memory. Evicts oldest if at capacity."""
        mem_id = str(uuid.uuid4())
        meta_json = json.dumps(metadata or {})
        self._conn.execute(
            "INSERT INTO memories (id, content, metadata) VALUES (?, ?, ?)",
            (mem_id, content, meta_json),
        )
        self._conn.commit()
        self._enforce_limit()

    def clear(self) -> None:
        """Remove all memories."""
        self._conn.executescript("""
            DELETE FROM memories;
            DELETE FROM memories_fts;
        """)
        self._conn.commit()

    def count(self) -> int:
        """Return number of stored memories."""
        return self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def _enforce_limit(self) -> None:
        """Evict oldest memories if over max_items."""
        current = self.count()
        if current > self._max_items:
            excess = current - self._max_items
            self._conn.execute(
                """DELETE FROM memories WHERE id IN (
                    SELECT id FROM memories ORDER BY created_at ASC LIMIT ?
                )""",
                (excess,),
            )
            self._conn.commit()
