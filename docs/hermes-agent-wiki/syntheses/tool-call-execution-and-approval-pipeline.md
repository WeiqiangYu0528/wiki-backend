# Tool Call Execution and Approval Pipeline

## Overview

This page follows one model-emitted tool call from the agent loop to its concrete effect. The key question is not just "did a tool run?" but whether the call became normal registry dispatch, an approval-blocked action, or an agent-local exception that never entered the registry path.

The pipeline crosses a few fixed boundaries. `AIAgent` parses model output and decides whether a call is ordinary dispatch or loop-owned special handling. `model_tools.py` hands ordinary calls into the registry. `tools/approval.py` applies dangerous-command policy. `tools/terminal_tool.py` executes approved commands in a backend environment. The result is then normalized and reinserted into history.

## Systems Involved

- [Agent Loop Runtime](../entities/agent-loop-runtime.md)
- [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md)
- [Terminal and Execution Environments](../entities/terminal-and-execution-environments.md)
- [ACP Adapter](../entities/acp-adapter.md)
- [Gateway Runtime](../entities/gateway-runtime.md)

## Interaction Model

The normal path is easier to understand as ordered stages.

1. The model returns one or more tool calls.
   The assistant message is still only a request, even if it already contains names, arguments, and ordering information.

2. `AIAgent` inspects the calls before dispatch.
   The agent loop owns the first interpretation pass and separates normal registry calls from loop-owned exceptions.

3. Ordinary tool calls enter `model_tools.handle_function_call(...)`.
   It coerces arguments, runs plugin pre-hooks when available, and forwards the call into the registry path.

4. The tool registry resolves the handler.
   `ToolRegistry.dispatch()` looks up the handler, bridges async execution when needed, and returns structured failures instead of crashing the turn.

5. Approval-sensitive tools are checked before execution.
   Terminal commands are the important example. `tools/terminal_tool.py` calls into the approval layer before a command reaches a backend, and `tools/approval.py` decides whether the command is dangerous, already approved, or blocked for human review.

6. If approval is required, Hermes pauses execution and hands control to the active surface.
   The approval decision does not live in the terminal backend or in the model. The active surface transports it instead: CLI prompts directly, the gateway uses in-band `/approve` and `/deny`, and ACP maps the decision to a permission request.

7. If the call is allowed, the tool handler runs.
   For terminal work, the selected backend environment executes the command. Other tools perform their work directly or through a tool-specific subsystem.

8. The result is normalized.
   Tool handlers return structured output, and failures become consistent JSON-style errors when needed.

9. The tool result is appended back into the conversation.
   `AIAgent` reinserts the result as a tool message so the next model step reasons over the actual side effect, not a guess.

The important boundary shifts are:

- model -> agent loop when a tool call is emitted
- agent loop -> `model_tools.py` for ordinary dispatch
- registry -> approval layer when a command must be blocked or confirmed
- approval layer -> calling surface when a human response is required
- tool runtime -> agent loop when the normalized result is appended back into history

## Key Interfaces

| Boundary | What crosses it | Why it matters |
| --- | --- | --- |
| Model -> agent loop | Tool call name, arguments, and ordering | The model has requested action, but nothing has executed yet. |
| Agent loop -> `model_tools.py` | Ordinary tool calls selected for registry dispatch | This is the handoff from loop-owned parsing into the tool runtime. |
| `model_tools.py` -> `ToolRegistry` | Tool name and coerced args | The registry turns a symbolic call into a concrete handler. |
| Registry -> approval policy | Terminal command text plus current session state | Dangerous actions are stopped before any process runs. |
| Approval policy -> surface transport | Permission request or `/approve` / `/deny` exchange | Hermes preserves one policy engine while letting each surface collect consent differently. |
| Tool runtime -> agent loop | Normalized tool output or structured error | The next reasoning step sees a stable result shape. |

## Agent-Local Exceptions

Not every model-visible tool goes through normal registry dispatch. Hermes keeps some tools advertised to the model but intercepts them inside the loop because they need agent-owned state or special orchestration.

The main examples are:

- `todo`, which is tied to agent-local task state
- `memory`, which may need direct access to the agent's memory manager
- `session_search`, which queries the current session database and needs the live session context
- `delegate_task`, which launches or coordinates child agents rather than a standalone tool handler

These are not hidden tools. They are visible to the model, but execution is owned by the loop, not the registry.

## Approval, Execution, And Surfaces

Hermes uses one approval policy engine, but the approval can travel through different surfaces.

### CLI

The CLI can prompt the user directly when a command is flagged as dangerous. That keeps the approval exchange local to the terminal session and is the simplest transport path.

### Gateway

The gateway cannot rely on a blocking terminal prompt, so approval round-trips through the messaging surface. `gateway/run.py` contains the explicit `/approve` and `/deny` handlers that unblock waiting dangerous-command executions.

### ACP

ACP uses a permission bridge in `acp_adapter/permissions.py`. The adapter converts Hermes approval needs into ACP permission requests and maps the editor's response back into Hermes approval strings.

The simplest model is: `tools/approval.py` decides whether approval is needed, the active shell asks the human, and the tool runtime continues only after the gate is satisfied.

## Execution Backends And Result Normalization

Once a command clears approval, `tools/terminal_tool.py` hands it to the selected execution environment. The terminal layer owns environment selection and reuse; the backend owns the actual process execution. After execution, Hermes normalizes the result into a stable response shape so dispatch errors, backend failures, and policy blocks all look consistent to the loop.

`model_tools.handle_function_call(...)` is also the main observation point for plugin `pre_tool_call` and `post_tool_call` hooks. Provider-specific behavior sees the result indirectly on the next model turn, after the tool output has been appended back into history.

## Ownership Boundaries

| Subsystem | Owns | Does not own |
| --- | --- | --- |
| `AIAgent` / agent loop | Parsing model tool calls, intercepting agent-local exceptions, appending tool results back into history | Tool schema governance, backend process execution, surface-specific approval UI |
| `model_tools.py` | Normal tool-call entry point, discovery, argument coercion, plugin hooks, registry handoff | Dangerous-command policy, editor or gateway permission UI |
| `tools/registry.py` | Tool metadata, dispatch resolution, async bridging, structured failure wrapping | Model output parsing or surface transport |
| `tools/approval.py` | Dangerous-command detection and approval state | How CLI, gateway, or ACP asks the user |
| `tools/terminal_tool.py` and backends | Approved command execution and output normalization | Whether the command should have been approved |
| CLI, gateway, ACP surfaces | Approval transport and user interaction | Shared tool-policy rules |

If the tool was visible but did not run, look at registry resolution, readiness checks, and the agent-local exception list. If the tool ran but asked for consent, look at approval policy and the active surface transport. If the tool ran successfully but the model still behaved oddly afterward, look at the normalized tool result reinsertion into the conversation.

## Source Evidence

The implementation evidence for this page comes from:

- `hermes-agent/model_tools.py` for tool discovery, argument handling, plugin hooks, and `handle_function_call(...)`
- `hermes-agent/tools/registry.py` for `ToolRegistry`, dispatch resolution, async bridging, and structured error handling
- `hermes-agent/tools/approval.py` for dangerous-command detection, approval state, and approval decisions
- `hermes-agent/tools/terminal_tool.py` for the approval gate and backend execution handoff
- `hermes-agent/acp_adapter/permissions.py` for ACP approval transport
- `hermes-agent/gateway/run.py` for gateway approval handlers such as `/approve` and `/deny`
- `hermes-agent/website/docs/developer-guide/tools-runtime.md` for the maintainer-facing narrative of the same pipeline

## See Also

- [Agent Loop Runtime](../entities/agent-loop-runtime.md)
- [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md)
- [Terminal and Execution Environments](../entities/terminal-and-execution-environments.md)
- [ACP Adapter](../entities/acp-adapter.md)
- [Gateway Runtime](../entities/gateway-runtime.md)
- [Interruption and Human Approval Flow](../concepts/interruption-and-human-approval-flow.md)
- [Gateway Message to Agent Reply Flow](gateway-message-to-agent-reply-flow.md)
