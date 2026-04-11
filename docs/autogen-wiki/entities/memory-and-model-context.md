# Memory and Model Context

## Overview

AutoGen distinguishes between two related but different concerns: what immediate history or token window is presented to a model during a run, and what longer-lived knowledge or retrieval surfaces an agent can consult. The first concern belongs to model context. The second belongs to memory. The repository treats both as pluggable capabilities rather than hard-coded properties of the agent loop.

This split is visible directly in `AssistantAgent`. It imports `ChatCompletionContext` and `UnboundedChatCompletionContext` from Core model-context support, and it also accepts a `memory` sequence of memory components. The docstring then explicitly describes how alternate model-context implementations can limit message count or token budget while memory stores remain a separate capability layer.

## Key Types

| Type | Source | Role |
|------|--------|------|
| `ChatCompletionContext` | `autogen_core.model_context` | Abstract context-shaping interface for model prompts |
| `UnboundedChatCompletionContext` | same import surface | Default or broad message-history behavior |
| `Memory` | `autogen_core.memory` | Abstract memory capability used by high-level agents |
| Memory backends | `python/packages/autogen-ext/src/autogen_ext/memory/` | Concrete memory implementations |

## Architecture

Model context is primarily a **prompt-shaping concern**. It determines how much history or which messages are sent to the model during inference. The AgentChat docstring points to bounded and token-limited contexts as examples. These are runtime-control primitives for keeping inference economical or model-compatible.

Memory is primarily a **knowledge augmentation concern**. It lets an agent maintain or query information outside the immediate prompt window. In the repository this expands in Extensions into concrete memory backends and experimental task-centric memory systems.

The architecture matters because these two ideas are often collapsed into one in simpler frameworks. AutoGen keeps them distinct, which makes it easier to reason about whether a behavior comes from short-term context shaping or from explicit memory augmentation.

## Runtime Behavior

During an AgentChat run, the model context influences what history is available for the next inference. A bounded context may trim or summarize history before the call. An unbounded context may retain the entire run history.

Memory participates differently. It can be attached as a component that the agent consults or uses to augment reasoning. The fact that `AssistantAgent` emits a `MemoryQueryEvent` in its message imports underscores that memory interaction is treated as an observable execution event rather than as hidden internal state.

The Extensions tree makes clear that memory is not one backend. There are backends and experiments for multiple storage or retrieval strategies, including task-centric memory work and integrations such as Redis, Chroma, or Mem0-related support.

## Variants, Boundaries, and Failure Modes

The crucial boundary is:

- model context shapes the prompt window
- memory augments knowledge beyond that window

That boundary matters because a failure to answer a question may come from prompt truncation, not from memory absence, or vice versa. It also matters for package ownership: Core defines the abstractions, while Extensions provides many concrete memory backends.

## Source Files

| File | Purpose |
|------|---------|
| `python/packages/autogen-agentchat/src/autogen_agentchat/agents/_assistant_agent.py` | Shows both model-context and memory integration in the main high-level agent |
| `python/packages/autogen-core/src/autogen_core/model_context/` | Core model-context abstractions and implementations |
| `python/packages/autogen-core/src/autogen_core/memory/` | Core memory abstractions |
| `python/packages/autogen-ext/src/autogen_ext/memory/` | Concrete memory backends |
| `python/packages/autogen-ext/src/autogen_ext/experimental/task_centric_memory/` | Experimental memory behavior beyond the base abstractions |

## See Also

- [Python Core Runtime](python-core-runtime.md)
- [Python AgentChat](python-agentchat.md)
- [Python Extensions](python-extensions.md)
- [Tool-Augmented Agent Execution](../concepts/tool-augmented-agent-execution.md)
- [Core to AgentChat to Extension Composition](../syntheses/core-to-agentchat-to-extension-composition.md)
