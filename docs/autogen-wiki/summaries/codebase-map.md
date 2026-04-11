# Codebase Map

## Overview

The `autogen/` repository is organized around a layered architecture rather than around one product binary. The fastest way to read the tree is to separate it into four zones: Python framework packages, application/tooling packages, shared design/protocol material, and the .NET implementation surface. That split matters because many directories that look adjacent on disk are architecturally at different heights. For example, `autogen-core` and `autogen-agentchat` are framework layers; `autogen-studio` and `agbench` are applications built on those layers; `protos/` is a contract layer that informs both Python and .NET distributed runtimes; and `dotnet/src` contains both older packages and a newer event-driven stack.

## Major Subsystems

| Repo area | Key paths | Wiki pages |
|-----------|-----------|------------|
| Python framework core | `python/packages/autogen-core/` | [Python Core Runtime](../entities/python-core-runtime.md), [Memory and Model Context](../entities/memory-and-model-context.md) |
| Python high-level API | `python/packages/autogen-agentchat/` | [Python AgentChat](../entities/python-agentchat.md), [Layered API Architecture](../concepts/layered-api-architecture.md) |
| Python extensions | `python/packages/autogen-ext/` | [Python Extensions](../entities/python-extensions.md), [Model Client and Provider System](../entities/model-client-and-provider-system.md), [Tool and Code Execution System](../entities/tool-and-code-execution-system.md) |
| Application surfaces | `python/packages/autogen-studio/`, `python/packages/agbench/`, `python/packages/magentic-one-cli/` | [AutoGen Studio](../entities/autogen-studio.md), [AutoGen Bench](../entities/agbench.md), [Magentic-One](../entities/magentic-one.md) |
| Package and tooling wrappers | `python/packages/pyautogen/`, `component-schema-gen/`, `autogen-test-utils/` | [Package and Distribution Surface](../entities/package-and-distribution-surface.md), [Component Schema and Test Tooling](../entities/component-schema-and-test-tooling.md) |
| Design and protocol docs | `docs/design/`, `protos/` | [Distributed Runtime and Worker System](../entities/distributed-runtime-and-worker-system.md), [Protocol Contracts](../entities/protocol-contracts.md) |
| .NET runtime stack | `dotnet/src/` | [Dotnet Runtime Stack](../entities/dotnet-runtime-stack.md), [Python and Dotnet Ecosystem Relationship](../syntheses/python-and-dotnet-ecosystem-relationship.md) |

## Execution Model

The top-level `README.md` is the best architectural index because it already presents the intended stack in dependency order. It sends new users toward `autogen-agentchat` plus a provider implementation from `autogen-ext`, then broadens the picture by naming Core, AgentChat, Extensions, Studio, Bench, and Magentic-One as separate pieces of one ecosystem. That README is a better map than a plain file listing because it shows which packages are “framework,” which are “developer tools,” and which are “applications.”

Inside `python/packages/`, the layout reinforces that stack:

- `autogen-core/` is the foundational runtime and shared type layer.
- `autogen-agentchat/` is the high-level multi-agent API.
- `autogen-ext/` is the concrete integration layer.
- `autogen-studio/`, `agbench/`, and `magentic-one-cli/` are end-user or developer-facing surfaces built on the framework.
- `pyautogen/` is effectively a distribution convenience package that points users back to AgentChat.
- `component-schema-gen/` and `autogen-test-utils/` are tooling packages rather than end-user runtime layers.

That means the Python tree is not a random collection of packages. It is a deliberate progression from substrate to API to integrations to packaged applications.

## Package-by-Package Orientation

### `python/packages/autogen-core/`

This is the runtime substrate. The exported names in `src/autogen_core/__init__.py` tell you the main conceptual surface: `AgentRuntime`, `SingleThreadedAgentRuntime`, `AgentId`, `AgentType`, `TopicId`, `Subscription`, `RoutedAgent`, serialization helpers, component config helpers, model-context helpers, memory support, and telemetry. Files worth starting from:

- `src/autogen_core/_agent_runtime.py`
- `src/autogen_core/_single_threaded_agent_runtime.py`
- `src/autogen_core/_routed_agent.py`
- `src/autogen_core/_subscription.py`
- `src/autogen_core/_topic.py`

This package maps most directly to [Python Core Runtime](../entities/python-core-runtime.md) and the concepts around [event-driven agent programming](../concepts/event-driven-agent-programming-model.md).

### `python/packages/autogen-agentchat/`

This package is the recommended user entry point. Its top-level README says exactly that. The important internal areas are:

- `agents/` for concrete agent types such as `AssistantAgent`, `UserProxyAgent`, `CodeExecutorAgent`, and `SocietyOfMindAgent`
- `teams/` for team and group-chat patterns including round-robin, selector, swarm, graph, and Magentic-One variants
- `base/` for task runners, handoffs, teams, and termination contracts
- `tools/` for wrapping agents and teams as tools
- `messages.py` and `state/` for the message and state surfaces exposed to users

This area feeds [Python AgentChat](../entities/python-agentchat.md), [Tool-Augmented Agent Execution](../concepts/tool-augmented-agent-execution.md), and [Core to AgentChat to Extension Composition](../syntheses/core-to-agentchat-to-extension-composition.md).

### `python/packages/autogen-ext/`

This is the broadest package tree because it houses concrete integrations. The directory and optional dependencies show the architectural clusters:

- `models/` for provider clients such as OpenAI and Azure
- `tools/` including MCP support
- `code_executors/` for local, Docker, Jupyter, Azure, and Docker-Jupyter execution
- `memory/` and `experimental/task_centric_memory/`
- `runtimes/grpc/` for distributed runtime implementations
- `agents/` and `teams/` for specialized higher-level components

This package is the raw material for [Python Extensions](../entities/python-extensions.md), [Model Client and Provider System](../entities/model-client-and-provider-system.md), and [Tool and Code Execution System](../entities/tool-and-code-execution-system.md).

### `python/packages/autogen-studio/`

This package is an application, not a framework layer. It contains:

- `autogenstudio/web/` for the FastAPI app and routes
- `autogenstudio/database/` and `datamodel/` for persistence and schema
- `autogenstudio/lite/` for the lightweight in-memory or file-backed Studio mode
- `autogenstudio/mcp/` for MCP integration
- `frontend/` for the web UI build

It maps to [AutoGen Studio](../entities/autogen-studio.md) and [Studio on Top of Framework Flow](../syntheses/studio-on-top-of-framework-flow.md).

### `python/packages/agbench/`

`agbench` is another application/tooling surface. The package contains the CLI, task-runner commands, templates, and benchmark assets under `benchmarks/`. It should be read as a controlled-experiment harness, not as part of the main runtime substrate. It maps to [AutoGen Bench](../entities/agbench.md) and [Benchmark-Driven Agent Evaluation](../concepts/benchmark-driven-agent-evaluation.md).

### `python/packages/magentic-one-cli/`

This package is thin on its own because much of the behavior lives in AgentChat and Extensions. The important point is architectural role: it is a packaged agent system, not a new framework layer. That is why it belongs next to Studio and Bench in the wiki rather than next to Core or AgentChat.

### `docs/design/` and `protos/`

These directories define the conceptual and wire-level distributed runtime model.

- `docs/design/01 - Programming Model.md` explains publish-subscribe, CloudEvents, handlers, and orchestrators.
- `docs/design/03 - Agent Worker Protocol.md` explains service processes, worker processes, agent placement, and worker lifecycle.
- `protos/agent_worker.proto` and `protos/cloudevent.proto` define the canonical wire contracts.

These areas ground [Distributed Runtime and Worker System](../entities/distributed-runtime-and-worker-system.md), [Protocol Contracts](../entities/protocol-contracts.md), and [Protocol-Mediated Cross-Language Runtime](../concepts/protocol-mediated-cross-language-runtime.md).

### `dotnet/src/`

This tree is bifurcated.

- The older `AutoGen.*` packages keep the earlier .NET agent/chat/middleware/orchestrator style alive.
- The newer `Microsoft.AutoGen.*` packages add event-driven contracts, in-process and gRPC runtimes, runtime gateway services, agent hosts, and a more explicit alignment with the shared protocol model.

That split is essential to [Dotnet Runtime Stack](../entities/dotnet-runtime-stack.md) and the [Python and Dotnet Ecosystem Relationship](../syntheses/python-and-dotnet-ecosystem-relationship.md) synthesis.

## Architectural Themes

The map that emerges from the tree is less “one package depends on everything else” and more “many consumers sit on a narrow substrate.” Core stays conceptually small and abstract. AgentChat stays higher-level and still mostly abstract. Extensions explodes in breadth because it is where concrete providers, runtimes, and environment bindings live. Applications and tools then compose those pieces into user-facing systems.

The second important theme is that `docs/` and `protos/` are first-class architecture sources, not only documentation extras. They contain information that is not obvious from package APIs alone, especially around the distributed worker/service runtime and CloudEvents-based execution model.

## Entry Points for Newcomers

- Read [Architecture Overview](architecture-overview.md) first for the layered mental model.
- Go to [Python Core Runtime](../entities/python-core-runtime.md) if you need the substrate.
- Go to [Python AgentChat](../entities/python-agentchat.md) if you want the main developer-facing API.
- Go to [Python Extensions](../entities/python-extensions.md) if you need concrete providers, tools, runtimes, or code executors.
- Go to [AutoGen Studio](../entities/autogen-studio.md) or [AutoGen Bench](../entities/agbench.md) if you care about app/tool surfaces.
- Go to [Dotnet Runtime Stack](../entities/dotnet-runtime-stack.md) if your entry point is .NET rather than Python.

## See Also

- [Architecture Overview](architecture-overview.md)
- [Python Core Runtime](../entities/python-core-runtime.md)
- [Python AgentChat](../entities/python-agentchat.md)
- [Python Extensions](../entities/python-extensions.md)
- [Distributed Runtime and Worker System](../entities/distributed-runtime-and-worker-system.md)
- [Dotnet Runtime Stack](../entities/dotnet-runtime-stack.md)
- [Layered API Architecture](../concepts/layered-api-architecture.md)
