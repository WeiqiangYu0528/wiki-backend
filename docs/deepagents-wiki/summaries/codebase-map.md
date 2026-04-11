# Codebase Map

## Overview

This map turns the deepagents/ tree into a reading plan. The goal is not only to say which folder maps to which page, but to show where control flow, state, policy, and extension points live so a newcomer can read the raw repository in an order that matches the architecture.

For Deep Agents, the most reliable pattern is to start with the modules that own runtime control or durable state, then move outward into adapters, protocol bridges, client shells, and examples. If you reverse that order, the repository can look broader and flatter than it really is.

## SDK Core

| Source Area | Wiki Page | How To Read It |
| --- | --- | --- |
| `libs/deepagents/deepagents/graph.py` | [Graph Factory](../entities/graph-factory.md) | Defines `create_deep_agent`, default prompt assembly, model resolution, and the base LangGraph compilation path. |
| `libs/deepagents/deepagents/backends/` | [Backend System](../entities/backend-system.md) | Implements state, filesystem, local-shell, composite, and sandbox-facing backends that the graph can target. |
| `libs/deepagents/deepagents/middleware/subagents.py` and `async_subagents.py` | [Subagent System](../entities/subagent-system.md) | Define synchronous and asynchronous delegation surfaces, task-tool integration, and remote execution handoff. |
| `libs/deepagents/deepagents/middleware/skills.py` | [Skills System](../entities/skills-system.md) | Loads filesystem skills and turns them into prompt and runtime augmentation. |
| `libs/deepagents/deepagents/middleware/memory.py` | [Memory System](../entities/memory-system.md) | Loads and formats `AGENTS.md` memory into the compiled agent prompt. |
| `libs/deepagents/deepagents/middleware/summarization.py` | [Context Management and Summarization](../concepts/context-management-and-summarization.md) | Owns the compaction and offload story for long-running sessions. |

## CLI and Interactive Surface

| Source Area | Wiki Page | How To Read It |
| --- | --- | --- |
| `libs/cli/deepagents_cli/main.py` | [CLI Runtime](../entities/cli-runtime.md) | Entry point for argument parsing, startup mode selection, and user-facing runtime bootstrap. |
| `libs/cli/deepagents_cli/agent.py`, `server_graph.py`, and `server.py` | [SDK To CLI Composition](../syntheses/sdk-to-cli-composition.md) | Wrap the SDK graph with CLI-specific prompts, MCP tools, server-mode behavior, and execution policy. |
| `libs/cli/deepagents_cli/app.py`, `ui.py`, and `widgets/` | [CLI Textual UI](../entities/cli-textual-ui.md) | Implement the Textual application, chat widgets, approval views, and thread navigation. |
| `libs/cli/deepagents_cli/sessions.py` and `_session_stats.py` | [Session Persistence](../entities/session-persistence.md) | Persist threads, usage statistics, and resume metadata for interactive sessions. |
| `libs/cli/deepagents_cli/mcp_tools.py` and `mcp_trust.py` | [MCP System](../entities/mcp-system.md) | Load MCP tool definitions, validate trust decisions, and expose servers to the running agent. |

## Protocol, Evaluation, and Examples

| Source Area | Wiki Page | How To Read It |
| --- | --- | --- |
| `libs/acp/deepagents_acp/server.py` | [ACP Server](../entities/acp-server.md) | Presents the SDK graph through the Agent Client Protocol for editor-hosted flows. |
| `libs/evals/deepagents_evals/` and `deepagents_harbor/` | [Evals System](../entities/evals-system.md) | Organize benchmark categories, harness integrations, radar reporting, and behavioral scoring. |
| `libs/partners/daytona`, `modal`, `runloop`, and `quickjs` | [Sandbox Partners](../entities/sandbox-partners.md) | Package remote or hosted execution adapters that let Deep Agents run beyond the local shell. |
| `examples/` | [Example Agents](../entities/example-agents.md) | Demonstrate repository-sanctioned customization patterns against realistic agent workloads. |

## Reading Strategy

1. Start with the source areas that own runtime control flow, persistent state, or policy decisions.
2. Read extension, plugin, protocol, or adapter directories only after the core runtime contract is clear.
3. Use client or UI packages to understand how the architecture is surfaced to users rather than where the architecture itself is defined.
4. When a behavior crosses package boundaries, jump from the mapped entity page into the relevant concept or synthesis page instead of staying directory-local.

## See Also

- [Architecture Overview](architecture-overview.md)
- [Graph Factory](../entities/graph-factory.md)
- [Example Agents](../entities/example-agents.md)
- [Interactive Session Lifecycle](../syntheses/interactive-session-lifecycle.md)
- [Batteries Included Agent Architecture](../concepts/batteries-included-agent-architecture.md)
- [Sdk To Cli Composition](../syntheses/sdk-to-cli-composition.md)
- [Glossary](glossary.md)
