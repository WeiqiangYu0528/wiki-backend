# Model Client and Provider System

## Overview

The provider system in AutoGen is intentionally not embedded directly into Core or AgentChat. Instead, concrete model clients live in `autogen-ext`, where provider-specific request formats, auth conventions, streaming support, and tool-call settings can evolve without distorting the substrate. This keeps [Python Core Runtime](python-core-runtime.md) abstract and keeps [Python AgentChat](python-agentchat.md) focused on high-level agent behavior.

In practice, the provider layer is one of the most important parts of the real system because almost every user-facing AutoGen example ultimately hinges on a configured model client. The root README’s simplest quickstart already demonstrates this: create an `AssistantAgent`, then inject an `OpenAIChatCompletionClient`. The client is not a convenience detail. It is the object that turns an agent definition into an actual model-backed participant.

## Key Types

| Type | Source | Role |
|------|--------|------|
| `OpenAIChatCompletionClient` | `python/packages/autogen-ext/src/autogen_ext/models/openai/_openai_client.py` | Standard OpenAI-backed chat completion client |
| `AzureOpenAIChatCompletionClient` | same package | Azure-flavored OpenAI client |
| `BaseOpenAIChatCompletionClient` | same package | Shared base for OpenAI-like provider behavior |
| Config models | `python/packages/autogen-ext/src/autogen_ext/models/openai/config.py` | Declarative provider/client configuration |

The OpenAI package export surface in `src/autogen_ext/models/openai/__init__.py` is the clearest small snapshot of this subsystem: it exposes base and concrete clients plus configuration models instead of exposing runtime or agent abstractions directly.

## Architecture

The provider system has three main jobs.

The first is **provider-specific client behavior**. A model client translates AutoGen’s internal chat/message expectations into the concrete API calls a provider expects. This includes request formatting, streaming behavior, and any tool-call or structured-output support exposed to higher layers.

The second is **configuration and serialization**. Because AutoGen uses component models, provider clients need declarative configuration shapes. The config models exported from the OpenAI package are part of that story, and the component-schema tooling elsewhere in the repository depends on providers exposing clear component schemas.

The third is **capability surfacing to higher layers**. AgentChat relies on model-client capabilities for behaviors such as streaming, parallel tool calls, and structured output. `MagenticOne` also explicitly checks model capabilities and warns when a client may not support its preferred behaviors well.

## Runtime Behavior

At runtime, the provider system usually participates in one of two ways.

1. An AgentChat agent such as `AssistantAgent` receives a configured model client and uses it for inference during run or run-stream calls. In that flow, the provider client is the object that actually talks to the external model service.
2. A higher-level packaged system such as `MagenticOne` receives a client, validates that it supports required capabilities, and then uses it as the common model backend for multiple cooperating agents.

The important boundary is that the model client is injected. Agents and teams do not own the provider choice themselves. That keeps the rest of the stack provider-agnostic even when specific providers are the dominant examples in the repo.

## Variants, Boundaries, and Failure Modes

The optional extras in `autogen-ext/pyproject.toml` show the intended provider breadth: OpenAI, Azure, Anthropic, Gemini, Ollama, semantic-kernel variants, and more. But the tree itself suggests OpenAI and Azure remain the most mature or central paths in the current codebase.

Typical issues at this layer are provider capability mismatches, missing extras, auth/config errors, or model feature mismatches relative to what a team or agent expects. The Magentic-One implementation makes this explicit by warning when required capabilities such as function calling or JSON output are missing.

## Source Files

| File | Purpose |
|------|---------|
| `python/packages/autogen-ext/src/autogen_ext/models/openai/__init__.py` | Export surface for OpenAI/Azure clients and config models |
| `python/packages/autogen-ext/src/autogen_ext/models/openai/_openai_client.py` | Concrete provider client implementations |
| `python/packages/autogen-ext/src/autogen_ext/models/openai/config.py` | Declarative provider configuration models |
| `python/packages/autogen-ext/pyproject.toml` | Optional dependency map across providers |
| `python/packages/magentic-one-cli/src/magentic_one_cli/_m1.py` | Shows client loading from config into a packaged app |
| `python/packages/autogen-ext/src/autogen_ext/teams/magentic_one.py` | Validates provider capabilities for a complex team |

## See Also

- [Python Extensions](python-extensions.md)
- [Python AgentChat](python-agentchat.md)
- [Package and Distribution Surface](package-and-distribution-surface.md)
- [Tool-Augmented Agent Execution](../concepts/tool-augmented-agent-execution.md)
- [Core to AgentChat to Extension Composition](../syntheses/core-to-agentchat-to-extension-composition.md)
- [Package Selection and Entrypoint Flow](../syntheses/package-selection-and-entrypoint-flow.md)
