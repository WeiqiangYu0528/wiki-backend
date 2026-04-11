# Interactive Session Lifecycle

## Overview

This synthesis follows a single interactive CLI session from launch to shutdown: config loading, agent construction, TUI initialization, the user input → agent response loop, HITL tool approval, and session history persistence. Understanding this path tells you exactly where each system takes ownership and how failures in one layer surface as symptoms in another.

## Systems Involved

- [CLI Runtime](../entities/cli-runtime.md) — `main.py`, `agent.py`: startup and agent construction
- [CLI Textual UI](../entities/cli-textual-ui.md) — `app.py`: `DeepAgentsApp` and all widgets
- [Session Persistence](../entities/session-persistence.md) — thread IDs, SQLite checkpoints, history
- [Human in the Loop Approval](../concepts/human-in-the-loop-approval.md) — `interrupt_on`, `ApprovalMenu`
- [MCP System](../entities/mcp-system.md) — MCP server metadata preloading
- [SDK to CLI Composition](sdk-to-cli-composition.md)

## Interaction Model

### Phase 1 — Startup and Config Load

`cli_main()` → argument parsing → `_ensure_bootstrap()`.

Bootstrap runs once (guarded by `_bootstrap_lock`) and performs:
1. Dotenv loading: project `.env` (walked up from CWD) then `~/.deepagents/.env`
2. `LANGSMITH_PROJECT` override for agent traces
3. Optional ripgrep availability check via `check_optional_tools()`

Config file location: `~/.deepagents/config.toml` (read by `DEFAULT_CONFIG_PATH` in `model_config.py`). Theme preference is stored under `[ui].theme` and loaded at `DeepAgentsApp` construction via `_load_theme_preference()`.

### Phase 2 — Agent Construction

`agent.py` calls `create_deep_agent()` with:
- Model from `config.toml` or `--model` flag
- CLI-specific middleware: `LocalContextMiddleware`, `ConfigurableModelMiddleware`, `ShellAllowListMiddleware`
- MCP tools loaded by `load_mcp_tools()` if MCP is not disabled
- `checkpointer=SqliteSaver(...)` from `langgraph-checkpoint-sqlite`
- `interrupt_on` mapping from config (controls HITL gating per tool name)

Async subagents from `[async_subagents]` in `config.toml` are loaded by `load_async_subagents()` and passed as the `subagents` parameter.

For server mode the agent is wrapped in a LangGraph server process started by `start_server_and_get_agent()`. The app then connects via `RemoteAgent` (LangGraph SDK client) rather than calling the graph directly.

### Phase 3 — TUI Initialization

`DeepAgentsApp.__init__()` receives:

```python
DeepAgentsApp(
    agent=agent,               # Pregel compiled graph or None (deferred)
    backend=backend,           # CompositeBackend
    auto_approve=bool,         # --yes flag
    cwd=Path,                  # for status bar display
    thread_id=str,             # UUID7 session ID
    resume_thread=str|None,    # '-r' flag value
    initial_prompt=str|None,   # prompt passed inline on CLI
    mcp_server_info=list,      # for /mcp viewer
    server_kwargs=dict|None,   # deferred server startup kwargs
)
```

On `on_mount()` the app:
1. Configures scrollbar style (ASCII mode detection via `is_ascii_mode()`)
2. Registers custom Textual themes (`_register_custom_themes()`)
3. Applies saved theme from config
4. If `server_kwargs` is set: starts server in a background worker and shows "Connecting..." state

Key keybindings registered in `BINDINGS`:
- `escape` → `action_interrupt` — interrupts the running agent
- `ctrl+c` → `action_quit_or_interrupt`
- `ctrl+d` → `action_quit_app`
- `ctrl+t` / `shift+tab` → `action_toggle_auto_approve`
- `y` / `1`, `2` / `a`, `3` / `n` → approval menu yes/auto/no

### Phase 4 — Welcome Banner

`WelcomeBanner` widget is composed on first render. It displays the current model, MCP server summary (from `mcp_server_info`), working directory, and available slash commands. The banner is skipped if an `initial_prompt` was provided on the command line.

### Phase 5 — User Input via `ChatInput`

`ChatInput` is a custom Textual input widget with autocomplete (backed by `textual-autocomplete`) and slash-command recognition. Input modes (`InputMode`): `"normal"`, `"shell"`, `"command"`.

Submitted messages become `QueuedMessage(text=str, mode=InputMode)` dataclass instances.

### Phase 6 — `action_submit()`

When the user presses Enter, `action_submit()` is called on `DeepAgentsApp`. It:
1. Reads text from `ChatInput`
2. Detects slash commands (`/model`, `/mcp`, `/compact`, `/clear`, `/help`, `/changelog`, `/docs`, etc.)
3. For non-slash messages: posts a `QueuedUserMessage` to the `MessageStore` and starts a Textual `Worker` to run the agent
4. The worker calls `agent.astream()` (or the remote client equivalent) with the user message and current `thread_id`

### Phase 7 — Streaming Tokens and Tool Display

As the agent streams:
- Text tokens → `AssistantMessage` widget, updated incrementally
- Tool call requests → `ToolCallMessage` widget with tool name and arguments
- Tool results → `ToolCallMessage` status updated to success/error

`SessionStats` tracks token counts and updates the `StatusBar` widget with model name, token usage, and spinner state.

`SpinnerStatus` drives the animated spinner in the status bar during agent execution.

### Phase 8 — HITL Tool Approval

When `interrupt_on` is configured and the agent calls a gated tool, LangGraph pauses the graph and the app receives an interrupt. The `ApprovalMenu` modal widget is displayed with options:

- **Yes (y/1)** — approve this call once
- **Auto (a/2)** — approve all future calls to this tool in the session
- **No (n/3)** — reject and return an error tool message

`REQUIRE_COMPACT_TOOL_APPROVAL = True` (in `agent.py`) means `compact_conversation` also requires HITL approval by default.

The approval widget is deferred if the user is actively typing (checked against `_TYPING_IDLE_THRESHOLD_SECONDS = 2.0`). A fallback timeout of `_DEFERRED_APPROVAL_TIMEOUT_SECONDS = 30.0` shows the widget regardless.

Unicode safety checks run on tool call arguments via `detect_dangerous_unicode()` before display.

### Phase 9 — Session End and History Save

On quit (`ctrl+d` or `ctrl+c` when idle):
1. The Textual app calls `action_quit_app()`
2. Open background workers are cancelled
3. The SQLite checkpointer has already been persisting state after each graph turn
4. `sessions.py` writes thread metadata (model used, message count, last active timestamp) to a metadata cache
5. The LangGraph server process (`ServerProcess`) is terminated

On next launch with `deepagents -r`, the most recent `thread_id` is resolved from the metadata cache and the SQLite checkpoint is replayed to restore full graph state.

## Key Interfaces

| Interface | Type | Purpose |
|---|---|---|
| `DeepAgentsApp` | `textual.app.App` subclass | Top-level Textual application; owns UI lifecycle |
| `ChatInput` | Textual widget | User text entry with autocomplete and slash-command support |
| `ApprovalMenu` | `ModalScreen` subclass | HITL tool approval dialog |
| `MessageStore` | Dataclass | In-memory ordered log of `MessageData` for UI rendering |
| `TextualSessionState` | Dataclass | Holds `auto_approve: bool` and `thread_id: str` for the current session |
| `QueuedMessage` | Frozen dataclass | Carries `text` and `mode` from input to the agent worker |
| `SessionStats` | Dataclass | Tracks token counts; drives `StatusBar` display |
| `SqliteSaver` | LangGraph checkpointer | Persists full agent state to SQLite between turns |

## See Also

- [Session Persistence](../entities/session-persistence.md)
- [CLI Textual UI](../entities/cli-textual-ui.md)
- [Human in the Loop Approval](../concepts/human-in-the-loop-approval.md)
- [SDK to CLI Composition](sdk-to-cli-composition.md)
- [Agent Customization Surface](agent-customization-surface.md)
- [Architecture Overview](../summaries/architecture-overview.md)
