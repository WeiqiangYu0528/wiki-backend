# OpenCode Architecture Wiki — Index

> Master catalog of the OpenCode sub-wiki.

| Meta | Value |
|------|-------|
| **Pages** | 28 |
| **Last Updated** | 2026-04-06 |
| **Last Lint** | 2026-04-06 |

---

## Summaries

| Page | Description |
|------|-------------|
| [Architecture Overview](summaries/architecture-overview.md) | High-level orientation to the OpenCode monorepo, package boundaries, and runtime model |
| [Codebase Map](summaries/codebase-map.md) | Maps `packages/`, `sdks/`, and the core source tree to wiki pages |
| [Glossary](summaries/glossary.md) | Definitions for recurring OpenCode terms and acronyms |

## Entities

| Page | Description |
|------|-------------|
| [CLI Runtime](entities/cli-runtime.md) | Root command entry point, bootstrap, one-time migration flow, and command surface |
| [Session System](entities/session-system.md) | Session records, prompt selection, messages, compaction, retries, and summaries |
| [Tool System](entities/tool-system.md) | Tool registry, built-in tool catalog, plugin tools, and model-sensitive tool selection |
| [Provider System](entities/provider-system.md) | Provider/model loading, auth integration, and AI SDK routing |
| [Permission System](entities/permission-system.md) | Ask/allow/deny rules, permission requests, and approval lifecycle |
| [Project and Instance System](entities/project-and-instance-system.md) | Project discovery, worktree context, bootstrap, and instance scoping |
| [Control Plane and Workspaces](entities/control-plane-and-workspaces.md) | Workspace model, adaptors, remote routing, and SSE syncing |
| [Server API](entities/server-api.md) | Hono server, middleware, OpenAPI generation, and routed APIs |
| [Plugin System](entities/plugin-system.md) | Internal and external plugin loading, hooks, and SDK-backed plugin context |
| [MCP and ACP Integration](entities/mcp-and-acp-integration.md) | MCP client management and ACP editor-facing agent bridge |
| [LSP and Code Intelligence](entities/lsp-and-code-intelligence.md) | LSP clients, launch flow, and LSP-backed tools |
| [Storage and Sync](entities/storage-and-sync.md) | JSON migration, persistence, event sourcing, and synchronization |
| [UI Client Surfaces](entities/ui-client-surfaces.md) | Shared app/UI/web layers above the core runtime |
| [Desktop and Remote Clients](entities/desktop-and-remote-clients.md) | Desktop shells, Slack, VS Code SDK, and other client surfaces |

## Concepts

| Page | Description |
|------|-------------|
| [Client Server Agent Architecture](concepts/client-server-agent-architecture.md) | OpenCode core service with multiple clients layered on top |
| [Provider Agnostic Model Routing](concepts/provider-agnostic-model-routing.md) | Uniform model selection across many provider SDKs |
| [Project Scoped Instance Lifecycle](concepts/project-scoped-instance-lifecycle.md) | Per-directory runtime scoping, bootstrapping, and disposal |
| [Permission and Approval Gating](concepts/permission-and-approval-gating.md) | Allow/deny/ask flow for tool execution |
| [Tool and Agent Composition](concepts/tool-and-agent-composition.md) | Build/plan agents, task delegation, and tool orchestration |
| [Plugin Driven Extensibility](concepts/plugin-driven-extensibility.md) | Hook-based extension through internal and external plugins |

## Syntheses

| Page | Description |
|------|-------------|
| [Request to Session Execution Flow](syntheses/request-to-session-execution-flow.md) | How CLI/server requests become session-level model and tool activity |
| [Workspace Routing and Remote Control](syntheses/workspace-routing-and-remote-control.md) | Local vs remote workspaces, adaptors, and forwarded requests |
| [Multi Client Product Architecture](syntheses/multi-client-product-architecture.md) | TUI, app, web, desktop, Slack, and SDK surfaces around one core |
| [Context Compaction and Session Recovery](syntheses/context-compaction-and-session-recovery.md) | Prompt variants, summaries, compaction, retry, and restore behavior |
| [Provider Tool Plugin Interaction Model](syntheses/provider-tool-plugin-interaction-model.md) | How providers, tools, plugins, and permissions shape execution |

