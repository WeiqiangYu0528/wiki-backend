# Remote Subagent and Sandbox Flow

## Overview

This synthesis describes how work moves from the main agent into remote execution environments: async subagents running on remote LangGraph servers, isolated sandbox shells via `BaseSandbox`, and path-prefix routing through `CompositeBackend`. The three mechanisms are independent but compose: a parent agent can call a remote async subagent that itself runs file operations inside a sandboxed environment routed by a composite backend.

## Systems Involved

- [Subagent System](../entities/subagent-system.md) — `AsyncSubAgentMiddleware`, `AsyncSubAgent` TypedDict, async task tools
- [Backend System](../entities/backend-system.md) — `BaseSandbox`, `CompositeBackend`, `BackendProtocol`
- [Sandbox Partners](../entities/sandbox-partners.md) — Daytona, Modal, Runloop, LangSmith sandbox integrations
- [Local vs Remote Execution](../concepts/local-vs-remote-execution.md)
- [SDK to CLI Composition](sdk-to-cli-composition.md)

## Interaction Model

### Part A — Async Subagent Flow

#### Step 1 — Parent agent calls `start_async_task`

`AsyncSubAgentMiddleware` (in `libs/deepagents/deepagents/middleware/async_subagents.py`) registers five tools when `AsyncSubAgent` specs are passed to `create_deep_agent()`:

| Tool | Schema | Purpose |
|---|---|---|
| `start_async_task` | `StartAsyncTaskSchema(description, subagent_type)` | Launch a background task; returns `task_id` immediately |
| `check_async_task` | `CheckAsyncTaskSchema(task_id)` | Poll status and retrieve result when complete |
| `update_async_task` | `UpdateAsyncTaskSchema(task_id, message)` | Send follow-up instructions; interrupts current run, starts fresh on same thread |
| `cancel_async_task` | `CancelAsyncTaskSchema(task_id)` | Stop a running task |
| `list_async_tasks` | `ListAsyncTasksSchema(status_filter)` | List all tracked tasks with live statuses |

Task metadata is persisted in `AsyncSubAgentState.async_tasks: Annotated[NotRequired[dict[str, AsyncTask]], _tasks_reducer]`. The `_tasks_reducer` merges updates into the dict on each LangGraph state update.

#### Step 2 — Async task launch via LangGraph SDK

`start_async_task` resolves the named subagent from the available `AsyncSubAgent` specs. Each spec is a `TypedDict`:

```python
class AsyncSubAgent(TypedDict):
    name: str           # unique identifier
    description: str    # shown to the model in the tool description
    graph_id: str       # graph name or assistant ID on the remote server
    url: NotRequired[str]       # Agent Protocol server URL
    headers: NotRequired[dict[str, str]]  # auth headers
```

The middleware calls `get_client(url=...)` (or `get_sync_client`) from `langgraph_sdk` to create a `LangGraphClient`. Authentication for LangGraph Platform is handled automatically via `LANGGRAPH_API_KEY`, `LANGSMITH_API_KEY`, or `LANGCHAIN_API_KEY` environment variables.

The SDK creates a new thread on the remote server, starts a run, and records a new `AsyncTask` entry:

```python
class AsyncTask(TypedDict):
    task_id: str          # same as thread_id for stable reference
    agent_name: str       # which AsyncSubAgent type
    thread_id: str        # remote server thread
    run_id: str           # current run on that thread
    status: str           # 'running', 'success', 'error', 'cancelled'
    created_at: str       # ISO-8601 UTC
    last_checked_at: str
    last_updated_at: str
```

The tool returns the `task_id` immediately. The system prompt instructs the model not to auto-check status — it should return control to the user and only poll `check_async_task` when the user asks.

#### Step 3 — Parent polls with `check_async_task`

`check_async_task(task_id)` calls the LangGraph SDK to fetch the current run status. If the status is `"success"`, the result messages from the remote thread are included in the response. Multiple async subagents can run concurrently since the parent never blocks.

### Part B — Sandbox Shell Execution

#### `BaseSandbox` (`libs/deepagents/deepagents/backends/sandbox.py`)

`BaseSandbox` is an abstract base class implementing `SandboxBackendProtocol`. Concrete subclasses (Daytona, Modal, Runloop, LangSmith) implement only two abstract methods:

- `execute(command: str, *, timeout: int | None) -> ExecuteResponse`
- `upload_files(files: list[FileUploadRequest]) -> FileUploadResponse`

All other operations (`ls`, `read`, `write`, `edit`, `glob`, `grep`) are derived from those two primitives using shell commands and Python scripts passed via `execute()`.

The `glob` operation runs a Python3 inline script that uses `glob.glob()` with base64-encoded parameters to avoid shell escaping issues. Results include path, size, mtime, and `is_dir`.

The `edit` operation uses `_EDIT_COMMAND_TEMPLATE` — a Python3 heredoc script that reads the file, performs string replacement, and writes back — all on the sandbox. Payloads over `_EDIT_INLINE_MAX_BYTES = 50_000` bytes fall back to `_edit_via_upload()` which transfers old/new strings as temp files via `upload_files()`.

#### Sandbox Execution Flow

1. `FilesystemMiddleware` receives a tool call (e.g., `edit_file`)
2. It delegates to the backend's `edit()` method
3. `BaseSandbox.edit()` builds the appropriate Python inline script
4. The script is passed to `execute()` on the concrete sandbox implementation
5. The sandbox executes it in its isolated environment and returns stdout/stderr
6. `BaseSandbox` parses the JSON output and returns an `EditResult`

### Part C — `CompositeBackend` Path-Prefix Routing

`CompositeBackend` (in `libs/deepagents/deepagents/backends/composite.py`) routes file operations to different backends based on path prefixes, matching longest-first:

```python
composite = CompositeBackend(
    default=StateBackend(),
    routes={"/memories/": StoreBackend()}
)

composite.write("/temp.txt", "ephemeral")        # → StateBackend (default)
composite.write("/memories/note.md", "persistent") # → StoreBackend
```

`_route_for_path()` implements the routing logic:
- If path equals the route root without trailing slash (e.g., `"/memories"`) → route to that backend, normalize to `"/"`
- If path starts with a route prefix → strip prefix, route to backend with remaining path
- Otherwise → default backend with original path

For `glob` and `grep` operations, `CompositeBackend` fans out to all matching backends and merges results, remapping paths back to their full prefixed form with `_remap_grep_path()` and `_remap_file_info_path()`.

In the CLI, the composite backend is typically configured with:
- `default=LocalShellBackend()` or `FilesystemBackend()` for local file operations
- `/memories/` prefix routed to `StoreBackend()` backed by the LangGraph `store` for persistent memory

## Key Interfaces

| Interface | Location | Purpose |
|---|---|---|
| `AsyncSubAgent` | `middleware/async_subagents.py` | TypedDict spec for a remote subagent |
| `AsyncTask` | `middleware/async_subagents.py` | Persisted task state in `AsyncSubAgentState` |
| `AsyncSubAgentMiddleware` | `middleware/async_subagents.py` | Registers async task tools and manages state |
| `BaseSandbox` | `backends/sandbox.py` | Abstract base; subclasses implement `execute()` and `upload_files()` |
| `SandboxBackendProtocol` | `backends/protocol.py` | Protocol interface for execution-capable backends |
| `CompositeBackend` | `backends/composite.py` | Path-prefix router; `default` + `routes: dict[str, BackendProtocol]` |
| `LangGraphClient` | `langgraph_sdk` | SDK client used to launch and poll remote runs |

## See Also

- [Local vs Remote Execution](../concepts/local-vs-remote-execution.md)
- [Subagent System](../entities/subagent-system.md)
- [Backend System](../entities/backend-system.md)
- [Sandbox Partners](../entities/sandbox-partners.md)
- [ACP Server](../entities/acp-server.md)
- [SDK to CLI Composition](sdk-to-cli-composition.md)
- [Filesystem-First Agent Configuration](../concepts/filesystem-first-agent-configuration.md)
