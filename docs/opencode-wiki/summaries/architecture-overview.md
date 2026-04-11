# Architecture Overview

## Overview

OpenCode is an open source AI coding agent built as a Bun/TypeScript monorepo. The core runtime lives in [`packages/opencode`](../entities/cli-runtime.md), but the repository is intentionally broader than a single CLI. It includes a provider-agnostic agent engine, a TUI-focused CLI, a local/remote server layer, project-scoped runtime state, plugin and MCP/ACP integrations, and several client surfaces including app, web, desktop, Slack, and SDK packages.

OpenCode is best read as a shared agent runtime with many delivery surfaces layered around it. The repository contains a TUI CLI, HTTP server, workspace and control-plane logic, desktop shells, web and docs packages, a Slack surface, and a plugin and SDK layer, but those products are not independent implementations. They all reuse the same session engine, provider routing, tool registry, project scoping, and persistence story in `packages/opencode/src`.
That shared core makes the codebase denser than a conventional CLI repo. A user-visible feature often crosses several packages: project bootstrap establishes workspace state, the session system picks prompts and manages compaction, the provider layer resolves model SDKs, the tool layer governs external actions, and storage and sync surfaces persist the resulting event stream. The wiki therefore has to explain composition, not just packages.

## Major Subsystems

| Subsystem | Why It Matters |
| --- | --- |
| [CLI Runtime](../entities/cli-runtime.md) | Root command entry point, bootstrap, one-time migration flow, and command surface |
| [Session System](../entities/session-system.md) | Session records, prompt selection, messages, compaction, retries, and summaries |
| [Tool System](../entities/tool-system.md) | Tool registry, built-in tool catalog, plugin tools, and model-sensitive tool selection |
| [Provider System](../entities/provider-system.md) | Provider/model loading, auth integration, and AI SDK routing |
| [Permission System](../entities/permission-system.md) | Ask/allow/deny rules, permission requests, and approval lifecycle |
| [Project and Instance System](../entities/project-and-instance-system.md) | Project discovery, worktree context, bootstrap, and instance scoping |
| [Control Plane and Workspaces](../entities/control-plane-and-workspaces.md) | Workspace model, adaptors, remote routing, and SSE syncing |
| [Server API](../entities/server-api.md) | Hono server, middleware, OpenAPI generation, and routed APIs |
| [Plugin System](../entities/plugin-system.md) | Internal and external plugin loading, hooks, and SDK-backed plugin context |
| [MCP and ACP Integration](../entities/mcp-and-acp-integration.md) | MCP client management and ACP editor-facing agent bridge |
| [LSP and Code Intelligence](../entities/lsp-and-code-intelligence.md) | LSP clients, launch flow, and LSP-backed tools |
| [Storage and Sync](../entities/storage-and-sync.md) | JSON migration, persistence, event sourcing, and synchronization |

## Execution Model

The repository should be read as one architecture with several surfaces rather than a loose collection of packages. OpenCode keeps its center of gravity in the runtime modules that decide state, policy, and execution, then layers user-facing shells or protocol adapters on top of that shared core.

1. A request typically enters through the CLI or server, but both paths converge on project-scoped instances, session state, provider routing, and the tool registry in `packages/opencode/src`.
2. The session system owns prompt selection, summaries, compaction, retries, and message state, which makes it the durable core of the runtime rather than a lightweight chat log.
3. Provider, permission, plugin, and LSP services then shape what actions are possible in the current run, while storage and sync ensure the resulting state can be restored and projected into different clients.
4. App, desktop, web, Slack, and SDK surfaces reuse that runtime model instead of reimplementing their own agent loops.

## Architectural Themes

| Theme | What It Explains |
| --- | --- |
| [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md) | One runtime serves many clients and entry points. |
| [Provider Agnostic Model Routing](../concepts/provider-agnostic-model-routing.md) | Model choice is normalized behind provider abstractions instead of being hardcoded by surface. |
| [Project Scoped Instance Lifecycle](../concepts/project-scoped-instance-lifecycle.md) | Project directories are durable runtime boundaries. |
| [Permission And Approval Gating](../concepts/permission-and-approval-gating.md) | Tool calls are shaped by explicit policy rather than ad hoc prompts. |
| [Plugin Driven Extensibility](../concepts/plugin-driven-extensibility.md) | Hooks and plugins extend the runtime without forking the core execution path. |

## Entry Points For Newcomers

Start with [CLI Runtime](../entities/cli-runtime.md), [Session System](../entities/session-system.md), [Tool System](../entities/tool-system.md), and [Control Plane And Workspaces](../entities/control-plane-and-workspaces.md). Together they explain most user-visible runtime behavior.

The most useful reading order is usually summary, then hub entity, then synthesis. That sequence lets a newcomer first understand the system boundary, then inspect the runtime owner for a given concern, then see how that concern composes with its neighboring systems.

## See Also

- [Codebase Map](codebase-map.md)
- [CLI Runtime](../entities/cli-runtime.md)
- [Session System](../entities/session-system.md)
- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [Request To Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Glossary](glossary.md)
