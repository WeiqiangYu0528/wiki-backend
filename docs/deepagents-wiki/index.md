# Deep Agents Architecture Wiki — Index

> Master catalog of the Deep Agents sub-wiki.

| Meta | Value |
|------|-------|
| **Pages** | 29 |
| **Last Updated** | 2026-04-07 |
| **Last Lint** | 2026-04-07 |

---

## Summaries

| Page | Description |
|------|-------------|
| [Architecture Overview](summaries/architecture-overview.md) | High-level orientation to the monorepo, package boundaries, and execution model |
| [Codebase Map](summaries/codebase-map.md) | Maps `libs/`, `partners/`, and `examples/` to the corresponding wiki pages |
| [Glossary](summaries/glossary.md) | Definitions for recurring Deep Agents terms and acronyms |

## Entities

| Page | Description |
|------|-------------|
| [Graph Factory](entities/graph-factory.md) | `create_deep_agent` and the default SDK graph assembly |
| [Backend System](entities/backend-system.md) | Pluggable storage and execution backends, including composite routing |
| [Subagent System](entities/subagent-system.md) | Declarative, compiled, and async subagents exposed via the `task` tool |
| [Skills System](entities/skills-system.md) | Skill discovery, metadata parsing, source precedence, and prompt injection |
| [Memory System](entities/memory-system.md) | `AGENTS.md` loading and persistent memory prompt behavior |
| [CLI Runtime](entities/cli-runtime.md) | CLI entry points, agent construction, server graph bootstrapping, and tool selection |
| [CLI Textual UI](entities/cli-textual-ui.md) | Textual application, widgets, theme handling, and message rendering |
| [Session Persistence](entities/session-persistence.md) | Thread IDs, SQLite checkpoints, metadata caches, and resume flow |
| [MCP System](entities/mcp-system.md) | MCP config discovery, validation, trust, and tool loading |
| [ACP Server](entities/acp-server.md) | Agent Client Protocol bridge for editor-hosted Deep Agents |
| [Evals System](entities/evals-system.md) | Behavioral eval framework, category taxonomy, and radar reporting |
| [Sandbox Partners](entities/sandbox-partners.md) | Daytona, Modal, Runloop, and QuickJS integrations |
| [Example Agents](entities/example-agents.md) | Examples as applied patterns for research, content, SQL, looping, and remote subagents |

## Concepts

| Page | Description |
|------|-------------|
| [Batteries Included Agent Architecture](concepts/batteries-included-agent-architecture.md) | The planning, filesystem, subagent, and prompt bundle that defines Deep Agents |
| [Filesystem First Agent Configuration](concepts/filesystem-first-agent-configuration.md) | Skills, memories, and subagents represented as files and folders |
| [Context Management and Summarization](concepts/context-management-and-summarization.md) | Auto-compaction, offloading, and context-window control |
| [Human in the Loop Approval](concepts/human-in-the-loop-approval.md) | Interrupt-on policies, shell allow-lists, and approval-sensitive operations |
| [Local vs Remote Execution](concepts/local-vs-remote-execution.md) | Local shell execution, remote sandboxes, and async remote tasks |
| [Monorepo Package Layering](concepts/monorepo-package-layering.md) | How SDK, CLI, ACP, evals, partners, and examples stack together |

## Syntheses

| Page | Description |
|------|-------------|
| [SDK to CLI Composition](syntheses/sdk-to-cli-composition.md) | How the CLI extends and configures the base SDK graph |
| [Interactive Session Lifecycle](syntheses/interactive-session-lifecycle.md) | End-to-end flow from CLI startup to persisted thread resume |
| [Agent Customization Surface](syntheses/agent-customization-surface.md) | How tools, prompts, skills, memory, subagents, and backends compose |
| [Remote Subagent and Sandbox Flow](syntheses/remote-subagent-and-sandbox-flow.md) | The path through remote backends, async tasks, ACP, and hosted servers |
| [Evaluation Feedback Loop](syntheses/evaluation-feedback-loop.md) | How the eval suite turns desired behavior into measurable architecture signals |

