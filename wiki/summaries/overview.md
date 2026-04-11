# Overview

## What This Wiki Covers

The **services** directory (`docs/claude_code/src/services`) is the core backend layer of Claude Code (the CLI). It contains approximately 100 TypeScript source files organized into 18 subdirectories. Each subdirectory implements one independent service — a cohesive subsystem responsible for a specific capability. Services are consumed by the query loop, tool execution pipeline, React UI components, and CLI commands.

## Major Subsystems

The services layer is organized into the following major subsystems:

| Subsystem | Directory | Role |
|-----------|-----------|------|
| [API Service](../entities/api-service.md) | `services/api/` | Anthropic model calls, retry, usage tracking |
| [MCP Service](../entities/mcp-service.md) | `services/mcp/` | External MCP tool server connections |
| [Analytics Service](../entities/analytics-service.md) | `services/analytics/` | Event logging pipeline (Datadog + 1P) |
| [Compact Service](../entities/compact-service.md) | `services/compact/` | Context window compaction |
| [OAuth Service](../entities/oauth-service.md) | `services/oauth/` | Claude.ai authentication via PKCE |
| LSP Service | `services/lsp/` | Language server protocol integration |
| Session Memory | `services/SessionMemory/` | Persistent conversation memory |
| Settings Sync | `services/settingsSync/` | Cross-environment settings synchronization |
| Plugins | `services/plugins/` | Plugin installation and marketplace management |
| Tools | `services/tools/` | Tool orchestration and execution pipeline |

## Conceptual Model

The services layer sits between raw infrastructure (filesystem, network) and higher-level application code (query loop, UI components). It exposes well-defined TypeScript APIs and avoids creating import cycles by following strict dependency rules.

Two cross-cutting patterns appear throughout the services:

1. **[Async Event Queue](../concepts/async-event-queue.md)**: The [Analytics Service](../entities/analytics-service.md) queues events before the sink is attached, then drains them on initialization. This pattern ensures no events are lost during startup and avoids blocking the startup path.

2. **[Context Window Management](../concepts/context-window-management.md)**: The [Compact Service](../entities/compact-service.md) monitors token usage and triggers compaction when thresholds are exceeded. This enables indefinitely long conversations by summarizing older context.

The services collectively enable the [request lifecycle](../syntheses/request-lifecycle.md): user input flows through the API service, tools are dispatched via the tools service, MCP extensions are managed by the MCP service, and telemetry is reported via analytics.

## Entry Points for Newcomers

- Start with [api-service.md](../entities/api-service.md) to understand how Claude model calls are made
- Read [mcp-service.md](../entities/mcp-service.md) to understand how external tools are connected
- Read [compact-service.md](../entities/compact-service.md) to understand context window lifecycle
- Read [request-lifecycle.md](../syntheses/request-lifecycle.md) to see how all services compose

## See Also

- [Glossary](glossary.md)
- [API Service](../entities/api-service.md)
- [MCP Service](../entities/mcp-service.md)
- [Analytics Service](../entities/analytics-service.md)
- [Compact Service](../entities/compact-service.md)
- [OAuth Service](../entities/oauth-service.md)
- [Request Lifecycle](../syntheses/request-lifecycle.md)
