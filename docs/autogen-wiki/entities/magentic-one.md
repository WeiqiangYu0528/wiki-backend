# Magentic-One

## Overview

Magentic-One is AutoGen’s packaged “applied system” surface: a concrete multi-agent composition exposed as a CLI and implemented on top of AgentChat plus Extensions. It is not a new framework layer. It is a preassembled team architecture intended to solve open-ended web, file, coding, and execution tasks with a lead orchestrator and several specialized participants.

Architecturally, Magentic-One is valuable because it shows how the lower framework layers are meant to compose into a more opinionated system. The CLI package itself is thin, while most of the actual system behavior is implemented in `autogen_ext.teams.magentic_one.MagenticOne`.

## Key Types

| Type | Source | Role |
|------|--------|------|
| `MagenticOne` | `python/packages/autogen-ext/src/autogen_ext/teams/magentic_one.py` | Packaged multi-agent group-chat composition |
| CLI entry | `python/packages/magentic-one-cli/src/magentic_one_cli/_m1.py` | User-facing launcher, config loading, and console selection |
| Participant agents | same team file plus referenced agent classes | Orchestrator, web/file surfer, coder, executor, optional user proxy |

## Architecture

Magentic-One is built as a composite rather than as one giant agent. The team class wires together:

- a file-surfer agent
- a multimodal web-surfer agent
- a coder agent
- a code-executor agent
- optionally a human user proxy

These participants are then wrapped in a group-chat orchestration layer. The docstring explains the conceptual architecture: a lead orchestrator maintains a task ledger and progress ledger, directs the other agents, re-plans when needed, and coordinates the specialized participants.

The CLI in `_m1.py` adds only a small amount of packaging logic on top:

- parse task and mode flags
- load a model-client config from YAML
- create a chat completion client from component config
- create a Docker command-line code executor
- construct `MagenticOne`
- stream output through either the simple console or rich console UI

That division of labor matters. The CLI is distribution glue; the team class is the system architecture.

## Runtime Behavior

The packaged runtime flow is:

1. The user launches `magentic-one-cli` with a task and optional flags.
2. The CLI loads model-client configuration from either a local config file or built-in sample content.
3. The CLI constructs a `ChatCompletionClient`.
4. A Docker code executor is created as the default safe execution backend.
5. `MagenticOne` builds its specialized participant list and group-chat orchestrator.
6. The task is streamed through the chosen console surface.

The team class also makes several architectural assumptions explicit:

- it prefers OpenAI-style clients and checks client capabilities
- it assumes code execution should usually be isolated
- it supports human-in-the-loop mode and explicit approval functions
- it packages multiple specialized participants into one reusable team

## Variants, Boundaries, and Failure Modes

The main boundary is that Magentic-One is an **application composition**, not a foundational runtime primitive. It depends on AgentChat and Extensions rather than replacing them.

Its most important operational tradeoff is safety. The team docstring spends significant space warning about containerization, human oversight, prompt injection, and risky actions in web and code environments. That is strong evidence that Magentic-One belongs alongside Studio and Bench as an applied surface with its own operating assumptions.

## Source Files

| File | Purpose |
|------|---------|
| `python/packages/magentic-one-cli/src/magentic_one_cli/_m1.py` | CLI launcher and config loading |
| `python/packages/autogen-ext/src/autogen_ext/teams/magentic_one.py` | Packaged team composition and architecture description |
| `python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_magentic_one/` | Underlying AgentChat support for Magentic-One group-chat patterns |
| `python/packages/autogen-ext/src/autogen_ext/agents/` | Specialized participant implementations used by the team |

## See Also

- [Python AgentChat](python-agentchat.md)
- [Python Extensions](python-extensions.md)
- [Tool and Code Execution System](tool-and-code-execution-system.md)
- [AutoGen Bench](agbench.md)
- [Tool-Augmented Agent Execution](../concepts/tool-augmented-agent-execution.md)
- [Benchmark and Agent Runtime Feedback Loop](../syntheses/benchmark-and-agent-runtime-feedback-loop.md)
- [Package Selection and Entrypoint Flow](../syntheses/package-selection-and-entrypoint-flow.md)
