# Layered API Architecture

## Overview

AutoGen is intentionally layered. The repository does not want one monolithic package that tries to satisfy every user at once. Instead, it separates substrate, high-level API, concrete integrations, and packaged applications into distinct layers with distinct ownership. The root `README.md` is explicit about this when it describes Core, AgentChat, Extensions, Studio, Bench, and Magentic-One as separate parts of the ecosystem.

## Mechanism

The layering works as follows:

1. [Python Core Runtime](../entities/python-core-runtime.md) defines the runtime substrate: agent ids, topics, subscriptions, runtimes, serialization, component config, and state contracts.
2. [Python AgentChat](../entities/python-agentchat.md) builds on top of Core and provides user-facing agents, teams, handoffs, task runners, and coordination patterns.
3. [Python Extensions](../entities/python-extensions.md) implements the concrete provider, tool, runtime, memory, and executor integrations that the upper layers need to touch real systems.
4. Application or tooling surfaces such as [AutoGen Studio](../entities/autogen-studio.md), [AutoGen Bench](../entities/agbench.md), and [Magentic-One](../entities/magentic-one.md) package those lower layers for specific use cases.

The package metadata reinforces this layering. `autogen-agentchat` depends only on `autogen-core`, while `autogen-ext` also depends on `autogen-core` and exposes many extras for concrete capabilities. Studio, Bench, and Magentic-One sit beside that stack as consumers.

## Involved Entities

- [Python Core Runtime](../entities/python-core-runtime.md)
- [Python AgentChat](../entities/python-agentchat.md)
- [Python Extensions](../entities/python-extensions.md)
- [AutoGen Studio](../entities/autogen-studio.md)
- [AutoGen Bench](../entities/agbench.md)
- [Magentic-One](../entities/magentic-one.md)

## Source Evidence

- `autogen/README.md` names the stack explicitly as Core API, AgentChat API, Extensions API, Studio, Bench, and Magentic-One.
- `python/packages/autogen-agentchat/pyproject.toml` depends on `autogen-core==0.7.5`, showing AgentChat is layered over Core.
- `python/packages/autogen-ext/pyproject.toml` depends on `autogen-core==0.7.5` and exposes many extras, showing it is the concrete integration layer rather than a new substrate.
- `python/packages/pyautogen/README.md` shows that user entrypoints can be redirected toward the higher-level AgentChat line without changing the lower layers.

## See Also

- [Architecture Overview](../summaries/architecture-overview.md)
- [Python Core Runtime](../entities/python-core-runtime.md)
- [Python AgentChat](../entities/python-agentchat.md)
- [Python Extensions](../entities/python-extensions.md)
- [Core to AgentChat to Extension Composition](../syntheses/core-to-agentchat-to-extension-composition.md)
- [Package Selection and Entrypoint Flow](../syntheses/package-selection-and-entrypoint-flow.md)
