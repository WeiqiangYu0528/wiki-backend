# Claude Code Architecture Wiki — Index

> Master catalog of all Claude Code wiki pages.

| Meta | Value |
|------|-------|
| **Pages** | 35 |
| **Last Updated** | 2026-04-06 |
| **Last Lint** | 2026-04-06 |

---

## Summaries

| Page | Description |
|------|-------------|
| [Architecture Overview](summaries/architecture-overview.md) | High-level overview of Claude Code: purpose, subsystems, execution model, tech stack |
| [Codebase Map](summaries/codebase-map.md) | Maps every `src/` directory and root file to its purpose and wiki page |
| [Glossary](summaries/glossary.md) | Definitions of ~40 domain-specific terms with cross-references |

## Entities

| Page | Description |
|------|-------------|
| [Agent System](entities/agent-system.md) | Agent definitions, lifecycle, isolation, memory scopes, built-in agents |
| [Bridge System](entities/bridge-system.md) | CLI-to-web remote control, session management, poll-based events |
| [Command System](entities/command-system.md) | 100+ slash commands, feature-flag gating, command lifecycle |
| [Configuration System](entities/configuration-system.md) | Settings hierarchy, CLAUDE.md memory files, @include directives |
| [MCP System](entities/mcp-system.md) | Model Context Protocol servers, tool discovery, OAuth, transport layers |
| [Memory System](entities/memory-system.md) | Memdir module, team memory sync, auto-extraction, agent memory scopes |
| [Permission System](entities/permission-system.md) | Permission modes, layered rules, classifiers, denial tracking |
| [Plugin System](entities/plugin-system.md) | Built-in and marketplace plugins, extension points, lifecycle |
| [Query Engine](entities/query-engine.md) | Streaming query loop, tool dispatch, compaction, budget enforcement |
| [Skill System](entities/skill-system.md) | Inline/fork execution, skill sources, frontmatter schema, permissions |
| [State Management](entities/state-management.md) | AppState (~250 fields), Zustand-like store, React context, selectors |
| [Task System](entities/task-system.md) | 7 task types, lifecycle states, persistence, cleanup |
| [Tool System](entities/tool-system.md) | ~50 built-in tools, Tool interface, permission gating, deferred loading |

## Concepts

| Page | Description |
|------|-------------|
| [Agent Isolation](concepts/agent-isolation.md) | File cache cloning, worktrees, MCP scoping, state merge-back |
| [Compaction and Context Management](concepts/compaction-and-context-management.md) | Auto-compaction, microcompact, reactive compact, context window limits |
| [Error Handling Patterns](concepts/error-handling-patterns.md) | Retry logic, abort handling, prompt-too-long recovery, error hierarchy |
| [Execution Flow](concepts/execution-flow.md) | End-to-end from user input through query loop to response |
| [Frontmatter Conventions](concepts/frontmatter-conventions.md) | Markdown frontmatter for agents and skills, all parsed fields |
| [Hook System](concepts/hook-system.md) | React hooks, frontmatter hooks, tool permission pipeline, event table |
| [Message Types and Streaming](concepts/message-types-and-streaming.md) | Message hierarchy, streaming events, API-to-UI flow |
| [Permission Model](concepts/permission-model.md) | Philosophy of layered allow/deny/ask, classifier pipeline |
| [Session Lifecycle](concepts/session-lifecycle.md) | Bootstrap, persistence, transcript recording, recovery, backgrounding |
| [Settings Hierarchy](concepts/settings-hierarchy.md) | Resolution chain: managed → policy → user → project → local → flags |
| [Tool Permission Gating](concepts/tool-permission-gating.md) | Per-tool-call permission checking, CanUseToolFn, validators |

## Syntheses

| Page | Description |
|------|-------------|
| [Agent-Tool-Skill Triad](syntheses/agent-tool-skill-triad.md) | Recursive execution: Agent → Tool → Skill → Agent |
| [Configuration Resolution Chain](syntheses/configuration-resolution-chain.md) | Full settings merge story across all sources and scopes |
| [MCP Integration Architecture](syntheses/mcp-integration-architecture.md) | How MCP connects to tools, agents, auth, and configuration |
| [Permission Enforcement Pipeline](syntheses/permission-enforcement-pipeline.md) | Rules → parsing → classification → hooks → UI → tracking |
| [Plugin Extension Model](syntheses/plugin-extension-model.md) | How plugins extend tools, commands, skills, agents, hooks |
| [Query Loop Orchestration](syntheses/query-loop-orchestration.md) | QueryEngine + tools + permissions + compaction state machine |
| [State-Driven Rendering](syntheses/state-driven-rendering.md) | AppState → selectors → Ink terminal UI rendering |
| [Task Execution and Isolation](syntheses/task-execution-and-isolation.md) | How different task types run, persist output, and isolate |

## Reference

- [Log](log.md)
- [Schema](schema.md)
