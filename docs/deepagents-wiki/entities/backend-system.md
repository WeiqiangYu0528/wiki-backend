# Backend System

## Overview

The backend system abstracts file storage and (optionally) shell command execution behind a uniform interface. It is what allows the same agent graph to operate over in-memory conversation state, the local filesystem, an isolated sandbox, a persistent cross-thread store, or routed combinations of all of the above.

Backends are not just storage plumbing. They determine what the agent can see, write, and execute. Every built-in file tool (`ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute`) delegates its actual I/O to the backend that was passed to `create_deep_agent()`. Swapping the backend changes the agent's view of the world without touching middleware or graph structure.

This page should be read alongside [Graph Factory](graph-factory.md) (how a backend is threaded into the graph), [CLI Runtime](cli-runtime.md) (how the CLI selects a backend), and [Local vs Remote Execution](../concepts/local-vs-remote-execution.md) (the design rationale for sandboxed vs. unsandboxed backends).

---

## Key Types / Key Concepts

### `BackendProtocol` — the base interface

All backends inherit from `BackendProtocol` (an abstract base class in `protocol.py`). The interface defines both sync and async versions of every file operation. The async variants default to `asyncio.to_thread(sync_version)` and may be overridden for native async backends.

```python
class BackendProtocol(abc.ABC):
    # Directory listing
    def ls(self, path: str) -> LsResult: ...
    async def als(self, path: str) -> LsResult: ...

    # File reading (windowed by offset/limit)
    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult: ...
    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult: ...

    # Content search
    def grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult: ...
    async def agrep(...) -> GrepResult: ...

    # Glob pattern matching
    def glob(self, pattern: str, path: str = "/") -> GlobResult: ...
    async def aglob(...) -> GlobResult: ...

    # File creation (errors if file already exists)
    def write(self, file_path: str, content: str) -> WriteResult: ...
    async def awrite(...) -> WriteResult: ...

    # In-place string replacement
    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult: ...
    async def aedit(...) -> EditResult: ...

    # Batch file transfer
    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]: ...
    async def aupload_files(...) -> list[FileUploadResponse]: ...
    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]: ...
    async def adownload_files(...) -> list[FileDownloadResponse]: ...
```

All read/write/edit/ls/glob/grep methods return structured result objects (see Result types below) rather than raising exceptions on failure.

### `SandboxBackendProtocol` — execution extension

Backends that support shell command execution extend `SandboxBackendProtocol`:

```python
class SandboxBackendProtocol(BackendProtocol):
    @property
    def id(self) -> str: ...  # Unique backend instance identifier

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse: ...
    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse: ...
```

The `execute` tool exposed to the agent calls `aexecute`. If the backend does not implement `SandboxBackendProtocol`, the `execute` tool returns an error message rather than raising — the agent sees a clean failure, not a crash.

### `BackendFactory`

```python
BackendFactory: TypeAlias = Callable[[ToolRuntime], BackendProtocol]
```

An alternative to passing a backend instance directly. A factory callable receives the `ToolRuntime` at tool-invocation time and returns the backend to use. Useful when the backend needs per-request context (e.g., resolving a user-scoped namespace).

### Result types

Every operation returns a typed result dataclass. All results carry an `error: str | None` field — `None` on success.

| Result type | Success field(s) |
|---|---|
| `ReadResult` | `file_data: FileData \| None` |
| `WriteResult` | `path: str \| None` |
| `EditResult` | `path: str \| None`, `occurrences: int \| None` |
| `LsResult` | `entries: list[FileInfo] \| None` |
| `GrepResult` | `matches: list[GrepMatch] \| None` |
| `GlobResult` | `matches: list[FileInfo] \| None` |
| `FileUploadResponse` | `path: str` (error field only) |
| `FileDownloadResponse` | `content: bytes \| None` |
| `ExecuteResponse` | `output: str`, `exit_code: int \| None`, `truncated: bool` |

### `FileData` — the on-wire file format

```python
class FileData(TypedDict):
    content: str          # UTF-8 text or base64-encoded binary
    encoding: str         # "utf-8" or "base64"
    created_at: NotRequired[str]   # ISO 8601
    modified_at: NotRequired[str]  # ISO 8601
```

The current storage format is `v2`. The legacy `v1` format stored `content` as `list[str]` (lines split on `\n`) without an `encoding` field. Backends accept `v1` for backward compatibility and emit a `DeprecationWarning`.

---

## Backend Implementations

### `StateBackend` — default, ephemeral

Files are stored in LangGraph agent state using the `files` channel. State persists within a conversation thread (checkpointed after each step) but is discarded when the thread is discarded. This is the default backend when none is specified.

```python
backend = StateBackend()  # default
agent = create_deep_agent(backend=backend)

# Pre-populate files at invoke time:
agent.invoke({"messages": [...], "files": {"/path/to/file.txt": {"content": "...", "encoding": "utf-8"}}})
```

Reads and writes go through LangGraph's `CONFIG_KEY_READ` / `CONFIG_KEY_SEND` internals so that state updates are queued as proper channel writes rather than returned as dict updates. `StateBackend` must be used inside a graph execution context — it raises `RuntimeError` if called outside.

`StateBackend` does not implement `upload_files` (raises `NotImplementedError`). Use `invoke(files={...})` to inject files before execution.

### `FilesystemBackend` — direct disk access

```python
class FilesystemBackend(BackendProtocol):
    def __init__(
        self,
        root_dir: str | Path | None = None,
        virtual_mode: bool | None = None,
        max_file_size_mb: int = 10,
    ): ...
```

Reads and writes go directly to the real filesystem. `root_dir` defaults to the current working directory. When `virtual_mode=False` (default), agents can reach any accessible path including absolute paths and `..` traversal. When `virtual_mode=True`, `root_dir` acts as a virtual root — path traversal and absolute paths outside it are blocked. Virtual mode is primarily for use with `CompositeBackend` routing, not as a security sandbox.

**Security note:** This backend grants agents direct read/write access to the local filesystem. Recommended for CLI tools and local development only. Use Human-in-the-Loop middleware with sensitive paths.

### `LocalShellBackend` — filesystem + unrestricted shell

```python
class LocalShellBackend(FilesystemBackend, SandboxBackendProtocol):
    def __init__(
        self,
        root_dir: str | Path | None = None,
        *,
        virtual_mode: bool | None = None,
        timeout: int = 120,          # seconds
        max_output_bytes: int = 100_000,
        env: dict[str, str] | None = None,
        inherit_env: bool = False,
    ): ...
```

Extends `FilesystemBackend` with shell command execution via `subprocess.run(shell=True)`. Commands execute in `root_dir` with the configured environment. Stdout and stderr are combined; stderr lines are prefixed with `[stderr]`. Output exceeding `max_output_bytes` is truncated (flagged via `ExecuteResponse.truncated`). On timeout, exit code `124` is returned.

**Security warning:** This backend provides NO sandboxing. Commands run directly on the host with the calling user's permissions. `virtual_mode` does not restrict shell execution. Appropriate for local development CLIs and trusted CI/CD environments only. Human-in-the-Loop middleware is strongly recommended.

```python
from deepagents.backends import LocalShellBackend

backend = LocalShellBackend(
    root_dir="/home/user/project",
    virtual_mode=True,
    inherit_env=True,
)
agent = create_deep_agent(backend=backend)
```

### `StoreBackend` — persistent, cross-thread

Wraps LangGraph's `BaseStore` for persistent storage that survives across conversation threads. Requires a `store` to be passed to `create_deep_agent()`. Namespace resolution is configurable via a `NamespaceFactory` callable that receives a `BackendContext` (containing the current `state` and `runtime`) and returns a namespace tuple.

```python
from deepagents.backends import StoreBackend

backend = StoreBackend(namespace=("memories", "user-123"))
agent = create_deep_agent(backend=backend, store=my_store)
```

### `LangSmithSandbox` — remote sandbox execution

Wraps a LangSmith `Sandbox` instance. Inherits file operations from `BaseSandbox` (which implements them via `execute()` shell commands). The `execute()` method delegates to the LangSmith API. Default timeout is 30 minutes.

```python
from langsmith.sandbox import Sandbox
from deepagents.backends import LangSmithSandbox

backend = LangSmithSandbox(sandbox=Sandbox(...))
agent = create_deep_agent(backend=backend)
```

### `CompositeBackend` — path-based routing

Routes file operations to different backends based on path prefixes. Paths are matched longest-prefix-first. Operations on `/` aggregate results from the default backend and all routed backends. Execution (`execute`) is always delegated to the default backend regardless of path.

```python
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

composite = CompositeBackend(
    default=StateBackend(),
    routes={
        "/memories/": StoreBackend(namespace=("memories",)),
    },
)
agent = create_deep_agent(backend=composite)
```

Writing to `/temp.txt` goes to `StateBackend`; writing to `/memories/note.md` is routed to `StoreBackend` with the path stripped to `/note.md`. When `ls("/")` is called, results from the default backend are merged with a synthetic directory entry for each route prefix.

For `grep` and `glob`, `CompositeBackend` fans out to all backends when the search path is `/` or `None`, and remaps result paths back to their full composite paths.

---

## How Backends Plug into `create_deep_agent()`

The `backend` parameter accepts either a `BackendProtocol` instance or a `BackendFactory` callable:

```python
# Instance — reused for all tool calls
agent = create_deep_agent(backend=LocalShellBackend(root_dir="/project"))

# Factory — called once per tool invocation with the ToolRuntime
agent = create_deep_agent(backend=lambda runtime: StateBackend())
```

When `backend=None`, `StateBackend()` is constructed and used as the default.

The backend instance is passed to `FilesystemMiddleware`, `SubAgentMiddleware`, `SkillsMiddleware`, `MemoryMiddleware`, and `create_summarization_middleware` during stack assembly. Each middleware holds a reference to the same backend instance, so all file operations within a single agent invocation share the same storage context.

---

## Source Files

| File | Purpose |
|---|---|
| `libs/deepagents/deepagents/backends/protocol.py` | `BackendProtocol`, `SandboxBackendProtocol`, `BackendFactory`, all result types (`ReadResult`, `WriteResult`, `EditResult`, `LsResult`, `GrepResult`, `GlobResult`, `ExecuteResponse`, `FileData`, `FileInfo`, `GrepMatch`, `FileUploadResponse`, `FileDownloadResponse`) |
| `libs/deepagents/deepagents/backends/state.py` | `StateBackend` — LangGraph state channel storage via `CONFIG_KEY_READ` / `CONFIG_KEY_SEND` |
| `libs/deepagents/deepagents/backends/filesystem.py` | `FilesystemBackend` — direct disk I/O with optional virtual path mode |
| `libs/deepagents/deepagents/backends/local_shell.py` | `LocalShellBackend` — extends `FilesystemBackend` with unrestricted local `subprocess` execution |
| `libs/deepagents/deepagents/backends/store.py` | `StoreBackend`, `BackendContext`, `NamespaceFactory` — persistent cross-thread storage via LangGraph `BaseStore` |
| `libs/deepagents/deepagents/backends/langsmith.py` | `LangSmithSandbox` — wraps LangSmith `Sandbox` for remote isolated execution |
| `libs/deepagents/deepagents/backends/composite.py` | `CompositeBackend` — path-prefix routing across multiple backends |
| `libs/deepagents/deepagents/backends/__init__.py` | Public backend export surface |
| `libs/deepagents/deepagents/middleware/filesystem.py` | Tool layer that consumes backend capabilities — implements `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute` as agent tools |

---

## See Also

- [Graph Factory](graph-factory.md)
- [CLI Runtime](cli-runtime.md)
- [Local vs Remote Execution](../concepts/local-vs-remote-execution.md)
- [Remote Subagent and Sandbox Flow](../syntheses/remote-subagent-and-sandbox-flow.md)
- [Batteries Included Agent Architecture](../concepts/batteries-included-agent-architecture.md)
- [Sdk To Cli Composition](../syntheses/sdk-to-cli-composition.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
