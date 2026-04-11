# Hermes Agent Codebase Map

## Overview

The easiest way to get lost in Hermes is to navigate it by folder names alone. Some of the most important runtime owners are top-level files such as `run_agent.py`, `model_tools.py`, and `hermes_state.py`. Several products then layer on top of that shared runtime: the terminal UI, the messaging gateway, cron, ACP editor integration, and research or evaluation tooling.

So the right mental model is not "start at the root and read downward." It is "pick the runtime surface you care about, then follow the owner that actually makes decisions there."

At a high level, Hermes has four kinds of repo surfaces:

- Runtime spine: the shared agent loop, provider resolution, tool dispatch, and session storage that most product surfaces reuse.
- Product shells: the CLI, gateway, cron, and ACP adapter, each of which hosts the runtime differently.
- Capability layers: tools, skills, plugins, memory providers, and execution environments that extend what the runtime can do.
- Documentation and support surfaces: the Docusaurus site, tests, scripts, packaging, and research assets that explain, verify, or distribute the system but are not usually the first implementation source of truth.

This page helps a newcomer choose a reading path. Detailed behavior lives in the entity, concept, and synthesis pages linked below.

## The Repo by Runtime Ownership

The most useful first cut is to ask which part of the repo owns runtime decisions for a given question.

| If you are asking about... | Start here in the repo | Why this is the owner | Primary wiki page |
| --- | --- | --- | --- |
| How Hermes runs a turn | `run_agent.py`, `agent/` | This is the shared execution core used by CLI, gateway, cron, and ACP-backed sessions. | [Agent Loop Runtime](../entities/agent-loop-runtime.md), [Prompt Assembly System](../entities/prompt-assembly-system.md) |
| How providers and models are chosen | `hermes_cli/runtime_provider.py`, `hermes_cli/auth.py`, `agent/model_metadata.py` | Provider resolution is shared across product surfaces, even though the code lives under CLI-owned modules. | [Provider Runtime](../entities/provider-runtime.md) |
| How tool calls become real work | `model_tools.py`, `tools/`, `toolsets.py` | Tool registration, toolset gating, approval checks, and backend handoff all meet here. | [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md), [Terminal and Execution Environments](../entities/terminal-and-execution-environments.md) |
| How sessions, history, and search persist | `hermes_state.py`, `gateway/session.py` | Hermes keeps one main persistence story, then adapts it for different surfaces. | [Session Storage](../entities/session-storage.md) |
| How the terminal app works | `cli.py`, `hermes_cli/` | The CLI is a product shell on top of the shared runtime, with its own commands, setup, callbacks, and config UX. | [CLI Runtime](../entities/cli-runtime.md), [Config and Profile System](../entities/config-and-profile-system.md) |
| How messaging platforms are hosted | `gateway/` | The gateway owns inbound events, session routing, delivery, pairing, and platform adapters. | [Gateway Runtime](../entities/gateway-runtime.md), [Messaging Platform Adapters](../entities/messaging-platform-adapters.md) |
| How scheduled automation works | `cron/`, `tools/cronjob_tools.py` | Cron is scheduled execution built on the main runtime, with its own job model and delivery rules. | [Cron System](../entities/cron-system.md) |
| How Hermes shows up inside editors | `acp_adapter/`, `acp_registry/` | ACP is the editor-facing bridge, not a new agent core. | [ACP Adapter](../entities/acp-adapter.md) |
| How memory, learning, and skills evolve behavior | `agent/`, `skills/`, `optional-skills/`, `plugins/memory/` | This is where Hermes shifts from "tool caller" to "self-improving agent with persistent guidance." | [Memory and Learning Loop](../entities/memory-and-learning-loop.md), [Skills System](../entities/skills-system.md), [Plugin and Memory Provider System](../entities/plugin-and-memory-provider-system.md) |
| How eval, batch, and RL-style environments work | `batch_runner.py`, `environments/`, `tinker-atropos/` | These surfaces reuse Hermes runtime pieces for benchmarking, data generation, and training workflows. | [Research and Batch Surfaces](../entities/research-and-batch-surfaces.md) |

That table is the main navigation trick for this repo: follow decision ownership, not just package boundaries.

## What Is Source of Truth, and What Is Supporting Surface

A newcomer often needs a second distinction: which directories define behavior, and which ones mostly explain, test, package, or expose it.

### Implementation truth

For runtime behavior, the main implementation owners are:

- top-level runtime files such as `run_agent.py`, `model_tools.py`, `hermes_state.py`, `toolsets.py`, and `batch_runner.py`
- `agent/` for prompt assembly, compression, memory orchestration, and model/runtime helpers
- `hermes_cli/` for CLI command surfaces, provider/config plumbing, setup, and shared command logic
- `tools/` for capability implementation and backend dispatch
- `gateway/`, `cron/`, and `acp_adapter/` for the long-running product shells
- `environments/` for research and evaluation environments

If you are trying to answer "what actually happens at runtime?", these are the places to trust first.

### Product and instruction surfaces

Some directories are not the runtime core, but they still shape what the agent does:

- `skills/` contains bundled skills that ship with Hermes and can be surfaced to users or injected into prompts
- `optional-skills/` contains official but not automatically installed skill packs
- `plugins/` contains plugin families, including bundled memory-provider plugins

These are closer to capability content than to core orchestration code, but still operationally important.

### Supporting surfaces

These paths are important, but usually secondary when you are tracing behavior:

- `website/docs/` is the project’s own documentation surface; useful for orientation and intended boundaries, but not the final authority when code and docs differ
- `tests/` is the best place to confirm guarantees, edge cases, and expected failure behavior
- `scripts/`, `packaging/`, `docker/`, `nix/`, and release files explain installation, shipping, and operator workflows rather than agent logic
- `landingpage/`, `assets/`, and top-level docs folders are product and presentation support, not runtime control centers

This is also how the Hermes wiki should relate to the repo. Entity pages explain implementation owners. Concept pages explain design ideas that cut across owners. Synthesis pages explain end-to-end flows that span multiple owners.

## Where To Start, Depending on Your Goal

The best entry point changes depending on what you want to learn.

### If you care about the agent runtime itself

Start with `run_agent.py`, then move into `agent/` and `model_tools.py`. That gives you the center of gravity: how Hermes builds prompts, calls providers, loops over tool calls, compresses context, and persists sessions.

Then read:

- [Agent Loop Runtime](../entities/agent-loop-runtime.md)
- [Prompt Assembly System](../entities/prompt-assembly-system.md)
- [Provider Runtime](../entities/provider-runtime.md)
- [Session Storage](../entities/session-storage.md)

### If you care about the CLI

Start with `cli.py` and `hermes_cli/main.py`, then read the surrounding modules for config, setup, callbacks, and command registration.

Then read:

- [CLI Runtime](../entities/cli-runtime.md)
- [Config and Profile System](../entities/config-and-profile-system.md)
- [CLI to Agent Loop Composition](../syntheses/cli-to-agent-loop-composition.md)

### If you care about the gateway

Start with `gateway/run.py`, `gateway/session.py`, and `gateway/delivery.py`. Then move into `gateway/platforms/` only after you understand the shared gateway routing model.

Then read:

- [Gateway Runtime](../entities/gateway-runtime.md)
- [Messaging Platform Adapters](../entities/messaging-platform-adapters.md)
- [Gateway Message to Agent Reply Flow](../syntheses/gateway-message-to-agent-reply-flow.md)

### If you care about tools and execution backends

Start with `model_tools.py`, `tools/registry.py`, `toolsets.py`, and `tools/terminal_tool.py`. Only then move into specific tool files or `tools/environments/` backends.

Then read:

- [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md)
- [Terminal and Execution Environments](../entities/terminal-and-execution-environments.md)
- [Tool Call Execution and Approval Pipeline](../syntheses/tool-call-execution-and-approval-pipeline.md)
- [Toolset-Based Capability Governance](../concepts/toolset-based-capability-governance.md)

### If you care about memory and self-improvement

Start inside `agent/`, then trace into `skills/`, `optional-skills/`, and `plugins/memory/`. Memory, skill discovery, learning, and provider-pluggable storage interact, but they do different jobs.

Then read:

- [Memory and Learning Loop](../entities/memory-and-learning-loop.md)
- [Skills System](../entities/skills-system.md)
- [Plugin and Memory Provider System](../entities/plugin-and-memory-provider-system.md)
- [Compression, Memory, and Session Search Loop](../syntheses/compression-memory-and-session-search-loop.md)

### If you care about cron, ACP, or research surfaces

These are best treated as specialized shells around the shared runtime:

- `cron/` if you care about scheduled automation and delivery routing
- `acp_adapter/` if you care about editor transport and permissions
- `batch_runner.py` and `environments/` if you care about evaluation, trajectories, or RL integration

Then read:

- [Cron System](../entities/cron-system.md)
- [ACP Adapter](../entities/acp-adapter.md)
- [Research and Batch Surfaces](../entities/research-and-batch-surfaces.md)
- [ACP Editor Session Bridge](../syntheses/acp-editor-session-bridge.md)

## How the Repo Maps to This Wiki

The repo’s own docs in `website/docs/` are the best broad orientation layer. They explain how Hermes names its subsystems and where the maintainers think the stable boundaries are. The wiki then goes one step lower and ties those boundaries back to specific implementation owners and cross-subsystem flows.

In practice:

- use repo code when you need the exact runtime truth
- use `website/docs/` when you need the project’s intended subsystem map
- use entity pages when you need one subsystem explained in implementation terms
- use concept pages when you need a cross-cutting design idea
- use synthesis pages when you need a full request or data flow traced end to end

## See Also

- [Architecture Overview](architecture-overview.md)
- [Agent Loop Runtime](../entities/agent-loop-runtime.md)
- [Gateway Runtime](../entities/gateway-runtime.md)
- [Skills System](../entities/skills-system.md)
- [Research and Batch Surfaces](../entities/research-and-batch-surfaces.md)
