# Session Persistence

## Overview

Session persistence allows agent conversations to survive process restarts by checkpointing the full graph state between steps. Two backends implement persistent storage from different angles: `FilesystemBackend` writes agent-visible files directly to local disk, and `StoreBackend` stores agent-visible files in LangGraph's `BaseStore` for persistent, cross-thread access. Separately, the `checkpointer` parameter in `create_deep_agent()` controls LangGraph's own graph-state checkpointing (messages, tool call history, and in-flight state), which is what enables a session to be resumed by thread ID after a process restart.

These two concerns — file storage persistence and graph-state checkpointing — are distinct but complementary. A typical long-running CLI session uses a LangGraph `checkpointer` for state resumption and `FilesystemBackend` for file I/O; a server deployment might combine `StoreBackend` (cross-thread file persistence) with a database-backed LangGraph checkpointer.

---

## Key Types / Key Concepts

### `FilesystemBackend` — agent files on local disk

`FilesystemBackend` implements `BackendProtocol` and performs all file I/O (read, write, edit, ls, glob, grep) directly against the real filesystem. Files are not serialized into graph state — they exist as ordinary files on disk. This makes them implicitly persistent: files written in one session survive process restart and are visible in the next.

```python
class FilesystemBackend(BackendProtocol):
    def __init__(
        self,
        root_dir: str | Path | None = None,
        virtual_mode: bool | None = None,
        max_file_size_mb: int = 10,
    ): ...
```

- `root_dir`: Base directory for all file operations. Defaults to `cwd`. Relative paths are resolved against it.
- `virtual_mode=False` (default): Agents can reach any accessible path, including absolute paths and `..` traversal. No security boundary is enforced.
- `virtual_mode=True`: All paths are treated as virtual paths anchored to `root_dir`. Path traversal (`..`, `~`) and absolute paths outside `root_dir` raise `ValueError`. Primarily intended for `CompositeBackend` path-routing semantics, not as a process-level sandbox.
- `max_file_size_mb`: Files larger than this are skipped during grep's Python fallback search.

Content is read and written as plain text. Timestamps (`created_at`, `modified_at`) are derived from filesystem `stat()` metadata. There is no internal file format — the on-disk file is the canonical representation.

### `StoreBackend` — agent files in LangGraph's BaseStore

`StoreBackend` implements `BackendProtocol` by storing agent-visible files in LangGraph's `BaseStore`. Files persist across conversation threads (not just within a single thread's checkpoints) and are organized by namespace tuples.

```python
class StoreBackend(BackendProtocol):
    def __init__(
        self,
        store: BaseStore | None = None,
        namespace: NamespaceFactory | None = None,
        file_format: FileFormat = "v2",
    ): ...
```

- `store`: Optional `BaseStore` instance. When `None`, the store is obtained at call time via `get_store()` from the LangGraph execution context. Requires `store=my_store` to be passed to `create_deep_agent()`.
- `namespace`: A callable `(BackendContext) -> tuple[str, ...]` that returns the namespace tuple used for all store operations. Namespace components must be alphanumeric with hyphens, underscores, dots, `@`, `+`, colons, or tildes. Wildcards are rejected. Example: `lambda ctx: ("filesystem", ctx.runtime.context.user_id)`.
- `file_format`: `"v2"` (default) stores content as a plain `str` with an `encoding` field. Legacy `"v1"` stored content as `list[str]` (lines split on `\n`) and is accepted for backward compatibility.

File data is stored in the LangGraph store as items keyed by filename within the namespace. Each item's value is a dict with `content`, `encoding`, and optional `created_at`/`modified_at` ISO 8601 strings.

### `BackendContext` and `NamespaceFactory`

```python
@dataclass
class BackendContext(Generic[StateT, ContextT]):
    state: StateT
    runtime: Runtime[ContextT]

NamespaceFactory = Callable[[BackendContext[Any, Any]], tuple[str, ...]]
```

The `NamespaceFactory` gives `StoreBackend` full flexibility over namespace resolution. It is called at each store operation, receiving the current graph state and runtime context. This allows namespaces to be scoped to users, assistants, or any other runtime-derived attribute.

### `checkpointer` parameter in `create_deep_agent()`

```python
def create_deep_agent(
    ...
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    ...
) -> CompiledStateGraph: ...
```

`checkpointer` is a LangGraph `Checkpointer` instance (e.g., `MemorySaver`, `SqliteSaver`, `PostgresSaver`) that snapshots the full graph state — messages, pending tool calls, and all state channels — after each step. When a `checkpointer` is provided, any invocation that passes a `thread_id` in config can resume a previous conversation:

```python
from langgraph.checkpoint.memory import MemorySaver

agent = create_deep_agent(
    model="claude-sonnet-4-6",
    checkpointer=MemorySaver(),
)

# First run
agent.invoke({"messages": [...]}, config={"configurable": {"thread_id": "session-abc"}})

# Resume after restart — graph state is restored from the checkpointer
agent.invoke({"messages": [...]}, config={"configurable": {"thread_id": "session-abc"}})
```

`checkpointer` is passed through to LangGraph's `StateGraph.compile()` unchanged. Without a checkpointer, each invocation starts from a blank state regardless of `thread_id`.

### Session IDs and thread IDs

LangGraph identifies conversations by `thread_id` passed in the invocation config under `config["configurable"]["thread_id"]`. The thread ID is a caller-supplied string (typically a UUID). The checkpointer stores one snapshot per `(thread_id, checkpoint_ns, checkpoint_id)` tuple; the latest checkpoint for a thread is used on resume.

The CLI generates a `thread_id` UUID at session creation time, stores it in its SQLite session metadata table, and passes it on every invocation for the lifetime of that CLI session. This allows the CLI's session-resume UI to map a human-readable session name back to a LangGraph thread ID.

---

## Architecture

### Save / restore flow

```
agent.invoke(messages, config={"configurable": {"thread_id": "..."}})
  → LangGraph step loop
      → after each node: checkpointer.put(checkpoint)
      → tool calls: backend.write() / backend.edit() / ...
          FilesystemBackend → disk I/O (file persists immediately)
          StoreBackend      → store.put(namespace, key, value)
  → on next invoke with same thread_id:
      → checkpointer.get(thread_id) → restore AgentState
      → FilesystemBackend: files already on disk, no restore needed
      → StoreBackend: files fetched from store on demand per tool call
```

### What state is persisted

| Layer | Mechanism | Scope |
|---|---|---|
| Graph state (messages, tool history, state channels) | LangGraph `checkpointer` | Per thread, restored on resume |
| Agent-visible files (`FilesystemBackend`) | Filesystem — no explicit save/restore | Persist naturally on disk across all threads and restarts |
| Agent-visible files (`StoreBackend`) | LangGraph `BaseStore` per namespace | Persistent across threads; namespace-scoped |
| Agent-visible files (`StateBackend`) | LangGraph state channel `files` | Per thread only; restored via checkpointer alongside messages |

### `StoreBackend` vs `checkpointer` — two independent persistence axes

`StoreBackend` and `checkpointer` operate independently and serve different purposes. The checkpointer is about replaying graph execution from a known state. `StoreBackend` is about giving the agent access to files that outlive any single thread. Both can be used together: a checkpointer resumes the conversation; `StoreBackend` ensures that files the agent wrote in a previous thread are still readable.

---

## Source Files

| File | Purpose |
|---|---|
| `libs/deepagents/deepagents/backends/filesystem.py` | `FilesystemBackend` — direct disk I/O with optional virtual path mode and security notes |
| `libs/deepagents/deepagents/backends/store.py` | `StoreBackend`, `BackendContext`, `NamespaceFactory` — persistent cross-thread file storage via LangGraph `BaseStore` |
| `libs/deepagents/deepagents/graph.py` | `create_deep_agent()` — `checkpointer` and `store` parameters; passes both to `StateGraph.compile()` |
| `libs/deepagents/deepagents/backends/protocol.py` | `BackendProtocol`, `FileData`, and all result types shared by both backends |

---

## See Also

- [Backend System](backend-system.md)
- [Graph Factory](graph-factory.md)
- [Filesystem First Agent Configuration](../concepts/filesystem-first-agent-configuration.md)
