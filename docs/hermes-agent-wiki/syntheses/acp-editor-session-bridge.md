# ACP Editor Session Bridge

## Overview

The ACP bridge lets an editor client talk to Hermes as an editor-native agent server, but it does not replace Hermes' runtime. The simplest mental model is: the ACP adapter handles protocol transport and editor-shaped session state, while Hermes still owns model execution, tool behavior, approval policy, and persistence.

That split matters because the editor needs a familiar session lifecycle:

1. connect to the agent
2. authenticate against the configured Hermes provider
3. create or resume a workspace-bound session
4. send prompts into the running conversation
5. stream messages, tool activity, and reasoning updates back to the editor
6. route dangerous-command approvals through the editor UI

This page follows that flow in order and calls out where the ACP adapter stops and the underlying Hermes runtime takes over.

## Systems Involved

The adapter is the visible surface, but it sits on top of normal Hermes subsystems. The ACP-specific code lives in [ACP Adapter](../entities/acp-adapter.md), while the conversation loop still comes from [Agent Loop Runtime](../entities/agent-loop-runtime.md) and long-lived state still persists through [Session Storage](../entities/session-storage.md).

The main layers are the ACP client and its stdio JSON-RPC transport, `acp_adapter/server.py` for ACP methods and session lifecycle, `acp_adapter/session.py` for session/cwd binding, `acp_adapter/events.py` for callback translation, `acp_adapter/permissions.py` for approval transport, and the Hermes runtime itself for turns, tools, and persistence.

The point of the adapter is not to create a second agent runtime. It is to translate between editor protocol expectations and Hermes' existing execution model.

## Interaction Model

The full handshake is easiest to understand as a sequence.

### 1. The editor connects over ACP transport

An ACP client starts a Hermes ACP process and opens a stdio JSON-RPC connection. `HermesACPAgent.on_connect()` stores that connection so the server can later send session updates and permission requests back to the editor.

At this stage the adapter is still only speaking protocol. It has not created a conversation yet, and it has not run any model work.

### 2. Hermes advertises what ACP mode supports

`initialize()` returns the agent identity, protocol version, and session capabilities the editor can rely on. Hermes also advertises auth methods only when the normal runtime provider resolution path can already find a provider.

That means ACP auth is a view into Hermes configuration, not a separate login system. `authenticate()` succeeds when Hermes already has the provider credentials it needs; otherwise the editor cannot proceed.

### 3. The editor creates or resumes a session with a cwd

The session manager is where ACP becomes workspace-aware. `new_session()`, `load_session()`, `resume_session()`, and `fork_session()` all work through `SessionManager`, which constructs or restores a live `AIAgent` and attaches:

- a unique session ID
- the editor's current working directory
- the selected model
- conversation history
- a cancellation event

The cwd binding is not cosmetic. `_register_task_cwd()` pushes the editor workspace into Hermes' terminal-tool overrides so file and shell tools run relative to the project the editor is showing. ACP sessions also persist into Hermes' shared `SessionDB`, so the manager can restore history after a restart.

### 4. The editor sends a prompt into the session

`prompt()` is the core execution path.

The adapter resolves the ACP session, extracts plain text from the prompt blocks, and handles recognized slash commands locally before it ever calls the model. That local branch is important because commands like `/help`, `/model`, `/tools`, `/context`, `/reset`, `/compact`, and `/version` are editor controls, not agent turns.

If the input is an ordinary prompt, `prompt()` prepares the runtime bridge:

- it clears any prior cancellation flag
- it builds callbacks for thinking, assistant messages, and tool progress
- it builds an ACP permission callback if a client connection exists
- it installs those callbacks on the session's `AIAgent`
- it temporarily installs the ACP approval bridge onto the terminal tool
- it runs `agent.run_conversation(...)` in a worker thread so the ACP event loop stays responsive

This is the most important ownership boundary in the subsystem. ACP owns the prompt transport and callback wiring, but Hermes still owns the actual turn.

### 5. Hermes executes the turn and streams events back

The agent loop runs synchronously in a thread pool, but the editor expects live updates on the main event loop. `events.py` solves that mismatch by converting callback invocations into ACP `session_update` calls with `asyncio.run_coroutine_threadsafe(...)`.

The adapter streams three kinds of editor-visible activity:

- thinking text from the reasoning callback
- assistant message text from the message callback
- tool start and completion events from the tool-progress and step callbacks

Tool events are paired carefully. `make_tool_progress_cb()` records tool-call IDs by tool name, and `make_step_cb()` drains them in FIFO order so repeated same-name tool calls do not get matched to the wrong completion event. The editor therefore sees a coherent tool timeline even though Hermes is running synchronously in another thread.

### 6. Dangerous-command approval is routed through the editor, not re-implemented in ACP

When a Hermes terminal action needs approval, the adapter does not decide on its own. `make_approval_callback()` turns Hermes' approval callback into an ACP `request_permission` call, shows the editor permission choices, and translates the response back into Hermes approval results.

That transport boundary is deliberate:

- Hermes decides whether a command is dangerous and whether approval is required
- ACP decides how to ask the user in the editor UI
- the adapter maps the choice back into Hermes' approval vocabulary

If the permission round-trip fails or times out, the callback denies by default. That preserves the runtime invariant that risky shell actions do not silently execute.

### 7. The session is persisted and the final response is returned

After the worker-thread run finishes, the adapter copies the updated history back into `SessionManager` and persists the session so reconnects and restarts can restore it later. The final assistant text is then sent as an ACP message update, and the prompt call ends with a stop reason.

## Key Interfaces

| Boundary | What crosses it | Who owns the next step |
| --- | --- | --- |
| Editor client -> ACP adapter | JSON-RPC initialize, session, prompt, cancel, and permission calls | The adapter translates protocol events into Hermes operations |
| ACP adapter -> Hermes session manager | Session ID, cwd, model, history, cancel state | Hermes session state owns the live conversation object |
| Session manager -> terminal/tool runtime | Task-specific cwd binding and approval callback | Hermes tools execute with the editor workspace context |
| Worker thread -> ACP event loop | Thinking, message, tool-start, and tool-complete callbacks | The editor receives streamed updates through ACP session events |
| Hermes runtime -> SessionDB | Updated history and session metadata | Durable session persistence survives reconnects and restarts |

## Permissions And Event Streaming

Two cross-cutting concerns deserve extra clarity because they show the adapter boundary most sharply.

Permission handling is not an ACP-local policy engine. The adapter is only the transport for human approval. The dangerous-command decision still comes from the Hermes tool stack, and the ACP client is just the active surface that gathers the user's response.

Event streaming is the same kind of translation. Hermes callbacks are synchronous and runtime-owned; ACP session updates are asynchronous and editor-owned. `events.py` bridges that gap without making the editor responsible for agent logic or making Hermes responsible for UI scheduling.

That separation gives the runtime a few useful invariants:

- the editor never sees raw internal callback objects
- Hermes never has to know which editor client is connected
- permission requests and event updates can fail independently without corrupting the turn
- the same underlying Hermes run still behaves like a normal Hermes run, just wrapped in ACP transport

## Source Evidence

This synthesis is anchored in the adapter implementation and tests:

- `hermes-agent/acp_adapter/server.py` for ACP initialize/authenticate, session lifecycle, prompt execution, slash commands, worker-thread orchestration, and callback installation
- `hermes-agent/acp_adapter/session.py` for `SessionManager`, cwd binding, restore logic, and `SessionDB` persistence
- `hermes-agent/acp_adapter/events.py` for ACP event streaming from synchronous Hermes callbacks
- `hermes-agent/acp_adapter/permissions.py` for the approval transport bridge and fallback-deny behavior
- `hermes-agent/tests/acp/` for tests covering permissions, events, sessions, auth, server flows, and tool rendering
- [ACP Adapter](../entities/acp-adapter.md) for the broader architecture
- [Agent Loop Runtime](../entities/agent-loop-runtime.md) for the execution loop that ACP invokes
- [Session Storage](../entities/session-storage.md) for the durable session layer ACP reuses

## See Also

- [ACP Adapter](../entities/acp-adapter.md)
- [CLI Runtime](../entities/cli-runtime.md)
- [Gateway Runtime](../entities/gateway-runtime.md)
- [Interruption and Human Approval Flow](../concepts/interruption-and-human-approval-flow.md)
- [Multi-Surface Session Continuity](../concepts/multi-surface-session-continuity.md)
