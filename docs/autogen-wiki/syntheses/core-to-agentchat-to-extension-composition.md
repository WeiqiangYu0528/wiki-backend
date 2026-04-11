# Core to AgentChat to Extension Composition

## Overview

This synthesis explains the main Python architecture path in AutoGen: Core defines the substrate, AgentChat packages that substrate into user-facing agent and team abstractions, and Extensions supplies the concrete capabilities that make those abstractions runnable against real providers and environments. The three layers are deliberately separated so that each one can stay focused on one class of concern.

## Systems Involved

- [Python Core Runtime](../entities/python-core-runtime.md)
- [Python AgentChat](../entities/python-agentchat.md)
- [Python Extensions](../entities/python-extensions.md)
- [Model Client and Provider System](../entities/model-client-and-provider-system.md)
- [Tool and Code Execution System](../entities/tool-and-code-execution-system.md)

## Interaction Model

The composition path usually looks like this:

1. Core defines ids, runtimes, message delivery, subscriptions, component config, memory, and model-context abstractions.
2. AgentChat defines higher-level agents and teams in terms of those abstractions.
3. Extensions provides the concrete model clients, tools, workbenches, code executors, runtimes, and memory backends used by those agents and teams.
4. An application then instantiates an AgentChat agent or team, injects Extension components, and runs the system.

The root README quickstarts show this clearly. The user creates an `AssistantAgent` from AgentChat, then injects an `OpenAIChatCompletionClient` from Extensions. The agent’s internal logic still uses Core types such as messages, cancellation tokens, contexts, and component models.

## Key Interfaces

| Boundary | Interface or artifact |
|----------|-----------------------|
| Core -> AgentChat | runtime, message, context, and component abstractions |
| AgentChat -> Extensions | injected model clients, tools, workbenches, code executors, memory stores |
| Application -> AgentChat | `run()` / `run_stream()` and team/task-runner APIs |

## Source Evidence

- `autogen/README.md` explicitly names Core API, AgentChat API, and Extensions API as layers.
- `python/packages/autogen-agentchat/pyproject.toml` depends directly on `autogen-core`.
- `python/packages/autogen-ext/pyproject.toml` depends on `autogen-core` and exposes optional extras for concrete integrations.
- `python/packages/autogen-agentchat/src/autogen_agentchat/agents/_assistant_agent.py` imports model-context, memory, model, and tool abstractions from Core and expects concrete model/tool implementations to be injected.

## See Also

- [Python Core Runtime](../entities/python-core-runtime.md)
- [Python AgentChat](../entities/python-agentchat.md)
- [Python Extensions](../entities/python-extensions.md)
- [Layered API Architecture](../concepts/layered-api-architecture.md)
- [Tool-Augmented Agent Execution](../concepts/tool-augmented-agent-execution.md)
- [Package Selection and Entrypoint Flow](package-selection-and-entrypoint-flow.md)
