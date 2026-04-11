# Glossary

## Overview

This glossary collects the recurring architecture terms in the AutoGen repository. It is not just a dictionary; each entry points toward the page where that term is explained mechanistically. Because AutoGen mixes framework layers, app surfaces, and distributed-runtime contracts, the same word can mean a public API concept in one package and a runtime ownership boundary in another. This page normalizes that vocabulary.

## Major Subsystems

| Term | Working meaning in this repo | Best entry page |
|------|------------------------------|-----------------|
| Core | The low-level runtime, ids, topics, subscriptions, serialization, and state substrate | [Python Core Runtime](../entities/python-core-runtime.md) |
| AgentChat | High-level chat-agent and team API built on Core | [Python AgentChat](../entities/python-agentchat.md) |
| Extensions | Concrete implementations of providers, tools, runtimes, memory, code executors, and specialized agents | [Python Extensions](../entities/python-extensions.md) |
| Studio | Prototyping UI application built on the framework | [AutoGen Studio](../entities/autogen-studio.md) |
| Bench | Repeatable evaluation harness for agent systems | [AutoGen Bench](../entities/agbench.md) |
| Runtime | The object or service responsible for agent lookup, delivery, state, and execution routing | [Python Core Runtime](../entities/python-core-runtime.md) |
| Worker | A process that hosts agents and registers supported agent types with a service | [Distributed Runtime and Worker System](../entities/distributed-runtime-and-worker-system.md) |
| Service | The coordinating process that places agents on workers and routes traffic | [Distributed Runtime and Worker System](../entities/distributed-runtime-and-worker-system.md) |
| CloudEvent | The canonical event envelope used in the distributed programming model | [Protocol Contracts](../entities/protocol-contracts.md) |
| Workbench | A tool-bearing environment, often used for MCP or other grouped capabilities | [Tool and Code Execution System](../entities/tool-and-code-execution-system.md) |

## Technology Stack

### Agent

An “agent” is not one class across the whole repo. In Core it means an addressable runtime participant identified by an `AgentId` and hosted by an `AgentRuntime`. In AgentChat it more often means a higher-level chat-oriented component such as `AssistantAgent` or `UserProxyAgent`. The distinction matters because AgentChat agents are built on top of a lower-level runtime concept rather than replacing it.

### Agent Runtime

The runtime is the object that owns registration, lookup, message delivery, topic publishing, and state persistence. In Python, `AgentRuntime` is a protocol in `autogen_core/_agent_runtime.py`, while `SingleThreadedAgentRuntime` is the default in-process implementation. In the distributed design docs, the runtime story expands into worker and service processes.

### AgentChat

AgentChat is the high-level API layer in `python/packages/autogen-agentchat/`. It wraps the lower-level runtime model into more direct primitives such as agents, teams, task runners, handoffs, and terminations. It is the recommended starting point for most Python users according to the package README and root README.

### Extensions

Extensions are concrete implementations maintained by the AutoGen project. The `autogen-ext` package houses provider clients, workbenches, MCP tooling, distributed runtimes, memory stores, code executors, and specialized teams or agents. “Extensions” in this repo therefore means more than third-party plugins; it is the official capability layer that turns abstract framework contracts into runnable systems.

### Workbench

A workbench is a capability surface exposed to an agent, often grouping tools or an MCP session under one abstraction. In examples, `McpWorkbench` is the most visible form. Workbenches sit between the model-facing agent logic and the concrete external capability providers.

### Model Client

A model client is the concrete implementation of chat completion or inference behavior supplied to AgentChat agents or lower-level systems. `autogen-ext.models.openai.OpenAIChatCompletionClient` is one example. The model client layer is where provider-specific auth, request formatting, streaming behavior, and tool-call settings live.

### Model Context

Model context is the object that shapes what message history or token budget is sent to the model. AgentChat’s `AssistantAgent` can use contexts such as `UnboundedChatCompletionContext`, while Core exposes a broader model-context package. This is different from “memory”: model context is immediate prompt-history shaping, while memory is usually a reusable or queryable knowledge surface.

### Memory

Memory in AutoGen can refer to explicit memory stores attached to agents, retrieval helpers, task-centric memory experiments, or broader componentized memory backends in `autogen-ext`. It is a capability layer rather than a single subsystem and often composes with model context rather than replacing it.

### Tool

A tool is a callable capability the agent may invoke during a model-guided loop. In AgentChat, tools can be passed directly to agents or wrapped in higher-level workbench constructs. Tool execution can be local, Docker-backed, Jupyter-backed, MCP-backed, or provider-backed depending on which Extension implementation is used.

### Code Executor

A code executor is a special class of tooling surface that runs generated code in a local, Docker, Jupyter, Azure, or hybrid environment. The local executor warns explicitly that it executes code on the host machine and recommends Docker as a safer default. This distinction is important when reading examples that appear to “just run code”; the execution surface is pluggable and has different risk profiles.

### Team

A team is an AgentChat abstraction representing multiple cooperating participants. The abstract `Team` base type provides methods like `reset`, `pause`, `resume`, `save_state`, and `load_state`, and concrete implementations include round-robin, selector, swarm, graph, and Magentic-One-flavored teams.

### Handoff

A handoff is an AgentChat mechanism for transferring work or control from one agent to another. In `AssistantAgent`, a handoff can be returned as a `HandoffMessage`, optionally after tool calls are executed and their results are preserved as context for the target participant.

### Termination

Termination conditions determine when a team or task runner should stop. They are part of the AgentChat coordination layer, not the low-level runtime delivery mechanism.

### CloudEvent

CloudEvents are the canonical event envelope in the distributed programming model. The design docs use CloudEvents to explain how agents subscribe to and react to event types, and `protos/cloudevent.proto` provides the shared schema used for cross-process and cross-language compatibility.

### Worker

A worker is a process that hosts application agents and registers the agent types it can support with a service process. Workers activate agent instances on demand when messages arrive for those agent ids or types.

### Service

A service is the coordinating process in the distributed worker protocol. It tracks which workers can host which agent names, chooses placement for inactive agents, and maintains the directory of active agent ids to workers.

### Protocol Contract

A protocol contract is a cross-boundary type or message definition that both implementations must honor. In AutoGen the most important examples are `agent_worker.proto` and `cloudevent.proto`. These are not optional documentation extras; they define the language-independent structure of distributed runtime communication.

### Studio Lite

Studio Lite is a lightweight AutoGen Studio mode that can launch a UI around a team definition without the full persistent app setup. Its implementation writes environment variables, may serialize a team definition into a temporary file, and launches the same web app with in-memory or lightweight defaults.

### Magentic-One

Magentic-One is a packaged multi-agent application surface built using AgentChat and Extensions. In architecture terms it is best treated as an application composition rather than a new core runtime layer.

## Entry Points for Newcomers

- Read [Architecture Overview](architecture-overview.md) for the full layered mental model.
- Read [Python Core Runtime](../entities/python-core-runtime.md) for runtime, agent, topic, and subscription terms.
- Read [Python AgentChat](../entities/python-agentchat.md) for team, handoff, termination, and assistant-agent terms.
- Read [Protocol Contracts](../entities/protocol-contracts.md) if the CloudEvent and worker/service terms are new.

## See Also

- [Architecture Overview](architecture-overview.md)
- [Python Core Runtime](../entities/python-core-runtime.md)
- [Python AgentChat](../entities/python-agentchat.md)
- [Python Extensions](../entities/python-extensions.md)
- [Distributed Runtime and Worker System](../entities/distributed-runtime-and-worker-system.md)
- [Protocol Contracts](../entities/protocol-contracts.md)
