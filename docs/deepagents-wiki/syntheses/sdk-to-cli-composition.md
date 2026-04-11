# SDK to CLI Composition

## Overview

`deepagents-cli` is a policy-and-product layer built on top of the SDK, not beside it. The CLI calls `create_deep_agent()` from the SDK, adds operational concerns that only make sense in an interactive terminal (streaming TUI, session persistence, MCP tool loading, human-in-the-loop approval, shell command allow-listing), and wraps the result in a Textual application. Understanding the composition handoff tells you exactly where SDK behavior ends and CLI-specific behavior begins.

## Systems Involved

- [CLI Runtime](../entities/cli-runtime.md) — `main.py`, `agent.py`: entry points and agent construction
- [Graph Factory](../entities/graph-factory.md) — `graph.py`: `create_deep_agent()` and the default SDK middleware stack
- [CLI Textual UI](../entities/cli-textual-ui.md) — `app.py`: the `DeepAgentsApp` Textual application
- [MCP System](../entities/mcp-system.md) — MCP tool loading and server metadata
- [Session Persistence](../entities/session-persistence.md) — SQLite checkpoints, thread IDs, history
- [Monorepo Package Layering](../concepts/monorepo-package-layering.md)

## Interaction Model

### Step 1 — Entry point: `cli_main()` in `deepagents_cli/__init__.py`

The CLI is registered as two entry points both pointing to `deepagents_cli:cli_main`. Startup defers all heavy imports until after argument parsing to keep `--help` fast. `check_cli_dependencies()` in `main.py` verifies that `textual`, `requests`, `dotenv`, and `tavily` are installed before proceeding.

### Step 2 — Config bootstrap in `config.py`

`_ensure_bootstrap()` (called lazily on first `settings` access) runs dotenv loading from two locations in priority order:

1. Project/CWD `.env` — detected by walking up from the start path
2. `~/.deepagents/.env` — global user defaults

Environment variables exported in the shell always override dotenv values (`override=False`). This runs before model creation and before MCP loading.

### Step 3 — Agent construction in `agent.py`

`agent.py` is where the CLI calls into the SDK. The central function imports `create_deep_agent` from `deepagents` and assembles the call with CLI-specific additions:

```python
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, LocalShellBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware import MemoryMiddleware, SkillsMiddleware
```

CLI-specific middleware added on top of the SDK defaults:

| Middleware | Class | Purpose |
|---|---|---|
| `ShellAllowListMiddleware` | defined in `agent.py` | Validates shell commands against a configured allow-list before execution; returns error `ToolMessage` for rejected commands without pausing the graph |
| `LocalContextMiddleware` | from `local_context.py` | Runs environment detection script at startup; injects `## Local Context` into system prompt |
| `ConfigurableModelMiddleware` | from `configurable_model.py` | Enables runtime `/model` switching within a session |

`ShellAllowListMiddleware` wraps both `wrap_tool_call` and `awrap_tool_call`. When a shell command is not in `self._allow_list`, it returns an error `ToolMessage` immediately rather than raising — this keeps LangSmith traces as a single continuous run instead of fragmenting them at interrupt/resume boundaries.

### Step 4 — `create_deep_agent()` and graph assembly

The SDK's `create_deep_agent()` signature:

```python
def create_deep_agent(
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    *,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    subagents: Sequence[SubAgent | CompiledSubAgent | AsyncSubAgent] | None = None,
    skills: list[str] | None = None,
    memory: list[str] | None = None,
    response_format: ...,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    backend: BackendProtocol | BackendFactory | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    ...
) -> CompiledStateGraph
```

The default middleware stack assembled inside `create_deep_agent()`:

```python
[
    TodoListMiddleware(),
    FilesystemMiddleware(backend=backend),
    create_summarization_middleware(model, backend),
    PatchToolCallsMiddleware(),
    # optional: SkillsMiddleware(backend, sources=skills)
    AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
    # optional: MemoryMiddleware(...)
]
```

The CLI passes its own additional middleware via the `middleware` parameter, appended after the base stack but before `AnthropicPromptCachingMiddleware`.

The default model is `ChatAnthropic(model_name="claude-sonnet-4-6")`.

### Step 5 — LangGraph server and streaming

In interactive mode the CLI wraps the compiled graph in a LangGraph server process (`ServerProcess` in `server.py`) and connects a remote client. The `DeepAgentsApp` (Textual) sends messages via this client rather than calling the graph directly. This enables:

- Streaming token delivery to the TUI as they arrive
- Clean trace separation in LangSmith (one run per user turn)
- Session resume via SQLite checkpoint (provided by `langgraph-checkpoint-sqlite`)

### Step 6 — Session persistence

Thread IDs are UUID7 strings generated by `sessions.generate_thread_id()`. The SQLite checkpointer persists the full LangGraph state between turns, enabling `deepagents -r` to resume the most recent session and `deepagents -r <thread_id>` to resume a specific one.

## Key Interfaces

| Interface | Location | Purpose |
|---|---|---|
| `create_deep_agent()` | `libs/deepagents/deepagents/graph.py` | SDK entry point; returns `CompiledStateGraph` |
| `ShellAllowListMiddleware` | `libs/cli/deepagents_cli/agent.py` | CLI-only shell gating without graph pause |
| `LocalContextMiddleware` | `libs/cli/deepagents_cli/local_context.py` | Environment detection and system-prompt injection |
| `DeepAgentsApp` | `libs/cli/deepagents_cli/app.py` | Textual application; owns UI lifecycle |
| `AgentMiddleware` | `langchain.agents.middleware.types` | Base class for all middleware in the stack |
| `BackendProtocol` | `libs/deepagents/deepagents/backends/protocol.py` | Interface all backends must implement |

## See Also

- [CLI Runtime](../entities/cli-runtime.md)
- [Graph Factory](../entities/graph-factory.md)
- [Monorepo Package Layering](../concepts/monorepo-package-layering.md)
- [Interactive Session Lifecycle](interactive-session-lifecycle.md)
- [Agent Customization Surface](agent-customization-surface.md)
- [Architecture Overview](../summaries/architecture-overview.md)
