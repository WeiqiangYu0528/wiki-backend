# Package Selection and Entrypoint Flow

## Overview

This synthesis explains how a user’s chosen install or entrypoint maps onto AutoGen’s architecture. In this repository, package selection is not just packaging trivia. It determines which layer of the system a user encounters first.

## Systems Involved

- [Package and Distribution Surface](../entities/package-and-distribution-surface.md)
- [Python AgentChat](../entities/python-agentchat.md)
- [Python Extensions](../entities/python-extensions.md)
- [AutoGen Studio](../entities/autogen-studio.md)
- [AutoGen Bench](../entities/agbench.md)
- [Magentic-One](../entities/magentic-one.md)

## Interaction Model

The entrypoint flow usually follows one of these paths:

1. **Framework builder path**
   Install `autogen-agentchat` plus one or more `autogen-ext[...]` extras.
   This leads directly into the high-level Python framework API.

2. **Compatibility path**
   Install `pyautogen`.
   This now proxies to the latest AgentChat line rather than to the old Python architecture.

3. **Prototype app path**
   Install `autogenstudio`.
   This drops the user into a UI/application layer that sits on top of the framework.

4. **Evaluation path**
   Install `agbench`.
   This leads into repeatable benchmark execution and result analysis.

5. **Packaged system path**
   Install or run `magentic-one-cli`.
   This leads into a specific multi-agent application composition rather than the generic framework.

## Key Interfaces

| Entry choice | First major architectural layer encountered |
|--------------|---------------------------------------------|
| `autogen-agentchat` | high-level framework API |
| `autogen-ext[...]` | concrete capability layer |
| `pyautogen` | compatibility/distribution wrapper into AgentChat |
| `autogenstudio` | prototyping app surface |
| `agbench` | evaluation harness |
| `magentic-one-cli` | packaged multi-agent app |

## Source Evidence

- `autogen/README.md` installation examples point users to `autogen-agentchat` plus `autogen-ext[openai]`.
- `python/packages/pyautogen/README.md` explains the proxy-package role.
- `python/packages/autogen-studio/README.md` documents Studio as a standalone installed app.
- `python/packages/agbench/README.md` documents Bench as a dedicated CLI tool.
- `python/packages/magentic-one-cli/src/magentic_one_cli/_m1.py` shows Magentic-One as a dedicated CLI entrypoint.

## See Also

- [Package and Distribution Surface](../entities/package-and-distribution-surface.md)
- [Layered API Architecture](../concepts/layered-api-architecture.md)
- [AutoGen Studio](../entities/autogen-studio.md)
- [AutoGen Bench](../entities/agbench.md)
- [Magentic-One](../entities/magentic-one.md)
- [Core to AgentChat to Extension Composition](core-to-agentchat-to-extension-composition.md)
