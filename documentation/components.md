# Components Reference

This document describes every module in the backend, its responsibilities,
key classes/functions, and how it interacts with other components.

---

## Table of Contents

- [main.py — FastAPI Application](#mainpy--fastapi-application)
- [agent.py — LangGraph Agent](#agentpy--langgraph-agent)
- [security.py — Settings, JWT & Auth](#securitypy--settings-jwt--auth)
- [proposals.py — Document Change Proposals](#proposalspy--document-change-proposals)
- [git_workflow.py — Git Operations](#git_workflowpy--git-operations)
- [search/ — Search Package](#search--search-package)
- [context_engine/ — Context Assembly](#context_engine--context-assembly)
- [memory/ — Conversational Memory](#memory--conversational-memory)
- [observability/ — Telemetry](#observability--telemetry)

---

## main.py — FastAPI Application

**Purpose**: Entry point for the backend. Defines all HTTP endpoints, CORS
middleware, lifespan events, and request/response handling.

### Endpoints

| Method | Path                    | Auth     | Description                          |
|--------|-------------------------|----------|--------------------------------------|
| GET    | `/health`               | No       | Returns `{"status": "ok", "environment": "..."}` |
| POST   | `/login`                | No       | Authenticates user, returns JWT      |
| POST   | `/chat`                 | JWT      | Synchronous chat, returns `{"reply": "..."}` |
| POST   | `/chat/stream`          | JWT      | Streaming NDJSON events              |
| GET    | `/proposals/{id}`       | JWT      | Get proposal details                 |
| POST   | `/proposals/{id}/approve` | JWT    | Approve proposal, trigger git workflow |
| POST   | `/proposals/{id}/reject`  | JWT    | Reject proposal                      |

### Request Models

```python
class ChatRequest:
    query: str           # User's question
    history: list        # Previous conversation turns
    model: str           # (Optional) Model override
    page_context: str    # (Optional) Current wiki page URL
```

### Streaming Protocol

The `/chat/stream` endpoint returns newline-delimited JSON (NDJSON). Each line
is a JSON object with a `type` field:

```json
{"type": "token", "content": "The agent "}
{"type": "token", "content": "uses "}
{"type": "tool_call", "name": "search_knowledge_base", "args": {"query": "agent architecture"}}
{"type": "citations", "sources": [{"title": "...", "path": "...", "section": "..."}]}
{"type": "done"}
```

On error:
```json
{"type": "error", "message": "Internal server error"}
```

### Lifespan Events

- **Startup**: Initializes OTEL tracing/metrics, warms up search indexes, loads
  embedding cache.
- **Shutdown**: Flushes OTEL spans, closes database connections.

---

## agent.py — LangGraph Agent

**Purpose**: Core intelligence layer. Defines the LangGraph ReAct agent, all
five tools, model routing logic, and the system prompt. This is the largest
module at approximately 725 lines.

### Agent Creation

Uses `create_react_agent` from LangGraph to build a tool-calling agent. The
agent follows the ReAct (Reason + Act) pattern:

1. LLM receives the message history and decides whether to call a tool
2. If a tool is called, the result is fed back to the LLM
3. The loop continues until the LLM produces a final text response

### Tools

#### `search_knowledge_base(query: str, scope: str) → str`

Primary search tool. Delegates to the Search Orchestrator to perform hybrid
search across wiki and code documents.

- `query`: Natural language search query
- `scope`: (Optional) Namespace to restrict search to
- Returns: Formatted search results with titles, paths, sections, and snippets

#### `read_workspace_file(path: str) → str`

Reads a file from the wiki workspace (the `docs/` or `site/` directories
mounted into the container).

- `path`: Relative file path
- Returns: File content (truncated to `READ_CODE_DEFAULT_LINES`, default 50)

#### `read_source_file(path: str, start_line: int, end_line: int) → str`

Reads source code files with line-range support.

- `path`: File path relative to the workspace
- `start_line`: (Optional) Starting line number
- `end_line`: (Optional) Ending line number
- Returns: File content with line numbers, limited to `READ_CODE_MAX_SYMBOL_LINES` (default 100)

#### `list_wiki_pages(namespace: str) → str`

Lists available markdown files in a given wiki namespace.

- `namespace`: One of the registered namespaces
- Returns: Newline-separated list of `.md` file paths

#### `propose_doc_change(path: str, description: str, content: str) → str`

Creates a documentation change proposal that can later be approved or rejected.

- `path`: Target file path
- `description`: Human-readable description of the change
- `content`: Proposed new content
- Returns: Proposal ID and confirmation message

### Model Routing

The agent routes LLM calls through the `ChatOpenAI` adapter by varying the
`base_url` parameter. Model selection logic:

```
1. If request specifies a model explicitly → use that model
2. If OLLAMA_CHAT_URL is set → route to that URL
3. Otherwise → use OLLAMA_BASE_URL + "/v1" as OpenAI-compatible endpoint
```

Supported providers (all via ChatOpenAI adapter):

| Provider   | Configuration                                  |
|------------|------------------------------------------------|
| Ollama     | `base_url = OLLAMA_BASE_URL + "/v1"`           |
| OpenAI     | `base_url = "https://api.openai.com/v1"`       |
| DeepSeek   | `base_url = "https://api.deepseek.com/v1"`     |
| Qwen       | Provider-specific URL                          |

### System Prompt

The system prompt defines the agent's persona and behavior:

- Role: "You are a knowledgeable wiki assistant"
- Instructions: Always search before answering, cite sources, stay grounded
  in retrieved content, propose changes when appropriate
- Namespace awareness: Informed of the current wiki namespace from page_context
- Memory context: Top-5 relevant memories appended dynamically

---

## security.py — Settings, JWT & Auth

**Purpose**: Central configuration (Pydantic `BaseSettings`), JWT token
creation/validation, and authentication helpers.

### Settings Class

Uses Pydantic `BaseSettings` to load configuration from environment variables
with sensible defaults. All settings are documented in
[configuration.md](configuration.md).

Key groups:
- **Auth**: `APP_ADMIN_USERNAME`, `APP_ADMIN_PASSWORD`, `APP_MFA_SECRET`
- **JWT**: `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`
- **LLM**: `OLLAMA_BASE_URL`, `OLLAMA_CHAT_MODEL`, `OLLAMA_CHAT_URL`
- **Embeddings**: `OLLAMA_EMBED_MODEL`, `EMBEDDING_DIMENSIONS`, `EMBEDDING_PROVIDER`
- **Search**: `SEARCH_MAX_RESULTS`, `SEARCH_MAX_CHARS`, `SEARCH_RESULT_MAX_CHARS`
- **Cache**: `CACHE_L1_MAX_ENTRIES`, `CACHE_L2_TTL_SECONDS`, `CACHE_DB_PATH`
- **Context**: `CONTEXT_BUDGET_*_PCT`, `MAX_HISTORY_TURNS`, `COMPACTOR_PROTECTED_TURNS`
- **Memory**: `MEMORY_DB_PATH`, `MEMORY_MAX_ITEMS`
- **Observability**: `OTEL_OTEL_ENDPOINT`, `OTEL_ENABLED`
- **Publishing**: `PUBLISH_REPO_DIR`, `GITHUB_TOKEN`, `PUBLISH_REPO`

### JWT Functions

```python
def create_access_token(data: dict) -> str:
    """Create a JWT token with expiry."""

def verify_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
```

### Authentication Flow

1. Client sends `POST /login` with `{"username", "password", "totp"}`
2. `security.py` compares credentials against `APP_ADMIN_USERNAME` / `APP_ADMIN_PASSWORD`
3. If `APP_MFA_SECRET` is set, validates the TOTP code
4. On success, returns a JWT token signed with `JWT_SECRET_KEY` (HS256)
5. Subsequent requests include `Authorization: Bearer <token>`

---

## proposals.py — Document Change Proposals

**Purpose**: Manages the lifecycle of documentation change proposals. When the
agent determines that wiki content should be updated, it creates a proposal
via the `propose_doc_change` tool.

### Proposal Lifecycle

```
Created → Pending Review → Approved → Git Workflow Executed
                         → Rejected
```

### Data Model

Each proposal contains:
- `id`: Unique identifier
- `path`: Target file path
- `description`: Human-readable change description
- `content`: Proposed new content
- `status`: pending / approved / rejected
- `created_at`: Timestamp
- `reviewed_at`: (Optional) When reviewed

### API

- `POST /proposals/{id}/approve` — Marks as approved, triggers `git_workflow.py`
- `POST /proposals/{id}/reject` — Marks as rejected

---

## git_workflow.py — Git Operations

**Purpose**: Executes git operations when a proposal is approved. Creates a
branch, commits the change, and optionally pushes to a remote repository.

### Workflow

1. Checkout a new branch: `proposal/<id>`
2. Write the proposed content to the target file
3. Stage and commit with a descriptive message
4. If `GITHUB_TOKEN` and `PUBLISH_REPO` are set, push the branch
5. Optionally create a pull request

### Configuration

- `PUBLISH_REPO_DIR`: Local path to the git repository
- `GITHUB_TOKEN`: Token for pushing to GitHub
- `PUBLISH_REPO`: Remote repository reference (e.g., `owner/repo`)

---

## search/ — Search Package

The search package contains 10 modules that implement the hybrid search
pipeline.

### search/orchestrator.py — Search Orchestrator

**Purpose**: Central coordinator for all search operations. Classifies queries,
dispatches to backends in parallel, deduplicates, and reranks results.

Key responsibilities:
- Query classification (symbol / concept / exact) via regex patterns
- Cache lookup (L1 → L2)
- Repo targeting from page_context URL
- Parallel dispatch to search backends
- Deduplication by `file_path:section`
- Jaccard reranking
- Result trimming to `SEARCH_MAX_RESULTS`
- Cache storage (L1 + L2)

### search/lexical.py — Ripgrep Lexical Search

**Purpose**: Full-text search using ripgrep (`rg`) subprocess calls. Serves as
a fast fallback when Meilisearch is unavailable.

Features:
- Case-insensitive pattern matching
- Respects `.gitignore` patterns
- Returns file path, line number, and matching content
- Configurable result limits

### search/semantic.py — ChromaDB Semantic Search

**Purpose**: Vector similarity search using ChromaDB. Used for concept queries
where keyword matching is insufficient.

Features:
- Embeds queries using `nomic-embed-text` (768 dimensions)
- Queries ChromaDB collections for nearest neighbors
- Returns documents with similarity scores
- Supports namespace-scoped collections

### search/meilisearch_client.py — Meilisearch Client

**Purpose**: Primary search backend. Combines BM25 keyword ranking with vector
similarity for hybrid search.

Features:
- BM25 text search for keyword relevance
- Vector search using the experimental vector store
- Hybrid mode: combines BM25 and vector scores
- Indexes: `wiki_docs` (markdown content) and `code_docs` (source code)
- Configurable result limits and score thresholds

### search/reranker.py — Jaccard Reranker

**Purpose**: Reranks search results using a weighted combination of the original
search score, Jaccard similarity with the query, and recency.

Formula:
```
final_score = search_score × 0.6 + jaccard_similarity × 0.3 + recency_score × 0.1
```

- `search_score`: Normalized score from the search backend (0.0–1.0)
- `jaccard_similarity`: Token-level Jaccard between query and result text
- `recency_score`: Bonus for recently modified documents

### search/cache.py — Search Cache

**Purpose**: Two-level cache for search results.

- **L1**: In-memory `OrderedDict` LRU with 200 entries max
- **L2**: SQLite database with TTL-based expiration (3600 seconds)
- Cache key: `SHA256(query + ":" + scope)`

See [caching.md](caching.md) for full details.

### search/embedding_cache.py — Embedding Cache

**Purpose**: SQLite cache for embedding vectors. Since embeddings for the same
text are deterministic, entries never expire.

- Key: SHA256 hash of the input text
- Value: Serialized 768-dimension float vector
- No TTL (immutable)

### search/indexer.py — Document Indexer

**Purpose**: Indexes documents into Meilisearch and ChromaDB. Processes
markdown and source files, chunks them, generates embeddings, and upserts
into the search backends.

Responsibilities:
- Walks wiki directories for markdown files
- Walks source directories for code files
- Chunks documents using `chunker.py`
- Generates embeddings via Ollama
- Upserts to Meilisearch indexes (`wiki_docs`, `code_docs`)
- Upserts to ChromaDB collections

### search/symbols.py — Symbol Search

**Purpose**: Extracts and searches for code symbols (classes, functions,
methods) from source files. Used for symbol-type queries.

Features:
- Regex-based extraction of Python class/function definitions
- Matches symbol names against search query
- Returns symbol name, file path, line number, and surrounding context
- Limited to `READ_CODE_MAX_SYMBOL_LINES` (default 100) lines per result

### search/registry.py — Repo Registry

**Purpose**: Maps wiki namespaces to content directories and resolves page
URLs to namespaces.

```python
# Example registry entries
{
    "claude-code":   {"path": "claude_code/",   "type": "wiki"},
    "deepagents":    {"path": "deepagents/",    "type": "wiki"},
    "opencode":      {"path": "opencode/",      "type": "wiki"},
    "openclaw":      {"path": "openclaw/",      "type": "wiki"},
    "autogen":       {"path": "autogen/",       "type": "wiki"},
    "hermes-agent":  {"path": "hermes-agent/",  "type": "wiki"},
}
```

Functions:
- `resolve_namespace(page_url: str) → str`: Extracts namespace from URL path
- `get_repo_path(namespace: str) → str`: Returns filesystem path for namespace
- `list_namespaces() → list[str]`: Returns all registered namespaces

### search/chunker.py — Document Chunker

**Purpose**: Splits documents into chunks suitable for indexing and embedding.

Strategy:
- Markdown files: Split on headings (H1–H4), preserving heading hierarchy
- Code files: Split on class/function boundaries
- Each chunk includes metadata: source path, section title, line range
- Chunk size optimized for the 768-dimension embedding model

---

## context_engine/ — Context Assembly

The context engine manages the token budget and assembles the final message
list sent to the LLM.

### context_engine/engine.py — Context Engine

**Purpose**: Main orchestrator for context assembly. Coordinates the budget
calculator, memory retrieval, history compaction, and final message
construction.

```python
class ContextEngine:
    def assemble(
        self,
        system_prompt: str,
        history: list,
        user_query: str,
        memories: list,
        search_results: list
    ) -> dict:
        """
        Returns:
            {
                "messages": [...],       # Final message list for LLM
                "total_tokens": int,     # Estimated total tokens
                "budget_summary": {...}  # Per-category token usage
            }
        """
```

Assembly pipeline:
1. Calculate token budget using `budget.py`
2. Query memory for relevant facts
3. Build system prompt with injected memories
4. Compact history if it exceeds the history budget
5. Construct final message list: `[system, ...compacted_history, user_query]`
6. Return messages with token count and budget summary

### context_engine/budget.py — Token Budget

**Purpose**: Calculates token allocation across six categories for a 128K
context window.

| Category   | Percentage | Tokens (of 128K) | Purpose                         |
|------------|-----------|-------------------|----------------------------------|
| System     | 3%        | ~3,840            | System prompt                    |
| Memory     | 5%        | ~6,400            | Injected memories                |
| History    | 35%       | ~44,800           | Conversation history             |
| Search     | 25%       | ~32,000           | Search results in tool responses |
| Output     | 30%       | ~38,400           | Reserved for LLM generation      |
| Safety     | 2%        | ~2,560            | Buffer for tokenization variance |

### context_engine/compactor.py — History Compactor

**Purpose**: Prunes conversation history when it exceeds the token budget.

Strategy:
- Protects the most recent `COMPACTOR_PROTECTED_TURNS` turns (default: 4)
- For older turns: removes tool output content (replaces with summary)
- Triggers when history exceeds 50% of the history budget
- Preserves user/assistant message text, only truncates tool results

---

## memory/ — Conversational Memory

### memory/base.py — Memory Interface

**Purpose**: Abstract base class defining the memory interface.

```python
class BaseMemory(ABC):
    async def store(self, key: str, content: str, metadata: dict) -> None: ...
    async def recall(self, query: str, limit: int = 5) -> list[dict]: ...
    async def forget(self, key: str) -> None: ...
    async def count(self) -> int: ...
```

### memory/sqlite_memory.py — SQLite FTS5 Memory

**Purpose**: Concrete implementation using SQLite with FTS5 (Full-Text Search 5)
extension for keyword-based memory recall.

Features:
- FTS5 virtual table for fast full-text search
- Stores memories as key-value pairs with metadata (timestamp, source, etc.)
- `recall()` uses FTS5 `MATCH` queries, ranked by BM25
- Maximum capacity: `MEMORY_MAX_ITEMS` (default 1000), oldest evicted
- Database path: `MEMORY_DB_PATH` (default `data/memory.db`)

Usage in agent:
1. After each conversation turn, relevant facts are extracted and stored
2. Before each new query, the context engine recalls top-5 memories matching
   the user's query
3. Retrieved memories are injected into the system prompt

---

## observability/ — Telemetry

### observability/config.py — Configuration

**Purpose**: Observability configuration and initialization.

- `OTEL_ENABLED`: Master toggle (default: true)
- `OTEL_OTEL_ENDPOINT`: OTLP gRPC endpoint (default: `http://localhost:4317`)

### observability/tracing.py — Tracing

**Purpose**: Configures the OpenTelemetry `TracerProvider` with a
`BatchSpanProcessor` that exports spans via OTLP gRPC.

Span hierarchy for a typical request:
```
http_request (FastAPI)
  └── agent_run (LangGraph)
       ├── tool_call: search_knowledge_base
       │    ├── cache_lookup
       │    ├── meilisearch_search
       │    ├── chromadb_search
       │    ├── rerank
       │    └── cache_store
       ├── tool_call: read_workspace_file
       └── llm_call
            └── token_streaming
```

### observability/metrics.py — Metrics

**Purpose**: Defines OTEL meters, counters, and histograms exported via
the PeriodicExportingMetricReader (15-second interval).

See [observability.md](observability.md) for the complete list of 13 metrics.

### observability/tokens.py — Token Counting

**Purpose**: Utilities for counting tokens in messages, tool results, and
LLM responses. Used by the context engine for budget calculations and by
the trace store for recording token usage.

### observability/trace_store.py — Request Trace Store

**Purpose**: SQLite database that stores per-request summaries for audit
and debugging. Each row captures 19 fields covering the full request lifecycle.

See [observability.md](observability.md) for the complete schema.

---

## Module Dependency Graph

```
main.py
  ├── agent.py
  │     ├── search/orchestrator.py
  │     │     ├── search/meilisearch_client.py
  │     │     ├── search/semantic.py
  │     │     ├── search/lexical.py
  │     │     ├── search/symbols.py
  │     │     ├── search/reranker.py
  │     │     ├── search/cache.py
  │     │     ├── search/embedding_cache.py
  │     │     └── search/registry.py
  │     ├── context_engine/engine.py
  │     │     ├── context_engine/budget.py
  │     │     └── context_engine/compactor.py
  │     ├── memory/sqlite_memory.py
  │     │     └── memory/base.py
  │     └── proposals.py
  │           └── git_workflow.py
  ├── security.py
  └── observability/
        ├── tracing.py
        ├── metrics.py
        ├── tokens.py
        ├── trace_store.py
        └── config.py
```

---

## Related Documentation

- [System Architecture](system-architecture.md) — How components interact
- [Search & Retrieval](search-and-retrieval.md) — Full search pipeline
- [Configuration](configuration.md) — All environment variables
