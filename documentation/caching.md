# Caching Architecture

The backend uses a multi-level caching strategy to minimize redundant search
operations and embedding API calls. There are three distinct caches, each
serving a different purpose.

---

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Search Request                            │
│                         │                                    │
│                         ▼                                    │
│                ┌──────────────────┐                          │
│                │  L1: In-Memory   │  ← OrderedDict LRU      │
│                │  200 entries max │     Sub-millisecond       │
│                └────────┬─────────┘                          │
│                   miss  │  hit → return                      │
│                         ▼                                    │
│                ┌──────────────────┐                          │
│                │  L2: SQLite      │  ← TTL: 3600 seconds     │
│                │  data/cache.db   │     ~1ms lookup           │
│                └────────┬─────────┘                          │
│                   miss  │  hit → promote to L1 → return      │
│                         ▼                                    │
│              Execute search backends                         │
│                         │                                    │
│                         ▼                                    │
│              Store in L1 + L2                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    Embedding Request                         │
│                         │                                    │
│                         ▼                                    │
│                ┌──────────────────┐                          │
│                │  Embedding Cache │  ← SQLite, no TTL        │
│                │  (immutable)     │     data/cache.db         │
│                └────────┬─────────┘                          │
│                   miss  │  hit → return                      │
│                         ▼                                    │
│              Call Ollama API                                  │
│                         │                                    │
│                         ▼                                    │
│              Store in embedding cache                         │
└─────────────────────────────────────────────────────────────┘
```

---

## L1: In-Memory LRU Cache

**Module**: `search/cache.py`

### Design

The L1 cache is a Python `OrderedDict` used as an LRU (Least Recently Used)
cache. It lives entirely in process memory for maximum speed.

### Characteristics

| Property         | Value                        |
|------------------|------------------------------|
| Data structure   | `collections.OrderedDict`    |
| Max entries      | 200 (configurable: `CACHE_L1_MAX_ENTRIES`) |
| TTL              | None (eviction by LRU only)  |
| Persistence      | None (lost on restart)       |
| Lookup time      | Sub-millisecond              |
| Thread safety    | Single-threaded (async event loop) |

### Operations

**Get**:
```python
def get(self, key: str) -> Optional[dict]:
    if key in self._store:
        self._store.move_to_end(key)  # Mark as recently used
        self._hits += 1
        return self._store[key]
    self._misses += 1
    return None
```

**Set**:
```python
def set(self, key: str, value: dict) -> None:
    if key in self._store:
        self._store.move_to_end(key)
    self._store[key] = value
    if len(self._store) > self._max_entries:
        self._store.popitem(last=False)  # Evict oldest (LRU)
```

### Eviction Policy

When the cache reaches 200 entries and a new entry is added, the least
recently used entry is evicted. "Recently used" means either accessed (get)
or inserted/updated (set) — both operations move the entry to the end of the
ordered dict.

---

## L2: SQLite Cache

**Module**: `search/cache.py`

### Design

The L2 cache uses SQLite for persistence across backend restarts. It stores
search results with a TTL (time-to-live) for automatic expiration.

### Characteristics

| Property         | Value                        |
|------------------|------------------------------|
| Storage          | SQLite (`data/cache.db`)     |
| TTL              | 3600 seconds (configurable: `CACHE_L2_TTL_SECONDS`) |
| Persistence      | Yes (survives restarts)      |
| Lookup time      | ~1 millisecond               |
| Thread safety    | SQLite WAL mode              |
| Path             | Configurable: `CACHE_DB_PATH` |

### Schema

```sql
CREATE TABLE IF NOT EXISTS search_cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,        -- JSON-serialized search results
    created_at REAL NOT NULL,   -- Unix timestamp
    expires_at REAL NOT NULL    -- Unix timestamp (created_at + TTL)
);

CREATE INDEX IF NOT EXISTS idx_search_cache_expires
ON search_cache(expires_at);
```

### Operations

**Get**:
```python
async def get_l2(self, key: str) -> Optional[dict]:
    row = await db.execute(
        "SELECT value FROM search_cache WHERE key = ? AND expires_at > ?",
        (key, time.time())
    )
    if row:
        self._l2_hits += 1
        result = json.loads(row["value"])
        # Promote to L1
        self.set_l1(key, result)
        return result
    self._l2_misses += 1
    return None
```

**Set**:
```python
async def set_l2(self, key: str, value: dict) -> None:
    now = time.time()
    await db.execute(
        """INSERT OR REPLACE INTO search_cache (key, value, created_at, expires_at)
           VALUES (?, ?, ?, ?)""",
        (key, json.dumps(value), now, now + self._ttl)
    )
```

### TTL Expiration

Entries older than `CACHE_L2_TTL_SECONDS` (default 3600s = 1 hour) are treated
as misses on read. Expired entries are lazily cleaned up — they are not
proactively deleted but are overwritten on the next cache set for the same key.

Periodic cleanup can be triggered manually:
```python
async def cleanup_expired(self) -> int:
    result = await db.execute(
        "DELETE FROM search_cache WHERE expires_at < ?",
        (time.time(),)
    )
    return result.rowcount
```

---

## Cache Key Generation

Both L1 and L2 use the same key format:

```python
import hashlib

def make_cache_key(query: str, scope: str) -> str:
    raw = f"{query}:{scope}"
    return hashlib.sha256(raw.encode()).hexdigest()
```

The key includes:
- **query**: The search query text (case-sensitive)
- **scope**: The namespace/scope (e.g., "claude-code", "deepagents", or empty
  string for global)

This ensures that the same query in different namespaces produces different
cache keys, preventing cross-namespace contamination.

---

## Embedding Cache

**Module**: `search/embedding_cache.py`

### Design

A separate SQLite cache specifically for embedding vectors. Since embeddings
are deterministic (same text always produces the same vector), entries never
expire.

### Characteristics

| Property         | Value                        |
|------------------|------------------------------|
| Storage          | SQLite (`data/cache.db`)     |
| TTL              | None (immutable)             |
| Key              | SHA256 hash of input text    |
| Value            | Serialized float vector (768 dims) |
| Persistence      | Yes (survives restarts)      |

### Schema

```sql
CREATE TABLE IF NOT EXISTS embedding_cache (
    key TEXT PRIMARY KEY,
    embedding BLOB NOT NULL,    -- Packed float32 array (768 × 4 = 3072 bytes)
    model TEXT NOT NULL,        -- Model name (e.g., "nomic-embed-text")
    created_at REAL NOT NULL    -- Unix timestamp
);
```

### Operations

**Get**:
```python
async def get_embedding(self, text: str) -> Optional[list[float]]:
    key = hashlib.sha256(text.encode()).hexdigest()
    row = await db.execute(
        "SELECT embedding FROM embedding_cache WHERE key = ?", (key,)
    )
    if row:
        return struct.unpack(f'{EMBEDDING_DIMENSIONS}f', row["embedding"])
    return None
```

**Set**:
```python
async def set_embedding(self, text: str, vector: list[float]) -> None:
    key = hashlib.sha256(text.encode()).hexdigest()
    blob = struct.pack(f'{len(vector)}f', *vector)
    await db.execute(
        """INSERT OR IGNORE INTO embedding_cache (key, embedding, model, created_at)
           VALUES (?, ?, ?, ?)""",
        (key, blob, self._model_name, time.time())
    )
```

### Why No TTL?

Embeddings are immutable for a given model: the same input text always produces
the same vector output. The only case where cached embeddings become invalid is
if the embedding model changes — in that scenario, the cache should be manually
cleared:

```bash
sqlite3 data/cache.db "DELETE FROM embedding_cache;"
```

---

## Cache Statistics

The cache tracks hit/miss counts for monitoring:

```python
class SearchCache:
    @property
    def stats(self) -> dict:
        total_l1 = self._l1_hits + self._l1_misses
        total_l2 = self._l2_hits + self._l2_misses
        return {
            "l1_hits": self._l1_hits,
            "l1_misses": self._l1_misses,
            "l1_hit_rate": self._l1_hits / total_l1 if total_l1 > 0 else 0.0,
            "l1_size": len(self._store),
            "l1_max_size": self._max_entries,
            "l2_hits": self._l2_hits,
            "l2_misses": self._l2_misses,
            "l2_hit_rate": self._l2_hits / total_l2 if total_l2 > 0 else 0.0,
        }
```

These statistics are available through the observability layer and can be
monitored via the `embedding_cache_size` metric in Prometheus/Grafana.

---

## Configuration

| Setting                | Default         | Description                          |
|------------------------|-----------------|--------------------------------------|
| `CACHE_L1_MAX_ENTRIES` | 200             | Maximum entries in L1 LRU cache      |
| `CACHE_L2_TTL_SECONDS` | 3600            | TTL for L2 SQLite cache entries      |
| `CACHE_DB_PATH`        | `data/cache.db` | Path to SQLite cache database        |

### Tuning Guidelines

**L1 size (`CACHE_L1_MAX_ENTRIES`)**:
- Increase for wikis with repetitive query patterns (users asking similar
  questions). 500–1000 entries uses ~10–50 MB memory depending on result size.
- Decrease if memory is constrained. Minimum useful value is ~50.

**L2 TTL (`CACHE_L2_TTL_SECONDS`)**:
- Decrease (e.g., 600s = 10 min) if wiki content changes frequently and stale
  results are problematic.
- Increase (e.g., 86400s = 24 hours) if content is relatively static and you
  want maximum cache benefit.
- Set to 0 to effectively disable L2 caching (all entries expire immediately).

**Cache path (`CACHE_DB_PATH`)**:
- In Docker, this should point to a volume-mounted path to persist across
  container restarts.
- For development, the default `data/cache.db` works fine.

---

## Cache Invalidation

There is currently no automatic cache invalidation when wiki content changes.
To clear caches:

### Clear All Caches

```bash
# L1: Restart the backend process (L1 is in-memory only)
docker compose restart backend

# L2 + Embedding: Delete the SQLite database
rm data/cache.db
# Or selectively:
sqlite3 data/cache.db "DELETE FROM search_cache;"
sqlite3 data/cache.db "DELETE FROM embedding_cache;"
```

### Future Improvements

- File-watcher based invalidation (clear cache entries when source files change)
- Webhook-triggered invalidation (clear on git push)
- Per-namespace cache clearing API endpoint

---

## Related Documentation

- [Search & Retrieval](search-and-retrieval.md) — How caching fits in the search pipeline
- [Configuration](configuration.md) — All environment variables
- [Observability](observability.md) — Cache metrics
