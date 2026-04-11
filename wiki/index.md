# Wiki Index

Master catalog of all pages in the Claude Code Services wiki.

**Source:** `docs/claude_code/src/services`
**Built:** 2026-04-06

---

## Infrastructure

| Page | Description |
|------|-------------|
| [schema.md](schema.md) | Governance: page templates, naming conventions, cross-referencing rules |
| [index.md](index.md) | This file — master catalog |
| [log.md](log.md) | Append-only operation log |

---

## Summaries

| Page | Description |
|------|-------------|
| [overview.md](summaries/overview.md) | High-level orientation: what the services layer is, its major subsystems, and conceptual model |
| [glossary.md](summaries/glossary.md) | Domain-specific terms defined and linked to their most relevant wiki pages |

---

## Entities

| Page | Description |
|------|-------------|
| [api-service.md](entities/api-service.md) | The core API gateway — calls Anthropic models, manages request lifecycle, retry, and usage tracking |
| [mcp-service.md](entities/mcp-service.md) | Model Context Protocol service — manages connections to external MCP tool servers |
| [analytics-service.md](entities/analytics-service.md) | Analytics event pipeline — routes events to Datadog and first-party logging |
| [compact-service.md](entities/compact-service.md) | Context window compaction — automatically summarizes conversations to prevent token overflows |
| [oauth-service.md](entities/oauth-service.md) | OAuth 2.0 with PKCE authentication — handles Claude.ai login flow |

---

## Concepts

| Page | Description |
|------|-------------|
| [async-event-queue.md](concepts/async-event-queue.md) | Pattern where events are queued before their consumer is ready, then drained on initialization |
| [context-window-management.md](concepts/context-window-management.md) | Strategy for monitoring and managing the token budget of active conversations |

---

## Syntheses

| Page | Description |
|------|-------------|
| [request-lifecycle.md](syntheses/request-lifecycle.md) | End-to-end flow: from user input through API call, tool execution, and analytics reporting |
