# Local vs Remote Execution

## Overview

deepagents agents can run shell commands through two fundamentally different backends: **local shell execution** directly on the host machine, or **remote sandbox execution** in an isolated environment provided by an external service (such as LangSmith).

The choice of backend is set once at agent creation via the `backend=` parameter of `create_deep_agent()` and propagates to every tool that requires execution or file I/O. Switching backends requires no changes to agent logic, tool definitions, or middleware — the `SandboxBackendProtocol` provides a uniform interface.

The trade-off is always between developer convenience (local is zero-setup) and security / isolation (remote keeps side effects off the developer's machine).

## Mechanism

### The backend protocol

All backends that support command execution implement `SandboxBackendProtocol`, which extends `BackendProtocol`. The core method is:

```python
def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse
```

`ExecuteResponse` carries `output` (combined stdout/stderr), `exit_code`, and a `truncated` flag. Higher-level file operations (`read`, `write`, `edit`, `glob`, `grep`, `ls`) are derived from `execute()` inside `BaseSandbox`, so remote backends get full filesystem semantics for free by implementing only `execute()` and `upload_files()`.

### Passing a backend to `create_deep_agent()`

```python
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend, LangSmithSandbox

# Local execution
agent = create_deep_agent(
    backend=LocalShellBackend(root_dir="/my/project", virtual_mode=True)
)

# Remote sandbox
from langsmith.sandbox import Sandbox
sandbox = Sandbox.create()
agent = create_deep_agent(backend=LangSmithSandbox(sandbox))
```

If `backend=None` is passed, `create_deep_agent()` defaults to `StateBackend()`, which supports file I/O against in-memory state but does not implement `execute()`. Shell commands will return an error message in that configuration.

## LocalShellBackend

**Source:** `libs/deepagents/deepagents/backends/local_shell.py`

`LocalShellBackend` extends `FilesystemBackend` and adds direct shell execution via `subprocess.run(..., shell=True)`. Every command runs on the host system with the user's own permissions.

### Constructor parameters

```python
LocalShellBackend(
    root_dir: str | Path | None = None,  # Working directory; defaults to cwd
    virtual_mode: bool | None = None,    # Virtual root for path routing (does NOT restrict shell)
    timeout: int = 120,                  # Default per-command timeout in seconds
    max_output_bytes: int = 100_000,     # Output capture limit before truncation
    env: dict[str, str] | None = None,   # Explicit environment variables
    inherit_env: bool = False,           # Inherit os.environ (apply env as overrides)
)
```

`virtual_mode=True` makes `root_dir` act as a virtual filesystem root for file-operation path resolution (useful with `CompositeBackend`). It does **not** restrict shell commands: `execute("cat /etc/passwd")` works regardless. The source docstring is explicit:

> `virtual_mode=True` and path-based restrictions provide NO security with shell access enabled, since commands can access any path on the system.

### Security posture

`LocalShellBackend` is intentionally unsandboxed. Appropriate use cases are personal development environments and local coding assistants. Inappropriate use cases listed in the source include production servers, multi-tenant systems, and untrusted input. Enabling HITL middleware is the primary recommended safeguard.

### Environment handling

When `inherit_env=False` (default), commands start with an empty environment unless `env` is explicitly provided. This prevents accidental secret exposure from the parent process environment. `inherit_env=True` copies `os.environ` and merges any `env` overrides on top.

### Output handling

Stdout and stderr are merged; `[stderr]` is prepended to each stderr line. Output is capped at `max_output_bytes` (default 100 KB); the `truncated` flag is set when this limit is hit.

## LangSmithSandbox / Remote Backends

**Sources:** `libs/deepagents/deepagents/backends/langsmith.py`, `libs/deepagents/deepagents/backends/sandbox.py`

### BaseSandbox

`BaseSandbox` is an abstract class implementing `SandboxBackendProtocol`. It provides all file operations (`ls`, `glob`, `grep`, `read`, `write`, `edit`, `download_files`, `upload_files`) by translating them into shell commands executed via `execute()`. Concrete subclasses only need to implement `execute()` and `upload_files()`.

Edit operations over 50 KB (`_EDIT_INLINE_MAX_BYTES = 50_000`) use a temp-file upload path to avoid exceeding request body limits on some sandbox providers.

### LangSmithSandbox

`LangSmithSandbox(sandbox: langsmith.sandbox.Sandbox)` wraps a LangSmith `Sandbox` instance:

```python
class LangSmithSandbox(BaseSandbox):
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._default_timeout: int = 30 * 60  # 30-minute default

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        result = self._sandbox.run(command, timeout=effective_timeout)
        ...
```

The default timeout is 30 minutes (versus 2 minutes for `LocalShellBackend`), reflecting that remote sandbox operations can be slower.

`write()` is overridden to use `self._sandbox.write()` (HTTP body transfer) rather than the `BaseSandbox` approach of embedding content in shell commands, which can exceed ARG_MAX for large files.

### Why use remote execution

- **Process isolation.** Commands run inside the sandbox provider's managed container, not on the developer's machine. A runaway process or malicious code cannot affect the host.
- **Secrets protection.** The host environment and filesystem are not exposed; the sandbox starts clean.
- **Multi-session safety.** Multiple concurrent agents can run in separate sandboxes without interfering with each other or the host.
- **Production-appropriate.** Remote sandboxes can be used in server and API contexts where `LocalShellBackend` is explicitly unsupported.

## The `offload.py` Module

**Source:** `libs/cli/deepagents_cli/offload.py`

`offload.py` implements the business logic for the CLI `/offload` command, which manually triggers conversation history archiving to the configured backend. It is not a backend switcher — it uses the existing `SummarizationMiddleware` and the active backend to persist evicted messages to `/conversation_history/{thread_id}.md`.

Key function `perform_offload()` rebuilds the effective message list accounting for any prior summarization event, computes the retention cutoff, and writes evicted messages to the backend as timestamped markdown sections. If no backend is configured, it falls back to a local `FilesystemBackend`.

```python
path = f"/conversation_history/{thread_id}.md"
new_section = f"## Offloaded at {timestamp}\n\n{buf}\n\n"
```

The `OffloadResult` dataclass captures before/after token counts, the number of messages offloaded and retained, and the percentage decrease in context usage.

## Trade-offs Summary

| Dimension | LocalShellBackend | LangSmithSandbox / Remote |
|---|---|---|
| Setup | Zero — runs immediately | Requires sandbox provisioning and API credentials |
| Security | None — host system fully exposed | Isolated container; host unaffected |
| Latency | Minimal | Network round-trip per command |
| Cost | Free | Billed by sandbox provider |
| Appropriate for | Local dev, personal tools, CI with secret management | Production APIs, multi-tenant systems, untrusted code |
| HITL recommended | Strongly yes | Yes, but lower urgency |
| Default timeout | 120 seconds | 1800 seconds (30 minutes) |
| Filesystem restriction | `virtual_mode` for path routing only (no security) | Isolated by default |

## Involved Entities

- [Backend System](../entities/backend-system.md) — defines `BackendProtocol`, `SandboxBackendProtocol`, `LocalShellBackend`, `LangSmithSandbox`, `BaseSandbox`, and `CompositeBackend`.
- [Subagent System](../entities/subagent-system.md) — subagents share the same backend instance provided to `create_deep_agent()`; file operations in subagents write to the same root.

## Source Evidence

**`libs/deepagents/deepagents/backends/local_shell.py`** — security warning:

```
This backend grants agents BOTH direct filesystem access AND unrestricted
shell execution on your local machine. Use with extreme caution and only in
appropriate environments.
```

`execute()` implementation note:
```
Commands are executed directly on your host system using subprocess.run()
with shell=True. There is no sandboxing, isolation, or security restrictions.
```

**`libs/deepagents/deepagents/backends/langsmith.py`** — 30-minute default timeout:
```python
self._default_timeout: int = 30 * 60
```

**`libs/deepagents/deepagents/graph.py`** — default backend fallback:
```python
backend = backend if backend is not None else StateBackend()
```

**`libs/cli/deepagents_cli/offload.py`** — fallback when no backend is set:
```python
if offload_backend is None:
    offload_backend = FilesystemBackend()
    logger.info("Using local FilesystemBackend for offload")
```

## See Also

- [Context Management and Summarization](context-management-and-summarization.md)
- [Human-in-the-Loop Approval](human-in-the-loop-approval.md)
- [Batteries-Included Agent Architecture](batteries-included-agent-architecture.md)
