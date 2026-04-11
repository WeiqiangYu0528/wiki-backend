# Sandbox Partners

## Overview

The partner packages under `libs/partners/` extend Deep Agents with remote sandbox execution environments and one lightweight computation middleware. Three packages — `langchain-daytona`, `langchain-modal`, and `langchain-runloop` — each provide a concrete `BaseSandbox` subclass that implements the `SandboxBackendProtocol` by wrapping a cloud-hosted container or devbox. A fourth package, `langchain-quickjs`, is not a remote sandbox but adds a stateless in-process JavaScript REPL tool via QuickJS middleware. All three sandbox packages share the same file-operation logic (read, write, edit, ls, grep, glob) inherited from `BaseSandbox` in the core `deepagents` library, and only need to implement `execute()` and `upload_files()` themselves.

## Key Types / Key Concepts

```python
# Core protocol (libs/deepagents/deepagents/backends/protocol.py)
class SandboxBackendProtocol(Protocol):
    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse: ...
    def upload_files(self, files: list[FileData]) -> FileUploadResponse: ...

# Base class (libs/deepagents/deepagents/backends/sandbox.py)
class BaseSandbox(ABC):
    """Implements ls, read, write, edit, grep, glob via execute() + upload_files().
    File ops use base64-encoded Python3 one-liners run inside the sandbox shell."""

# Partner implementations
class DaytonaSandbox(BaseSandbox):   # langchain-daytona
    def __init__(self, *, sandbox: daytona.Sandbox,
                 timeout: int = 1800,
                 sync_polling_interval: float | Callable = 0.1) -> None: ...

class ModalSandbox(BaseSandbox):     # langchain-modal
    def __init__(self, *, sandbox: modal.Sandbox) -> None: ...

class RunloopSandbox(BaseSandbox):   # langchain-runloop
    def __init__(self, *, devbox: Devbox) -> None: ...

# QuickJS middleware (langchain-quickjs)
class QuickJSMiddleware:
    def __init__(self, ptc: list[Callable] = [],
                 add_ptc_docs: bool = False) -> None: ...
```

**`ExecuteResponse`**: contains `output: str`, `exit_code: int`, `truncated: bool`.

## Architecture

### `BaseSandbox` — shared file-operation layer

All file operations in `BaseSandbox` are implemented by sending base64-encoded Python3 one-liners through `execute()`. This design means the partner packages have zero dependency on remote filesystem APIs and work identically regardless of the sandbox provider. For example, glob runs a `python3 -c "import glob, json, base64 ..."` snippet; edit transfers the old/new strings as base64-encoded heredoc input for payloads under `_EDIT_INLINE_MAX_BYTES` (50,000 bytes), and falls back to `upload_files` + a server-side replace script for larger payloads.

### Daytona (`langchain-daytona`)

Wraps an existing `daytona.Sandbox` instance. Execute uses Daytona's `SessionExecuteRequest` API. Because Daytona's native execution is asynchronous, `DaytonaSandbox` implements a configurable sync polling loop: `sync_polling_interval` can be a fixed float (seconds between polls, default 0.1 s) or a callable that receives elapsed time and returns the next delay, enabling adaptive backoff.

```python
from daytona import Daytona
from langchain_daytona import DaytonaSandbox

sandbox = Daytona().create()
backend = DaytonaSandbox(sandbox=sandbox, timeout=300, sync_polling_interval=0.25)
result = backend.execute("echo hello")
```

**Required env var:** `DAYTONA_API_KEY`

**Trade-offs:** Cloud-hosted; requires Daytona account. Good for Harbor's high-concurrency Terminal Bench runs (the evals Makefile uses `--jobs daytona` for 40 concurrent trials). The polling interval is the main latency tuning knob.

### Modal (`langchain-modal`)

Wraps a `modal.Sandbox` instance. Unlike Daytona, Modal exposes a native filesystem API (`sandbox.open(path, mode)`), so `ModalSandbox` overrides `_read_file` and `_write_file` with direct Modal calls rather than going through `execute()`. For everything else (ls, grep, glob, edit) it falls back to the `BaseSandbox` shell-script approach. File-not-found conditions are detected by catching `modal.exception.FilesystemExecutionError`.

```python
import modal
from langchain_modal import ModalSandbox

sandbox = ModalSandbox(sandbox=modal.Sandbox.create(app=modal.App.lookup("your-app")))
result = sandbox.execute("python3 script.py")
```

**Required:** Modal account and `modal setup` authentication. The `nvidia_deep_agent` example uses Modal for GPU execution (A10G by default, configurable to A100/T4/H100).

**Trade-offs:** Supports GPU hardware (the only partner that does). Native filesystem API makes read/write faster than shell-script round-trips. CPU mode uses a lightweight image; GPU mode uses the NVIDIA RAPIDS Docker image.

### Runloop (`langchain-runloop`)

Wraps a Runloop `Devbox`. Execute delegates to `devbox.cmd.exec(command, timeout=...)`, combining stdout and stderr into a single output string. File operations use `BaseSandbox`'s shell-script approach (no native filesystem API).

```python
from runloop_api_client import RunloopSDK
from langchain_runloop import RunloopSandbox

client = RunloopSDK(bearer_token=os.environ["RUNLOOP_API_KEY"])
devbox = client.devbox.create()
sandbox = RunloopSandbox(devbox=devbox)
try:
    result = sandbox.execute("echo hello")
finally:
    devbox.shutdown()
```

**Required env var:** `RUNLOOP_API_KEY`

**Trade-offs:** Devboxes must be explicitly shut down. The `id` property exposes the devbox ID for reuse across sessions (e.g. Ralph mode's `--sandbox-id` flag).

### QuickJS (`langchain-quickjs`)

Not a remote sandbox. Adds a stateless `repl` tool to any Deep Agent that evaluates JavaScript snippets using the embedded [QuickJS](https://bellard.org/quickjs/) engine. Each call starts from a fresh context (no state carries between calls). Python callables exposed via `ptc` (Python-to-callable) are bridged as foreign functions inside the REPL, with primitive type passing (`int`, `float`, `bool`, `str`, `None`, lists, dicts). Async Python functions are supported via a dedicated daemon-thread event loop.

```python
from langchain_quickjs import QuickJSMiddleware
from deepagents import create_deep_agent

agent = create_deep_agent(
    model="openai:gpt-4.1",
    middleware=[QuickJSMiddleware(ptc=[normalize_name], add_ptc_docs=True)],
)
```

**Use cases:** Small computations, JSON manipulation, control flow, calling Python helpers without spawning a sandbox. Not suitable for Node.js or browser APIs, does not support HIL in the REPL, and does not yet support `ToolRuntime`.

### Comparison

| Provider | Remote | GPU | Native FS API | Polling required | Key env var |
|----------|--------|-----|---------------|-----------------|-------------|
| Daytona | Yes | No | No (shell) | Yes (configurable) | `DAYTONA_API_KEY` |
| Modal | Yes | Yes | Yes (partial) | No | `modal setup` / token |
| Runloop | Yes | No | No (shell) | No | `RUNLOOP_API_KEY` |
| QuickJS | No | No | N/A | N/A | None |

All remote sandbox backends share the same `BaseSandbox` file-op layer and are drop-in replacements for each other when passed as the `backend` argument to `create_deep_agent`.

## Source Files

| File | Purpose |
|------|---------|
| `libs/deepagents/deepagents/backends/sandbox.py` | `BaseSandbox` ABC: shared file-op shell-script templates, `_EDIT_INLINE_MAX_BYTES`, `_edit_via_upload` |
| `libs/deepagents/deepagents/backends/protocol.py` | `SandboxBackendProtocol`, `ExecuteResponse`, `FileData`, and all result types |
| `libs/partners/daytona/langchain_daytona/sandbox.py` | `DaytonaSandbox`: polling execute, configurable `sync_polling_interval` |
| `libs/partners/daytona/README.md` | Daytona installation and quick-start |
| `libs/partners/modal/langchain_modal/sandbox.py` | `ModalSandbox`: native file API for read/write, shell-script for everything else |
| `libs/partners/modal/README.md` | Modal installation and quick-start |
| `libs/partners/runloop/langchain_runloop/sandbox.py` | `RunloopSandbox`: `devbox.cmd.exec` execute, `id` property |
| `libs/partners/runloop/README.md` | Runloop installation and quick-start |
| `libs/partners/quickjs/langchain_quickjs/__init__.py` | `QuickJSMiddleware`: stateless JS REPL, ptc bridging, async foreign function support |
| `libs/partners/quickjs/README.md` | QuickJS usage, REPL behavior, current limitations |

## See Also

- [Backend System](./backend-system.md)
- [Evals System](./evals-system.md)
- [Example Agents](./example-agents.md)
- [Subagent System](./subagent-system.md)
