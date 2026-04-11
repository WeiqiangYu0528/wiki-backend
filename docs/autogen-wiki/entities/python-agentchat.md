# Python AgentChat

## Overview

`autogen-agentchat` is the high-level Python API layer that most AutoGen users are meant to start from. Its README says this directly: beginner users should start with AgentChat, while advanced users can drop down to `autogen-core` when they need more direct control over the event-driven substrate. That line is the right framing. AgentChat is not a separate runtime universe; it is a friendlier, more opinionated façade over Core concepts.

The package turns lower-level runtime abstractions into recognizable application-building primitives: assistant agents, user proxies, teams, task runners, handoffs, terminations, chat messages, and console UIs. It tries to reduce how much the user needs to think about topic routing or raw runtime-managed agent instantiation. But it does not sever those ties. The agent and team surfaces still depend on Core model clients, component models, message types, cancellation tokens, and state handling.

This page should be read as the “public developer API” counterpart to [Python Core Runtime](python-core-runtime.md). Core owns the substrate; AgentChat owns the higher-level ergonomics and common agent/team patterns.

## Key Types

| Type | Source | Role |
|------|--------|------|
| `AssistantAgent` | `src/autogen_agentchat/agents/_assistant_agent.py` | Main high-level agent abstraction with tools, workbench, memory, and structured-output support |
| `BaseChatAgent` | `src/autogen_agentchat/agents/_base_chat_agent.py` | Shared chat-agent lifecycle and run helpers |
| `Team` | `src/autogen_agentchat/base/_team.py` | Abstract multi-participant coordination surface |
| `TaskRunner` | `src/autogen_agentchat/base/_task.py` | Run / stream contract for tasks and teams |
| `Handoff` | `src/autogen_agentchat/base/_handoff.py` | Cross-agent delegation primitive |
| `Termination` types | `src/autogen_agentchat/base/_termination.py`, `conditions/_terminations.py` | Stop conditions for multi-agent runs |
| `AgentTool` / `TaskRunnerTool` | `src/autogen_agentchat/tools/` | Wrappers that expose agents or teams as tool-callable capabilities |

The `AssistantAgentConfig` model shows the scope of this layer clearly. It includes a model client, tools or workbenches, handoffs, model context, memory, description, system message, streaming, reflective tool use, tool-call summaries, maximum tool iterations, and metadata. That one config shape effectively summarizes the layer’s job: package many lower-level capabilities into a single reusable chat-oriented component.

## Architecture

AgentChat is organized around a few coherent clusters.

The **agent cluster** in `agents/` contains the concrete participants people actually instantiate. `AssistantAgent` is the flagship. `UserProxyAgent` gives human-driven participation. `CodeExecutorAgent` bridges code-execution surfaces into the chat-oriented layer. `SocietyOfMindAgent` and other specialized agents show how the layer packages more complex behavior while keeping the same TaskRunner-like surface.

The **coordination cluster** in `teams/` contains predefined multi-agent patterns. The tree includes round-robin, selector, swarm, graph, and Magentic-One-oriented group chat code. This is where AutoGen’s higher-level “multi-agent patterns” become reusable objects rather than copy-pasted orchestration code.

The **base contracts cluster** in `base/` defines `Team`, `TaskRunner`, termination concepts, and handoff abstractions. These are the stable interfaces that let concrete agents and teams share a common run/reset/pause/resume/state surface.

The **message and state cluster** in `messages.py` and `state/` defines the user-facing events and persisted shapes emitted by runs. These types matter because AgentChat does not just return raw model output; it can emit streaming chunks, tool call request and execution events, handoff messages, memory-query events, and structured message variants.

The **tool adaptation cluster** in `tools/` lets agents and teams themselves become callable tools. This is one of the ways AgentChat composes higher-order systems: a participant can present another participant as a tool rather than only as a peer in a team.

## Runtime Behavior

`AssistantAgent` is the clearest execution example. Its docstring and configuration surface describe a multi-step run loop that is more sophisticated than “call model once and print text.”

1. The caller provides only new messages, not the full history, because the agent maintains internal state between calls.
2. The agent uses its configured `model_context` to prepare the message history supplied to the model.
3. The model produces either a direct text/structured response or tool calls.
4. If no tool calls are produced, the response becomes the final `Response.chat_message`.
5. If tool calls are produced, they are executed immediately.
6. If `reflect_on_tool_use` is false, the run ends with a `ToolCallSummaryMessage`.
7. If `reflect_on_tool_use` is true, the agent performs another model inference using the tool results and then produces the final response.
8. Handoffs can interrupt this path by returning a `HandoffMessage`, optionally carrying tool-result context to the target participant.

Several important behavioral rules emerge from that design:

- AgentChat agents are stateful across calls.
- Tool use is a first-class control-flow path, not a side detail.
- Teams and handoffs exist above raw runtime routing, but they still rely on reusable message/state contracts.
- Structured output, streaming, and model-context shaping are layer-owned concerns here, not something every app must reimplement itself.

The abstract `Team` surface shows the second half of the layer’s runtime story. Teams support `reset`, `pause`, `resume`, `save_state`, and `load_state`, which means the layer treats coordinated multi-agent execution as a stateful runtime object rather than as a one-shot function.

## Variants, Boundaries, and Failure Modes

The key boundary is between **conversation ergonomics** and **runtime mechanics**. AgentChat owns the former. It does not replace Core’s responsibility for agent identity, low-level runtime hosting, or delivery contracts.

Another important boundary is between **framework abstractions** and **concrete implementations**. AgentChat defines how an assistant agent or team behaves conceptually, but provider-specific clients, MCP-backed workbenches, and concrete code-executor implementations come from [Python Extensions](python-extensions.md).

Common failure or edge conditions visible in the code and docstrings include:

- non-thread-safe use of the same agent instance across concurrent tasks
- conflicting tool and handoff naming
- tool iteration limits preventing unbounded loops
- structured-output serialization limitations
- parallel tool-call behavior depending on model-client configuration

These are high-level agent-execution concerns rather than low-level runtime-delivery errors.

## Source Files

| File | Purpose |
|------|---------|
| `python/packages/autogen-agentchat/README.md` | Positions AgentChat as the main high-level user API |
| `python/packages/autogen-agentchat/src/autogen_agentchat/agents/_assistant_agent.py` | Main assistant-agent behavior, config model, tool loop, handoffs, streaming |
| `python/packages/autogen-agentchat/src/autogen_agentchat/agents/_base_chat_agent.py` | Shared chat-agent base surface |
| `python/packages/autogen-agentchat/src/autogen_agentchat/base/_team.py` | Abstract team contract |
| `python/packages/autogen-agentchat/src/autogen_agentchat/base/_task.py` | Task-runner contract |
| `python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/` | Multi-agent group-chat implementations and orchestration patterns |
| `python/packages/autogen-agentchat/src/autogen_agentchat/tools/` | Wrappers exposing agents or teams as tools |
| `python/packages/autogen-agentchat/pyproject.toml` | Confirms the layer depends directly on `autogen-core` |

## See Also

- [Python Core Runtime](python-core-runtime.md)
- [Python Extensions](python-extensions.md)
- [Tool and Code Execution System](tool-and-code-execution-system.md)
- [Memory and Model Context](memory-and-model-context.md)
- [Layered API Architecture](../concepts/layered-api-architecture.md)
- [Tool-Augmented Agent Execution](../concepts/tool-augmented-agent-execution.md)
- [Core to AgentChat to Extension Composition](../syntheses/core-to-agentchat-to-extension-composition.md)
