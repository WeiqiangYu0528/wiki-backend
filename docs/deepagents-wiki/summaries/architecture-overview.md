# Architecture Overview

## Overview

[Deep Agents](../entities/graph-factory.md) is a Python monorepo that packages an opinionated agent harness and several higher-level surfaces around it. The core claim is that a "deep" agent needs more than just tool-calling: it needs explicit planning, filesystem access, subagent delegation, and strong prompts bundled together as defaults. The repository implements that in the SDK, then layers a full terminal [CLI Runtime](../entities/cli-runtime.md), an editor-facing [ACP Server](../entities/acp-server.md), an [Evals System](../entities/evals-system.md), provider-specific [Sandbox Partners](../entities/sandbox-partners.md), and several [Example Agents](../entities/example-agents.md).

Deep Agents is organized around a deliberately opinionated SDK core rather than a thin framework shell. The monorepo assumes that a useful coding or research agent needs planning, file manipulation, summarization, and delegation wired together before any product-specific customization begins. That assumption explains why the SDK, CLI, ACP bridge, evaluation harness, and partner backends all cluster around the same `create_deep_agent` assembly path.
The project is also unusually filesystem-oriented. Skills are loaded from `SKILL.md`, persistent instructions from `AGENTS.md`, and many customization surfaces can be moved between local projects, remote sandboxes, and example agents without repackaging Python code. The result is a system that tries to make agent behavior portable and inspectable even when the execution environment changes.

## Major Subsystems

| Subsystem | Why It Matters |
| --- | --- |
| [Graph Factory](../entities/graph-factory.md) | `create_deep_agent` and the default SDK graph assembly |
| [Backend System](../entities/backend-system.md) | Pluggable storage and execution backends, including composite routing |
| [Subagent System](../entities/subagent-system.md) | Declarative, compiled, and async subagents exposed via the `task` tool |
| [Skills System](../entities/skills-system.md) | Skill discovery, metadata parsing, source precedence, and prompt injection |
| [Memory System](../entities/memory-system.md) | `AGENTS.md` loading and persistent memory prompt behavior |
| [CLI Runtime](../entities/cli-runtime.md) | CLI entry points, agent construction, server graph bootstrapping, and tool selection |
| [CLI Textual UI](../entities/cli-textual-ui.md) | Textual application, widgets, theme handling, and message rendering |
| [Session Persistence](../entities/session-persistence.md) | Thread IDs, SQLite checkpoints, metadata caches, and resume flow |
| [MCP System](../entities/mcp-system.md) | MCP config discovery, validation, trust, and tool loading |
| [ACP Server](../entities/acp-server.md) | Agent Client Protocol bridge for editor-hosted Deep Agents |
| [Evals System](../entities/evals-system.md) | Behavioral eval framework, category taxonomy, and radar reporting |
| [Sandbox Partners](../entities/sandbox-partners.md) | Daytona, Modal, Runloop, and QuickJS integrations |

## Execution Model

The repository should be read as one architecture with several surfaces rather than a loose collection of packages. Deep Agents keeps its center of gravity in the runtime modules that decide state, policy, and execution, then layers user-facing shells or protocol adapters on top of that shared core.

1. The runtime starts in the SDK graph factory, where model resolution, default middleware, filesystem-aware prompt building, and delegation surfaces are compiled into a LangGraph agent.
2. The CLI and ACP layers then wrap that compiled graph with human-facing concerns: approvals, MCP loading, session persistence, interactive rendering, and protocol-specific transport concerns.
3. Remote backends and partner packages extend the same graph contract into hosted sandboxes or async execution environments instead of defining a separate agent architecture.
4. Evals and examples close the loop by exercising the exact same runtime shape under benchmark and tutorial conditions.

## Architectural Themes

| Theme | What It Explains |
| --- | --- |
| [Batteries Included Agent Architecture](../concepts/batteries-included-agent-architecture.md) | The project ships a default agent opinion instead of only primitives. |
| [Filesystem First Agent Configuration](../concepts/filesystem-first-agent-configuration.md) | Skills, memories, and subagents are all represented as files and folders. |
| [Context Management And Summarization](../concepts/context-management-and-summarization.md) | Long runs rely on compaction and offloading rather than ever-growing prompts. |
| [Local Vs Remote Execution](../concepts/local-vs-remote-execution.md) | The same agent shape can target local shells, remote sandboxes, or async subagents. |
| [Monorepo Package Layering](../concepts/monorepo-package-layering.md) | SDK, CLI, ACP, evals, and partner packages are intentionally stacked around one runtime core. |

## Entry Points For Newcomers

Start with [Graph Factory](../entities/graph-factory.md) for the default runtime contract, [CLI Runtime](../entities/cli-runtime.md) for product-facing behavior, and [Agent Customization Surface](../syntheses/agent-customization-surface.md) for how skills, memory, tools, subagents, and backends actually compose.

The most useful reading order is usually summary, then hub entity, then synthesis. That sequence lets a newcomer first understand the system boundary, then inspect the runtime owner for a given concern, then see how that concern composes with its neighboring systems.

## See Also

- [Codebase Map](codebase-map.md)
- [Graph Factory](../entities/graph-factory.md)
- [CLI Runtime](../entities/cli-runtime.md)
- [Monorepo Package Layering](../concepts/monorepo-package-layering.md)
- [Batteries Included Agent Architecture](../concepts/batteries-included-agent-architecture.md)
- [Sdk To Cli Composition](../syntheses/sdk-to-cli-composition.md)
- [Glossary](glossary.md)
