"""SQLite-backed request trace summary store."""

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS request_traces (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    model TEXT NOT NULL,
    query TEXT NOT NULL,
    status TEXT NOT NULL,
    total_tokens INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    llm_calls INTEGER DEFAULT 0,
    tool_calls INTEGER DEFAULT 0,
    search_calls INTEGER DEFAULT 0,
    embedding_calls INTEGER DEFAULT 0,
    prompt_chars INTEGER DEFAULT 0,
    retrieval_chars INTEGER DEFAULT 0,
    citations_count INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    error_message TEXT DEFAULT '',
    tiers_used TEXT DEFAULT '',
    tools_used TEXT DEFAULT ''
)
"""


class RequestTraceStore:
    """Thread-safe SQLite store for per-request trace summaries."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(CREATE_TABLE_SQL)
                conn.commit()
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def write(
        self,
        request_id: str,
        model: str,
        query: str,
        status: str,
        total_tokens: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        llm_calls: int = 0,
        tool_calls: int = 0,
        search_calls: int = 0,
        embedding_calls: int = 0,
        prompt_chars: int = 0,
        retrieval_chars: int = 0,
        citations_count: int = 0,
        duration_ms: int = 0,
        error_message: str = "",
        tiers_used: str = "",
        tools_used: str = "",
    ) -> None:
        """Write a request trace summary row."""
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO request_traces
                    (id, timestamp, model, query, status, total_tokens, input_tokens,
                     output_tokens, llm_calls, tool_calls, search_calls, embedding_calls,
                     prompt_chars, retrieval_chars, citations_count, duration_ms,
                     error_message, tiers_used, tools_used)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        request_id, timestamp, model, query[:200], status,
                        total_tokens, input_tokens, output_tokens,
                        llm_calls, tool_calls, search_calls, embedding_calls,
                        prompt_chars, retrieval_chars, citations_count, duration_ms,
                        error_message, tiers_used, tools_used,
                    ),
                )
                conn.commit()
            except Exception as e:
                logger.error("Failed to write trace: %s", e)
            finally:
                conn.close()

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Run a read query and return rows as dicts."""
        conn = self._connect()
        try:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def recent(self, limit: int = 20) -> list[dict]:
        """Return the most recent trace summaries."""
        return self.query(
            "SELECT * FROM request_traces ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
