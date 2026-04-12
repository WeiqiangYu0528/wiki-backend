# Memory Package

Persistent memory for the wiki agent using SQLite FTS5 full-text search.

## Components

- **base.py** — Abstract `MemoryManager` protocol with `query()`, `add()`, `clear()`, `count()`.
- **sqlite_memory.py** — `SQLiteMemory` implementation using SQLite FTS5, WAL mode, and oldest-first eviction.

## Usage

```python
from memory import SQLiteMemory

mem = SQLiteMemory(db_path="data/memory.db", max_items=1000)
mem.add("User prefers concise answers", {"source": "user"})
results = mem.query("user preferences", top_k=5)
```

## Future

- Embedding-based similarity retrieval (via Ollama)
- Temporal decay for older memories
- Task-centric memory (learn from past successes)
