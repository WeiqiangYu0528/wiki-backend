# Tool and Agent Composition

## Overview

OpenCode's agent behavior is not a single fixed loop. It is the product of four composable layers: the set of tools registered for the current session, the permission rules governing those tools, the prompt variant selected for the session mode, and the optional `plan` step that gates execution behind a planning phase. The `task` tool adds a fifth dimension by allowing the running agent to spawn a sub-session (sub-agent) that executes with its own tool set and message history. Plugins inject additional tools at startup, so the effective tool registry is not static across configurations.

Understanding this composition is essential for predicting what the agent will do in a given session and for debugging unexpected behavior.

## Mechanism

### Tool registration pattern

Every tool is registered with a consistent shape:

```typescript
{
  name:        string               // model-visible tool name
  description: string               // shown in the model context window
  parameters:  ZodSchema            // JSON Schema for inputs, validated by zod
  execute:     (args, ctx) => Promise<Output>
}
```

The `name` is the identifier the language model uses in its tool call. The `description` is prompt-visible and shapes when the model chooses to invoke the tool. The `parameters` schema is serialized to JSON Schema and included in the model request so the model can generate valid arguments. The `execute` function receives the validated arguments and a context object that includes the active `InstanceContext`, the `Bus`, and the current session state.

The tool registry (`tool/registry.ts`) assembles the final list of tools for a given model call. Not all tools are always available: `Flag` values, model capabilities, and session mode can suppress or expose specific tools.

### Permission check before execute

Before calling any tool's `execute` function, the session runner calls into the permission system. The tool name is used as the `permission` key. If the permission gate returns `deny`, `execute` is never called. If it returns `ask`, execution is suspended until the user responds. Only `allow` (either from a rule match or from a previous `"always"` grant) lets the call proceed to `execute`.

This means the tool author's `execute` function can assume the user has approved the action; it does not need to perform its own authorization checks.

### batch tool

The `batch` tool allows the model to request parallel execution of multiple tool calls in a single turn. It accepts an array of tool invocations and runs them concurrently. Each individual call still passes through the permission gate independently. `batch` is particularly useful for file operations where the model wants to read several files simultaneously without waiting for each one sequentially.

### task tool and sub-agent delegation

The `task` tool spawns a child session. The calling session provides a goal description and optionally a tool subset. The child session runs as an independent agent with its own message history, its own tool invocations, and its own permission evaluations. When the child session completes, it returns a result summary to the parent session.

Child sessions are recorded with a `parentID` in `SessionTable`, linking them to the originating session. The `childTitlePrefix` constant in `session/index.ts` distinguishes child session titles from parent sessions in the UI. This tree structure supports multi-step delegation: a parent agent can orchestrate several specialist sub-agents without keeping all intermediate state in a single context window.

### plan mode

In `plan` mode, the session runs a two-phase loop:

1. **Planning phase**: The model is given a planning prompt (selected by `SessionPrompt` based on session mode). It produces a plan as structured text or a list of steps. Tool calls are not executed during this phase.
2. **Execution phase**: The user reviews and approves the plan. Once approved, the session switches to execution mode and runs the plan steps using normal tool execution.

`plan` mode is implemented by varying the prompt variant passed to the model and by filtering the available tools to a read-only subset during the planning phase. The session stores the plan file path so the plan can be recovered and resumed after interruption.

### Plugin-injected tools

Plugins can contribute tools through the `Hooks` interface. When `Plugin.Service.trigger()` is called during session setup, any `tools` hook implementations return additional tool definitions. These are merged into the registry before the model call. This means the available tool set is not fully known until all plugins have been initialized for the current instance.

The `INTERNAL_PLUGINS` (Codex, Copilot, GitLab, Poe) may each contribute provider-specific tools. External plugins loaded from npm can also inject arbitrary tools, subject to the `--pure` flag which disables external plugin loading.

### Prompt variant selection

`SessionPrompt` selects a system prompt based on:
- The current session mode (default, plan, build)
- The model family (different prompts for different providers)
- Whether a custom system prompt is configured in `opencode.json`

The prompt variant affects how the model interprets its task, how it uses tools, and how it structures its output. This is why two sessions with different modes but identical tool sets can behave differently.

## Invariants

1. Every tool call passes through the permission gate before `execute` is called. There is no bypass path in normal operation.
2. Child sessions created by `task` are independent: they have their own message history, their own permission evaluations, and their own tool results. The parent does not share context window contents with the child.
3. The tool registry is assembled once per model call. Tools added by plugins after the call begins are not available mid-conversation without a new call setup.
4. `plan` mode never executes tool calls during the planning phase. The tool filter is enforced at the registry level, not by the model's judgment.
5. `batch` tool parallel execution is bounded by the concurrency controls in the session runner. Each sub-call still produces an independent permission evaluation.

## Source Evidence

| File | What it confirms |
| --- | --- |
| `packages/opencode/src/tool/registry.ts` | Tool registration pattern, registry assembly, model-capability filtering |
| `packages/opencode/src/tool/task.ts` | `task` tool implementation; child session spawning |
| `packages/opencode/src/tool/batch.ts` | `batch` tool implementation; parallel execution |
| `packages/opencode/src/session/index.ts` | `parentID` field, `childTitlePrefix`, plan file path logic |
| `packages/opencode/src/session/prompt.ts` | `SessionPrompt` variant selection logic |
| `packages/opencode/src/permission/index.ts` | Permission gate called before each tool `execute` |
| `packages/opencode/src/plugin/index.ts` | `Plugin.Interface.trigger()` used to collect plugin-contributed tools |

## See Also

- [Permission and Approval Gating](permission-and-approval-gating.md)
- [Provider Agnostic Model Routing](provider-agnostic-model-routing.md)
- [Plugin Driven Extensibility](plugin-driven-extensibility.md)
- [Tool System](../entities/tool-system.md)
- [Session System](../entities/session-system.md)
- [Provider Tool Plugin Interaction Model](../syntheses/provider-tool-plugin-interaction-model.md)
- [Request to Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Context Compaction and Session Recovery](../syntheses/context-compaction-and-session-recovery.md)
- [Architecture Overview](../summaries/architecture-overview.md)
