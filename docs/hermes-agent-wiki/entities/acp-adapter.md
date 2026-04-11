# ACP Adapter

## Overview

The ACP adapter is the bridge that lets an editor talk to Hermes as if Hermes were an editor-native coding agent rather than a standalone CLI process. On one side is an ACP client such as VS Code, Zed, or a JetBrains plugin speaking async JSON-RPC over stdio. On the other side is Hermes' normal runtime: `AIAgent`, the tool registry, terminal/file tools, provider resolution, session storage, and approval rules.

In practice, that means the ACP adapter does five things:

- boots an ACP stdio server without polluting stdout
- creates and restores editor-scoped Hermes sessions
- runs synchronous `AIAgent` work safely from an async ACP server
- converts Hermes callbacks into ACP session updates the editor can render
- converts Hermes approval prompts into ACP permission requests

The ACP adapter owns transport, session wiring, and editor-facing translation. The underlying Hermes runtime still owns model execution, tool behavior, dangerous-command policy, provider setup, and persistence infrastructure.

## Key Interfaces / Key Concepts

| Anchor | Why it matters |
| --- | --- |
| `main()` in `hermes-agent/acp_adapter/entry.py` | Boot entry point for `hermes acp`, `hermes-acp`, and `python -m acp_adapter`; loads Hermes env, routes logs to stderr, and starts the ACP server. |
| `HermesACPAgent` in `hermes-agent/acp_adapter/server.py` | Main protocol adapter that implements ACP lifecycle methods, prompt execution, slash commands, model switching, and session updates. |
| `SessionManager` and `SessionState` in `hermes-agent/acp_adapter/session.py` | Hold the live editor session state: session ID, agent instance, cwd, model, message history, and cancel event. |
| `_register_task_cwd()` in `hermes-agent/acp_adapter/session.py` | Binds the editor workspace to the Hermes task/session ID so terminal and file tools operate relative to the editor's cwd. |
| `make_tool_progress_cb()`, `make_step_cb()`, `make_thinking_cb()`, `make_message_cb()` in `hermes-agent/acp_adapter/events.py` | Convert synchronous agent callbacks into ACP `session_update` events on the main event loop. |
| `build_tool_start()` / `build_tool_complete()` in `hermes-agent/acp_adapter/tools.py` | Turn Hermes tool calls and results into editor-friendly ACP content such as terminal blocks, diffs, and truncated previews. |
| `make_approval_callback()` in `hermes-agent/acp_adapter/permissions.py` | Bridges Hermes terminal approvals into ACP permission requests and maps editor choices back to Hermes approval results. |
| `detect_provider()` / `has_provider()` in `hermes-agent/acp_adapter/auth.py` | Show that ACP auth is only a thin view over Hermes' normal runtime-provider resolution, not a separate credential system. |

## Architecture

The ACP adapter is best understood as a translation layer with explicit boundaries.

It owns:

- ACP protocol methods such as initialize, authenticate, session creation, prompt, cancel, and model/mode updates
- stdio server boot and the rule that stdout must remain protocol-only JSON-RPC
- per-editor session objects and their binding to a Hermes `task_id`
- callback bridging from sync Hermes execution into async ACP event delivery
- editor-facing permission requests and tool-call presentation

It does not own:

- the agent loop itself
- provider credentials or provider-specific auth flows
- the actual behavior of terminal, file, browser, memory, or MCP tools
- dangerous-command detection logic
- CLI prompting or gateway messaging behavior

The cleanest boundary map is:

| Layer | Owns | Stops before |
| --- | --- | --- |
| ACP adapter (`acp_adapter/*`) | ACP transport, session lifecycle, callback/event translation, permission mediation, editor command surface | Running the core Hermes runtime logic itself |
| Hermes agent runtime (`run_agent.py`, `model_tools.py`, tool modules) | Prompt execution, tool dispatch, command policy, provider behavior, session persistence, tool semantics | Editor-specific rendering and ACP protocol mechanics |
| CLI and gateway surfaces | Their own shell UX, prompts, notifications, and message transport | ACP editor transport and editor session semantics |

ACP sessions are not a separate flavor of Hermes reasoning. They are normal Hermes runs wrapped in a different surface. When the editor asks for a prompt, the adapter eventually calls `AIAgent.run_conversation(...)`. When the editor approves a dangerous command, ACP is only supplying the approval transport.

## Runtime Behavior

### 1. Boot starts as a stdio transport, not as a chat shell

The entry path begins in `acp_adapter/entry.py`. `main()` loads `~/.hermes/.env`, configures logging to stderr, ensures the project root is importable, constructs `HermesACPAgent`, and starts `acp.run_agent(...)`.

ACP uses stdout for framed JSON-RPC traffic, so any human-readable logging or incidental `print()` output would corrupt the protocol stream. The adapter therefore pushes logs to stderr instead. `SessionManager` reinforces the same rule by overriding the agent's human-facing print function to write to stderr as well.

That makes ACP different from the CLI immediately. The CLI is itself a human interface. ACP is a protocol bridge that must stay silent on stdout unless it is speaking ACP.

### 2. Connect, initialize, and authenticate advertise Hermes through ACP

Once a client connects, `HermesACPAgent.on_connect()` stores the ACP connection object so the adapter can later send `session_update` events and permission requests.

The next stage is `initialize()`. This is where the adapter tells the editor what Hermes can do in ACP mode:

- protocol version
- agent identity and version
- session capabilities such as fork and list
- optional auth methods derived from Hermes' configured provider

The auth part is intentionally thin. `acp_adapter/auth.py` asks Hermes' runtime-provider resolver what provider is currently configured. If Hermes can already resolve a provider and API key, `initialize()` advertises a matching auth method, and `authenticate()` simply returns success. If Hermes has no configured provider, ACP auth fails. There is no ACP-local credential vault, login wizard, or alternate auth backend.

So ACP auth is only confirming that Hermes itself is already configured to run.

### 3. Session bootstrap creates a Hermes agent bound to the editor workspace

Session creation and restoration run through `SessionManager`.

`new_session(cwd=...)` creates a fresh `SessionState` with:

- a unique ACP session ID
- a new `AIAgent`
- the editor cwd
- the selected model
- conversation history
- a cancellation event

The constructed agent is still a Hermes agent. `_make_agent()` creates it with ACP-specific surface settings such as `platform="acp"`, `enabled_toolsets=["hermes-acp"]`, `quiet_mode=True`, and the ACP session ID. Provider information still comes from the normal Hermes config and runtime-provider resolution path.

The cwd binding is important. `_register_task_cwd()` stores a task-specific override in the terminal tool runtime so terminal and file operations resolve relative to the editor workspace rather than the server process directory. That is the bridge between "editor session" and "Hermes tool execution context."

Session lifecycle methods then layer on top of the same manager:

- `load_session()` updates cwd and restores a known session
- `resume_session()` restores if possible or creates a new session if missing
- `fork_session()` deep-copies conversation history into a new live session
- `list_sessions()` returns lightweight session info to the client

ACP's session story is more nuanced than "process-local memory." Live sessions are cached in memory for speed, but `SessionManager` also persists ACP sessions into Hermes' shared `SessionDB` in `~/.hermes/state.db` with `source="acp"`. If the ACP server restarts, the manager can restore the session record, rebuild the `AIAgent`, reload history, and rebind the cwd override.

### 4. ACP can extend the tool surface, but Hermes still owns tool definitions

During `new_session()`, `load_session()`, `resume_session()`, and `fork_session()`, the adapter can receive ACP-provided MCP server definitions. `_register_session_mcp_servers()` registers those servers through Hermes' MCP tooling and then refreshes the session agent's tool list using `model_tools.get_tool_definitions(...)`.

That boundary matters:

- ACP owns the protocol-level receipt of MCP server definitions
- Hermes still owns MCP registration, tool definition generation, and prompt invalidation

After bootstrap, the adapter also schedules an `available_commands_update` so the editor knows about ACP-handled slash commands such as `/help`, `/model`, `/tools`, `/context`, `/reset`, `/compact`, and `/version`.

Those commands are another example of scoped ownership. The adapter owns this small editor command surface because those actions are better handled locally than by sending them through the model.

### 5. Prompt execution is a sync-to-async handoff

`prompt()` is the core runtime path.

The flow is:

1. Resolve the session by ID.
2. Extract plain text from ACP content blocks.
3. Handle recognized slash commands locally if the text starts with `/`.
4. Clear any previous cancel signal.
5. Build ACP event callbacks and a permission callback if a client connection exists.
6. Install those callbacks on the session's `AIAgent`.
7. Temporarily install the ACP approval callback onto the terminal tool.
8. Run `agent.run_conversation(...)` in a `ThreadPoolExecutor`.
9. Persist updated history and send the final response chunk back to the editor.

ACP server I/O is async, but `AIAgent` is synchronous. The adapter resolves that mismatch by running agent work in a worker thread while the main event loop stays free to handle ACP protocol traffic. That is why `events.py` uses `asyncio.run_coroutine_threadsafe(...)`: callbacks fire inside the worker thread, but ACP updates must be delivered on the main loop.

This is the central handoff in the subsystem: ACP owns prompt transport, callback wiring, and worker-thread orchestration; Hermes owns the actual conversation run.

### 6. Events and tool rendering make Hermes activity look editor-native

While the agent is running, the adapter streams several kinds of updates back to the editor:

- thinking text
- assistant message text
- tool-call start events
- tool-call completion events

`events.py` builds those bridges from Hermes callbacks. Two details are especially important.

First, `make_tool_progress_cb()` only emits ACP start events for `tool.started`. Completion is handled later in `make_step_cb()` when Hermes reports the previous tool results. Second, tool IDs are tracked as FIFO queues per tool name. That prevents repeated or parallel same-name tool calls from being paired with the wrong completion event.

`tools.py` then shapes the content the editor sees. Instead of raw generic JSON for every tool, the adapter provides editor-appropriate renderings:

- `patch` and `write_file` become diff-like content
- `terminal` becomes shell command text
- `read_file` and `search_files` become concise previews
- large outputs are truncated for UI safety

This is translation logic. The adapter is not changing what a tool did, only how that tool call is represented to the ACP client.

### 7. Permission mediation is a transport bridge, not a policy engine

Dangerous terminal commands are where the ownership boundary must stay especially clear.

Hermes' terminal/runtime layer still decides whether a command needs approval. The ACP adapter does not inspect shell commands and does not replace Hermes' dangerous-command guards. Instead, when prompt execution begins, `prompt()` temporarily installs an ACP-aware approval callback via `make_approval_callback()`.

That callback:

- sends an ACP `request_permission` call to the editor
- offers `allow_once`, `allow_always`, and deny options
- maps the editor's choice back into Hermes approval strings such as `once`, `always`, or `deny`
- denies by default on timeout or transport failure

So the split is:

- Hermes decides whether approval is required
- ACP asks the editor user and translates the answer

The callback is restored after the run completes so ACP session-specific approval handling does not leak into other runtime contexts.

### 8. Cancellation, session mutation, and teardown stay lightweight

`cancel(session_id)` sets the session's cancel event and calls `agent.interrupt()` when available. After the run returns, `prompt()` reports `stop_reason="cancelled"` if that flag was set.

The adapter also supports session mutation after bootstrap:

- `set_session_model()` rebuilds the session's `AIAgent` with the new model
- `set_session_mode()` stores the editor-requested mode even if Hermes has no rich typed ACP mode system yet
- `set_config_option()` records client config values for compatibility

All of those updates are persisted through `SessionManager.save_session()`.

Teardown in ACP is intentionally light. The adapter can remove or clean up sessions through the session manager, which clears cwd overrides and deletes persisted ACP session rows. But the broader design favors continuity over aggressive teardown: sessions are meant to survive editor reconnects and process restarts when possible.

## Source Files

| File | Why it is an anchor |
| --- | --- |
| `hermes-agent/acp_adapter/entry.py` | Boot flow, env loading, stderr logging, and `acp.run_agent(...)` startup. |
| `hermes-agent/acp_adapter/__main__.py` | Minimal module entry point for `python -m acp_adapter`. |
| `hermes-agent/acp_adapter/server.py` | Main ACP protocol implementation: initialize/authenticate, session lifecycle, prompt execution, slash commands, permission callback installation, and model/mode/config updates. |
| `hermes-agent/acp_adapter/session.py` | Thread-safe session manager, cwd binding, SessionDB persistence/restore, and `AIAgent` construction for ACP sessions. |
| `hermes-agent/acp_adapter/events.py` | Worker-thread callback bridge that emits ACP session updates and pairs tool starts/completions correctly. |
| `hermes-agent/acp_adapter/tools.py` | Tool kind mapping plus editor-facing rendering for diffs, terminal commands, previews, and truncated outputs. |
| `hermes-agent/acp_adapter/permissions.py` | ACP permission request bridge used by Hermes terminal approvals. |
| `hermes-agent/acp_adapter/auth.py` | Thin provider-detection layer proving ACP reuses Hermes runtime auth state. |
| `hermes-agent/docs/acp-setup.md` | User-facing setup and editor integration guidance for ACP mode. |
| `hermes-agent/website/docs/developer-guide/acp-internals.md` | Maintainer-oriented description of the same bridge, useful as a secondary narrative source. |
| `hermes-agent/website/docs/user-guide/features/acp.md` | User-facing summary of ACP capabilities, toolset scope, and editor behavior. |
| `hermes-agent/tests/acp/` | Test coverage for permissions, tool rendering, event pairing, session restore behavior, MCP registration, and ACP server flows. |

## See Also

- [CLI Runtime](cli-runtime.md)
- [Gateway Runtime](gateway-runtime.md)
- [Tool Registry and Dispatch](tool-registry-and-dispatch.md)
- [Session Storage](session-storage.md)
- [ACP Editor Session Bridge](../syntheses/acp-editor-session-bridge.md)
- [Interruption and Human Approval Flow](../concepts/interruption-and-human-approval-flow.md)
