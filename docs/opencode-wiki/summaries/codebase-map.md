# Codebase Map

## Overview

This map turns the opencode/ tree into a reading plan. The goal is not only to say which folder maps to which page, but to show where control flow, state, policy, and extension points live so a newcomer can read the raw repository in an order that matches the architecture.

For OpenCode, the most reliable pattern is to start with the modules that own runtime control or durable state, then move outward into adapters, protocol bridges, client shells, and examples. If you reverse that order, the repository can look broader and flatter than it really is.

## Core Runtime in `packages/opencode/src`

| Source Area | Wiki Page | How To Read It |
| --- | --- | --- |
| `cli/` and `index.ts` | [CLI Runtime](../entities/cli-runtime.md) | Entry-point parsing, bootstrap sequencing, upgrades, and terminal-facing startup. |
| `session/` | [Session System](../entities/session-system.md) | Session records, prompts, summaries, retries, messages, todo state, and compaction. |
| `tool/` | [Tool System](../entities/tool-system.md) | Built-in tools, registry wiring, schemas, and tool-specific prompt fragments. |
| `provider/` | [Provider System](../entities/provider-system.md) | Model catalogs, provider auth, transformations, and AI SDK routing. |
| `permission/` | [Permission System](../entities/permission-system.md) | Ask, allow, deny policy evaluation and approval schema handling. |
| `project/` and `worktree/` | [Project And Instance System](../entities/project-and-instance-system.md) | Project discovery, instance caching, VCS context, and bootstrap lifecycles. |
| `control-plane/` | [Control Plane And Workspaces](../entities/control-plane-and-workspaces.md) | Workspace records, remote adaptors, and synchronization-oriented control-plane types. |
| `server/` | [Server API](../entities/server-api.md) | Router composition, middleware, event projection, and public API endpoints. |
| `plugin/` | [Plugin System](../entities/plugin-system.md) | Plugin loader, installation metadata, hooks, and plugin execution context. |
| `mcp/` and `acp/` | [MCP And ACP Integration](../entities/mcp-and-acp-integration.md) | External tool-server integration and editor-facing agent bridging. |
| `storage/` and `sync/` | [Storage And Sync](../entities/storage-and-sync.md) | Database wiring, JSON migration, event persistence, and synchronization state. |
| `lsp/` | [LSP And Code Intelligence](../entities/lsp-and-code-intelligence.md) | Language-server launch, client registration, and tool-assisted code intelligence. |

## Client and Product Surfaces

| Source Area | Wiki Page | How To Read It |
| --- | --- | --- |
| `packages/app/` | [UI Client Surfaces](../entities/ui-client-surfaces.md) | Primary app surface that consumes server and runtime APIs through a product UI. |
| `packages/ui/` | [UI Client Surfaces](../entities/ui-client-surfaces.md) | Shared presentation layer and reusable UI pieces. |
| `packages/web/` and `packages/docs/` | [Multi Client Product Architecture](../syntheses/multi-client-product-architecture.md) | Browser-delivered product and documentation layers that sit on the same conceptual core. |
| `packages/desktop/` and `packages/desktop-electron/` | [Desktop And Remote Clients](../entities/desktop-and-remote-clients.md) | Desktop shells that embed or wrap the shared client experience. |
| `packages/slack/` | [Desktop And Remote Clients](../entities/desktop-and-remote-clients.md) | A remote chat surface that reuses the core agent model through another client channel. |
| `packages/sdk/` and `packages/plugin/` | [Plugin System](../entities/plugin-system.md) | Developer-facing extension surfaces for integrating with the OpenCode runtime. |

## Reading Strategy

1. Start with the source areas that own runtime control flow, persistent state, or policy decisions.
2. Read extension, plugin, protocol, or adapter directories only after the core runtime contract is clear.
3. Use client or UI packages to understand how the architecture is surfaced to users rather than where the architecture itself is defined.
4. When a behavior crosses package boundaries, jump from the mapped entity page into the relevant concept or synthesis page instead of staying directory-local.

## See Also

- [Architecture Overview](architecture-overview.md)
- [CLI Runtime](../entities/cli-runtime.md)
- [Server API](../entities/server-api.md)
- [Multi Client Product Architecture](../syntheses/multi-client-product-architecture.md)
- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [Request To Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Glossary](glossary.md)
