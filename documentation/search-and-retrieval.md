# Search & Retrieval Pipeline

This document describes the complete search pipeline from query ingestion to
formatted results. The search system is the backbone of the wiki agent — every
answer the agent provides is grounded in search results.

---

## Pipeline Overview

```
User Query
    │
    ▼
┌───────────────────────┐
│  1. Query Classification │ ← Regex-based: symbol / concept / exact
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  2. Cache Lookup        │ ← L1 LRU → L2 SQLite
│     Key = SHA256(q:s)   │     Hit? → Return cached results
└───────────┬───────────┘
            │ Cache miss
            ▼
┌───────────────────────┐
│  3. Repo Targeting      │ ← Registry maps page_url → namespace
│     Scope resolution    │     Determines which dirs to search
└───────────┬───────────┘
            │
            ▼
┌───────────────────────────────────────────────────────────┐
│  4. Parallel Search Dispatch                                │
│                                                             │
│  ┌─────────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Meilisearch     │  │  ChromaDB     │  │  Ripgrep     │  │
│  │  BM25 + Vector   │  │  Semantic     │  │  Lexical     │  │
│  │  (wiki + code)   │  │  (concept     │  │  (fallback)  │  │
│  │                  │  │   queries)    │  │              │  │
│  └────────┬────────┘  └──────┬───────┘  └──────┬───────┘  │
│           │                   │                  │          │
│  ┌────────┴───────────────────┴──────────────────┘         │
│  │  Symbol Search (symbol queries only)                     │
│  └─────────────┬───────────────────────────────────────────│
│                │                                             │
└────────────────┼─────────────────────────────────────────────┘
                 │
                 ▼
┌───────────────────────┐
│  5. Deduplication       │ ← By file_path:section composite key
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  6. Jaccard Reranking   │ ← Weighted: search×0.6 + jaccard×0.3 + recency×0.1
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  7. Result Trimming     │ ← Max SEARCH_MAX_RESULTS (default 8)
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  8. Cache Storage       │ ← Store in L1 + L2
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  9. Format & Return     │ ← Structured text for agent consumption
└───────────────────────┘
```

---

## Step 1: Query Classification

The orchestrator classifies each query to determine which search backends to
invoke. Classification is regex-based for speed.

### Query Types

| Type       | Pattern Examples                                  | Backends Used                     |
|------------|---------------------------------------------------|------------------------------------|
| `symbol`   | `class MyClass`, `def func`, `function foo`, CamelCase identifiers | Meilisearch + Symbol search       |
| `concept`  | "how does X work", "explain Y", "what is Z"      | Meilisearch + ChromaDB semantic   |
| `exact`    | Quoted strings, file paths, specific identifiers  | Meilisearch + Ripgrep lexical     |

### Classification Rules

```python
def classify_query(query: str) -> str:
    # Symbol patterns: class/def/function keywords, CamelCase, snake_case with parens
    if re.search(r'\b(class|def|function|func)\s+\w+', query):
        return "symbol"
    if re.search(r'\b[A-Z][a-z]+[A-Z]\w+', query):  # CamelCase
        return "symbol"

    # Exact patterns: quoted strings, file paths, specific tokens
    if re.search(r'["\'].*["\']', query):
        return "exact"
    if re.search(r'\w+\.\w+', query) and '/' in query:  # file paths
        return "exact"

    # Default: concept
    return "concept"
```

---

## Step 2: Cache Lookup

Before executing any search, the orchestrator checks the two-level cache.

### Cache Key Generation

```python
import hashlib
cache_key = hashlib.sha256(f"{query}:{scope}".encode()).hexdigest()
```

The key includes both the query text and the scope (namespace) to prevent
cross-namespace cache hits.

### Lookup Order

1. **L1 (in-memory LRU)**: `OrderedDict` with 200 entries max. Sub-millisecond
   lookup. On hit, the entry is moved to the end (most recently used).

2. **L2 (SQLite)**: On L1 miss, checks SQLite. Entries have a TTL of 3600
   seconds (1 hour). On L2 hit, the result is also promoted to L1.

3. **Cache miss**: Proceed to repo targeting and search dispatch.

See [caching.md](caching.md) for full cache architecture details.

---

## Step 3: Repo Targeting

The registry maps the user's current page URL to a wiki namespace, which
determines which content directories to search.

### Resolution Logic

```python
def resolve_namespace(page_url: str) -> str:
    """
    Extract namespace from page URL.
    Example: "/claude-code/overview/" → "claude-code"
             "/deepagents/concepts/" → "deepagents"
    """
    parts = page_url.strip("/").split("/")
    if parts and parts[0] in REGISTERED_NAMESPACES:
        return parts[0]
    return None  # Search all namespaces
```

### Namespace-to-Path Mapping

| Namespace       | Content Directory    |
|-----------------|----------------------|
| `claude-code`   | `claude_code/`       |
| `deepagents`    | `deepagents/`        |
| `opencode`      | `opencode/`          |
| `openclaw`      | `openclaw/`          |
| `autogen`       | `autogen/`           |
| `hermes-agent`  | `hermes-agent/`      |

When a namespace is resolved, search is scoped to that directory first. If too
few results are found, cross-namespace fallback may be used.

---

## Step 4: Parallel Search Dispatch

The orchestrator dispatches to multiple search backends concurrently based on
the query classification.

### Meilisearch (BM25 + Vector)

**Primary search backend.** Used for all query types.

#### Indexes

| Index        | Content                              | Fields                                 |
|--------------|--------------------------------------|----------------------------------------|
| `wiki_docs`  | Markdown wiki content                | title, content, path, section, namespace |
| `code_docs`  | Source code files                    | content, path, language, symbols       |

#### Search Modes

- **BM25**: Traditional keyword ranking. Fast, precise for exact terms.
- **Vector**: Semantic similarity using embedded query vectors.
- **Hybrid**: Combines BM25 and vector scores for best-of-both results.

#### Query Flow

```python
async def search_meilisearch(query: str, scope: str, query_type: str) -> list:
    embedding = await get_embedding(query)  # 768-dim via Ollama

    results = await meilisearch.multi_search([
        {
            "indexUid": "wiki_docs",
            "q": query,
            "vector": embedding,
            "hybrid": {"semanticRatio": 0.5},  # Balance BM25 and vector
            "filter": f"namespace = '{scope}'" if scope else None,
            "limit": SEARCH_MAX_RESULTS,
        },
        {
            "indexUid": "code_docs",
            "q": query,
            "vector": embedding,
            "hybrid": {"semanticRatio": 0.3},  # Favor keyword for code
            "filter": f"namespace = '{scope}'" if scope else None,
            "limit": SEARCH_MAX_RESULTS,
        },
    ])
    return normalize_results(results)
```

### ChromaDB Semantic Search

**Used for concept queries only.** Pure vector similarity search for queries
where keyword matching is insufficient (e.g., "how does the agent decide which
tool to use?").

```python
async def search_chromadb(query: str, scope: str) -> list:
    embedding = await get_embedding(query)
    collection = chromadb_client.get_collection(scope or "all")
    results = collection.query(
        query_embeddings=[embedding],
        n_results=SEARCH_MAX_RESULTS,
    )
    return normalize_results(results)
```

### Ripgrep Lexical Search

**Used for exact queries and as a fallback** when Meilisearch is unavailable.

```python
async def search_ripgrep(query: str, scope: str) -> list:
    target_dir = get_repo_path(scope) if scope else "."
    result = await asyncio.subprocess.create_subprocess_exec(
        "rg", "--json", "--max-count", "20",
        "--ignore-case", query, target_dir,
        stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await result.communicate()
    return parse_ripgrep_json(stdout)
```

Features:
- Case-insensitive matching
- Respects `.gitignore`
- JSON output for structured parsing
- Configurable max result count

### Symbol Search

**Used for symbol queries only.** Extracts code symbols (class/function names)
and matches against the query.

```python
async def search_symbols(query: str, scope: str) -> list:
    # Extract symbol name from query
    symbol = extract_symbol_name(query)

    # Search indexed symbols
    matches = symbol_index.search(symbol, scope=scope)

    # Return with surrounding context
    return [
        {
            "path": m.path,
            "symbol": m.name,
            "type": m.type,  # "class", "function", "method"
            "line": m.line,
            "context": read_context(m.path, m.line, READ_CODE_MAX_SYMBOL_LINES),
        }
        for m in matches
    ]
```

---

## Step 5: Deduplication

Results from multiple backends often overlap. The orchestrator deduplicates
by composite key `file_path:section`.

```python
def deduplicate(results: list) -> list:
    seen = set()
    unique = []
    for r in results:
        key = f"{r['path']}:{r.get('section', '')}"
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique
```

When duplicates are found, the result with the highest search score is kept.

---

## Step 6: Jaccard Reranking

After deduplication, results are reranked using a weighted formula that
combines the original search score with Jaccard similarity and recency.

### Formula

```
final_score = search_score × 0.6 + jaccard_similarity × 0.3 + recency_score × 0.1
```

### Components

**search_score (weight: 0.6)**

The normalized score from the search backend (Meilisearch, ChromaDB, or
ripgrep). Normalized to the range [0.0, 1.0].

**jaccard_similarity (weight: 0.3)**

Token-level Jaccard similarity between the query and the result text:

```python
def jaccard_similarity(query: str, text: str) -> float:
    query_tokens = set(query.lower().split())
    text_tokens = set(text.lower().split())
    intersection = query_tokens & text_tokens
    union = query_tokens | text_tokens
    return len(intersection) / len(union) if union else 0.0
```

This captures keyword overlap that pure vector similarity might miss.

**recency_score (weight: 0.1)**

A bonus for recently modified documents, calculated from the file's last
modification timestamp. More recently modified files get a higher score.

```python
def recency_score(modified_at: datetime) -> float:
    age_days = (datetime.now() - modified_at).days
    return max(0.0, 1.0 - (age_days / 365.0))  # Linear decay over 1 year
```

---

## Step 7: Result Trimming

After reranking, results are trimmed to `SEARCH_MAX_RESULTS` (default 8).

Each result's content is also truncated to `SEARCH_RESULT_MAX_CHARS`
(default 200 characters) for the formatted output, while the full content
is retained internally for the agent's `read_workspace_file` tool to access.

---

## Step 8: Cache Storage

Successful search results are stored in both cache levels:

1. **L1**: Added to the in-memory LRU. If the cache is at capacity (200
   entries), the least recently used entry is evicted.

2. **L2**: Inserted into SQLite with the current timestamp. On next access,
   entries older than `CACHE_L2_TTL_SECONDS` (3600s) will be treated as misses
   and re-searched.

---

## Step 9: Format & Return

Results are formatted into a structured text format for the agent to consume:

```python
def format_results(results: list) -> str:
    formatted = []
    for i, r in enumerate(results, 1):
        formatted.append(
            f"[{i}] {r['title']}\n"
            f"    Path: {r['path']}\n"
            f"    Section: {r.get('section', 'N/A')}\n"
            f"    Score: {r['score']:.3f}\n"
            f"    {r['snippet'][:SEARCH_RESULT_MAX_CHARS]}\n"
        )
    return "\n".join(formatted)
```

Example output:
```
[1] Agent Architecture
    Path: claude_code/agent-overview.md
    Section: Tool Execution
    Score: 0.847
    The agent uses a ReAct loop to decide which tools to invoke...

[2] Search Pipeline
    Path: documentation/search-and-retrieval.md
    Section: Overview
    Score: 0.723
    The search system combines Meilisearch BM25+vector with ChromaDB...
```

---

## Embedding Pipeline

All vector operations use the same embedding model and cache.

### Model

- **Provider**: Ollama
- **Model**: `nomic-embed-text`
- **Dimensions**: 768
- **Endpoint**: `OLLAMA_BASE_URL/api/embeddings`

### Embedding Flow

```
Query text
    │
    ▼
SHA256 hash ──► Embedding cache lookup (SQLite)
    │               │
    │ Cache miss     │ Cache hit
    │               ▼
    ▼           Return cached vector
Ollama API call
    │
    ▼
768-dim vector
    │
    ├──► Store in embedding cache
    └──► Return vector
```

### Cache Behavior

Embedding vectors are cached in SQLite with no TTL:
- Same text always produces the same embedding
- Cache key: `SHA256(text)`
- Cache eliminates redundant API calls to Ollama
- Persists across backend restarts

---

## Configuration Reference

| Setting                  | Default | Description                              |
|--------------------------|---------|------------------------------------------|
| `SEARCH_MAX_RESULTS`     | 8       | Maximum results returned per search      |
| `SEARCH_MAX_CHARS`       | 2000    | Maximum total characters in formatted results |
| `SEARCH_RESULT_MAX_CHARS`| 200     | Maximum characters per result snippet    |
| `MEILISEARCH_URL`        | `http://localhost:7700` | Meilisearch server URL      |
| `MEILISEARCH_API_KEY`    | `""`    | Meilisearch API key (if set)             |
| `OLLAMA_BASE_URL`        | `http://localhost:11434` | Ollama server URL           |
| `OLLAMA_EMBED_MODEL`     | `nomic-embed-text` | Embedding model name            |
| `EMBEDDING_DIMENSIONS`   | 768     | Embedding vector dimensions              |
| `EMBEDDING_PROVIDER`     | `ollama`| Embedding provider                       |
| `READ_CODE_DEFAULT_LINES`| 50      | Default lines to read from files         |
| `READ_CODE_MAX_SYMBOL_LINES` | 100 | Max lines for symbol context             |

---

## Troubleshooting

### No Search Results

1. **Check Meilisearch**: `curl http://localhost:7700/health` — should return
   `{"status": "available"}`
2. **Check indexes**: `curl http://localhost:7700/indexes` — should list
   `wiki_docs` and `code_docs`
3. **Check Ollama**: `curl http://localhost:11434/api/tags` — should list
   `nomic-embed-text`
4. **Run indexer**: The indexer may need to be run to populate search indexes

### Slow Search

1. **Check cache hit rate**: If L1/L2 hit rates are low, searches hit backends
   every time. Check with the cache stats API.
2. **Meilisearch performance**: Check Meilisearch logs for slow queries.
3. **Ollama embedding latency**: Embedding generation can be slow on CPU. Check
   if Ollama has GPU access.

### Stale Results

1. **Cache TTL**: L2 cache has a 1-hour TTL. Results may be stale within that
   window. Clear the cache or reduce TTL.
2. **Re-index**: If content has changed, re-run the indexer to update
   Meilisearch and ChromaDB.

---

## Related Documentation

- [Caching](caching.md) — Full cache architecture
- [Components](components.md) — Module reference for search/ package
- [Configuration](configuration.md) — All environment variables
- [Observability](observability.md) — Search metrics and tracing
