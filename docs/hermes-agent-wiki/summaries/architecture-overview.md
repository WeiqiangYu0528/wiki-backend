# Hermes Agent Architecture Overview

## Overview

Hermes Agent is easiest to understand as one shared agent runtime wrapped by several shells. It is not just a CLI agent with a few adapters bolted onto the side. The same core loop powers the terminal experience, the long-running [Gateway Runtime](../entities/gateway-runtime.md), the editor-facing [ACP Adapter](../entities/acp-adapter.md), the scheduled [Cron System](../entities/cron-system.md), and the [Research and Batch Surfaces](../entities/research-and-batch-surfaces.md).

Hermes is also not a collection of separate agents that happen to share a repository. It is a platform that combines one reusable execution core with governed tool access, persistent session storage, and recall systems that survive across turns and sessions.

The central runtime anchor is [`AIAgent`](../entities/agent-loop-runtime.md) in `run_agent.py`. Around it sit the shells that accept input, the systems that build prompt context, the capability layer that exposes tools to the model, and the persistence layer that keeps long-running work coherent. If you keep those four layers separate in your head, the rest of the codebase gets much easier to read.

![Hermes Agent system architecture](../assets/graphs/hermes-agent-architecture.png)

[Edit diagram source](../assets/graphs/hermes-agent-architecture.excalidraw)

## Why The Repository Feels Larger Than A CLI Agent

A simple CLI agent can stop at "read input, call model, print output." Hermes does not. It supports multiple user-facing shells, and those shells all need consistent model behavior, tool behavior, and session continuity.

That leads to more infrastructure around the core loop. The [CLI Runtime](../entities/cli-runtime.md) focuses on local interactive use. The [Gateway Runtime](../entities/gateway-runtime.md) adds inbound event handling, authorization, delivery, and session routing for messaging platforms. The [ACP Adapter](../entities/acp-adapter.md) exposes Hermes as an editor-facing service. The [Cron System](../entities/cron-system.md) creates scheduled agent runs instead of interactive ones.

The repository is also larger because Hermes treats persistence as part of normal runtime behavior. Session history lives in [Session Storage](../entities/session-storage.md). Long-term recall and provider-backed memory live in [Memory and Learning Loop](../entities/memory-and-learning-loop.md). Prompt context is assembled from filesystem and runtime sources in [Prompt Assembly System](../entities/prompt-assembly-system.md), not from a single hardcoded template.

Finally, tool exposure is governed instead of automatic. The model only sees the tools that pass platform presets, toolset filtering, and readiness checks, which is why [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md) is a major subsystem rather than a thin helper.

## The Main Runtime Layers

The cleanest mental model is to separate Hermes into a few stable ownership layers. Each layer prepares work for the next one.

| Layer | What it owns | Main anchors | Read next |
|---|---|---|---|
| Shells and entry surfaces | Accepting input, resolving config, choosing session identity, presenting results | `hermes_cli/main.py`, `gateway/run.py`, `acp_adapter/`, `cron/` | [CLI Runtime](../entities/cli-runtime.md), [Gateway Runtime](../entities/gateway-runtime.md), [ACP Adapter](../entities/acp-adapter.md), [Cron System](../entities/cron-system.md) |
| Core agent runtime | Running the conversation loop, choosing API mode, handling retries, tool loops, fallback, callbacks, and compression | `run_agent.py`, `website/docs/developer-guide/agent-loop.md` | [Agent Loop Runtime](../entities/agent-loop-runtime.md) |
| Capability surface | Registering tools, deciding which ones are visible, and dispatching model tool calls | `model_tools.py`, `tools/registry.py`, `toolsets.py` | [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md) |
| Prompt context and recall | Building the stable system prompt, layering in filesystem context, skills, memories, and external recall | `agent/prompt_builder.py`, `agent/memory_manager.py`, `agent/context_compressor.py` | [Prompt Assembly System](../entities/prompt-assembly-system.md), [Memory and Learning Loop](../entities/memory-and-learning-loop.md) |
| Persistence and continuity | Saving sessions, supporting search and lineage, and restoring conversations across shells | `hermes_state.py`, `gateway/session.py` | [Session Storage](../entities/session-storage.md) |

This separation matters because Hermes does not want each shell to reimplement agent logic. A shell should prepare a request and deliver the outcome. The agent loop should own execution. The persistence and recall systems should preserve continuity without turning the shells themselves into runtime forks.

## How A Request Moves Through Hermes

Most Hermes requests follow the same broad path, even when the input surface changes.

1. A shell receives input. In the terminal that is the [CLI Runtime](../entities/cli-runtime.md). In chat platforms it is the [Gateway Runtime](../entities/gateway-runtime.md). In editors it is the [ACP Adapter](../entities/acp-adapter.md).
2. The shell resolves runtime setup. That includes provider and model settings, active profile, enabled toolsets, and any surface-specific callbacks or approval paths.
3. The shell determines session context. It may restore a stored conversation, create a fresh session, or map an inbound platform event onto a gateway session key before calling the agent.
4. `AIAgent.run_conversation()` takes over. This is the main execution spine described in [Agent Loop Runtime](../entities/agent-loop-runtime.md): it assembles prompt context, formats messages for the selected API mode, and makes the model call.
5. If the model asks for tools, Hermes routes those calls through the governed capability layer in [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md). Some agent-owned tools are intercepted inside the loop; normal tool calls go through the registry and its readiness checks.
6. During and after the turn, Hermes updates continuity systems. Memory writes, recall hooks, compression, and session persistence flow through [Memory and Learning Loop](../entities/memory-and-learning-loop.md) and [Session Storage](../entities/session-storage.md).
7. Control returns to the shell. The shell formats the final response, delivers it to the terminal, editor, or platform adapter, and handles any shell-specific follow-up such as queueing, approval responses, or background delivery.

The important pattern is that the shell-specific work happens mostly before and after the loop. The middle of the request is meant to stay shared.

## Why Hermes Is Structured This Way

After the request flow, the next useful question is why the repository is partitioned this way. The short answer is that Hermes is optimized for runtime consistency across surfaces, not for keeping each surface self-contained.

### The shells stay thin so behavior does not drift

If the CLI, gateway, ACP, and cron each owned their own execution loop, they would drift in tool behavior, prompt rules, fallback logic, and session semantics. Hermes avoids that by pushing real execution down into [`AIAgent`](../entities/agent-loop-runtime.md) and keeping the shells focused on surface concerns such as input, delivery, approvals, and session identity.

### Persistence sits close to the runtime because long sessions are normal

Hermes assumes users will resume work, compress conversations, search past sessions, and carry context across shells. Because of that, persistence is not an afterthought added at the edge. Systems such as [Session Storage](../entities/session-storage.md) and [Memory and Learning Loop](../entities/memory-and-learning-loop.md) sit close to the runtime path and show up during normal turn handling.

### Tool access is a product boundary, not just an implementation detail

The model-visible capability surface changes by platform, config, and runtime readiness. That is why Hermes has a distinct [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md) layer instead of handing every helper directly to the model. Toolsets, approval transport, and dynamic discovery from MCP or plugins all exist to keep that surface governed.

### Files on disk are part of runtime input, not just configuration

Hermes pulls identity and policy from files such as `SOUL.md`, `HERMES.md`, `AGENTS.md`, and related context files. That decision keeps behavior editable without rewriting Python code, but it also means [Prompt Assembly System](../entities/prompt-assembly-system.md) has to be treated as core runtime machinery rather than a thin prompt helper.

## Reading Paths For Different Readers

Different readers should branch into different pages after this overview.

| If you want to understand... | Start here | Then read |
|---|---|---|
| The core execution spine | [Agent Loop Runtime](../entities/agent-loop-runtime.md) | [Prompt Assembly System](../entities/prompt-assembly-system.md), [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md) |
| Messaging and long-running behavior | [Gateway Runtime](../entities/gateway-runtime.md) | [Session Storage](../entities/session-storage.md), [Gateway Message to Agent Reply Flow](../syntheses/gateway-message-to-agent-reply-flow.md) |
| Why Hermes keeps context across turns | [Session Storage](../entities/session-storage.md) | [Memory and Learning Loop](../entities/memory-and-learning-loop.md), [Prompt Layering and Cache Stability](../concepts/prompt-layering-and-cache-stability.md) |
| The big-picture design | [Self-Improving Agent Architecture](../concepts/self-improving-agent-architecture.md) | [Codebase Map](codebase-map.md), [Research and Batch Surfaces](../entities/research-and-batch-surfaces.md) |

If you want the shortest practical path, read this page, then [Agent Loop Runtime](../entities/agent-loop-runtime.md), then [Gateway Runtime](../entities/gateway-runtime.md). That sequence gives you the core runtime, the main long-running shell, and the clearest boundary between them.

## See Also

- [Codebase Map](codebase-map.md)
- [Agent Loop Runtime](../entities/agent-loop-runtime.md)
- [Gateway Runtime](../entities/gateway-runtime.md)
- [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md)
- [Self-Improving Agent Architecture](../concepts/self-improving-agent-architecture.md)
