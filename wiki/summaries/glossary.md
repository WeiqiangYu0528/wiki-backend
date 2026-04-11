# Glossary

Domain-specific terms used in the Claude Code services codebase, alphabetically ordered.

---

**Analytics Sink**
The concrete implementation that routes analytics events to external backends (Datadog, first-party logging). Attached during app startup via `attachAnalyticsSink()`. See [Analytics Service](../entities/analytics-service.md).

**Auto-Compact**
The automated process of summarizing a conversation when it approaches the model's context window limit. Triggered by `autoCompactIfNeeded()` in the query loop. See [Compact Service](../entities/compact-service.md).

**Betas**
Anthropic API feature flags (e.g., `interleaved-thinking-2025-05-14`) passed in request headers to enable preview model capabilities. Assembled by `getMergedBetas()` in the API service.

**CAPPED_DEFAULT_MAX_TOKENS**
A constant capping the maximum tokens requested per API call, preventing runaway usage. Defined in `utils/context.ts`, enforced in [API Service](../entities/api-service.md).

**Circuit Breaker**
A safety pattern in [Compact Service](../entities/compact-service.md) that stops retrying auto-compaction after `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES` (3) consecutive failures, preventing runaway API calls when context is irrecoverably oversized.

**Claude.ai OAuth**
Authentication via the Anthropic Claude.ai web service using OAuth 2.0 + PKCE. Managed by [OAuth Service](../entities/oauth-service.md).

**CompactConversation**
The core function in [Compact Service](../entities/compact-service.md) that summarizes the conversation via a forked sub-agent, replaces message history with the summary, and returns a `CompactionResult`.

**ConfigScope**
An enum (`local | user | project | dynamic | enterprise | claudeai | managed`) indicating the origin of an MCP server configuration. Defined in [MCP Service](../entities/mcp-service.md) `types.ts`.

**ConnectedMCPServer**
An MCP server that has successfully established a connection. One of five states in the `MCPServerConnection` union type. See [MCP Service](../entities/mcp-service.md).

**Context Window**
The maximum number of tokens a model can process in one API call. Managed and monitored by [Compact Service](../entities/compact-service.md) and [Context Window Management](../concepts/context-window-management.md).

**Event Queue**
An in-memory buffer in [Analytics Service](../entities/analytics-service.md) that holds events logged before the sink is attached. Drained via `queueMicrotask` after sink attachment. See [Async Event Queue](../concepts/async-event-queue.md).

**Feature Gate**
A GrowthBook-backed feature flag checked via `checkStatsigFeatureGate_CACHED_MAY_BE_STALE()` or `getFeatureValue_CACHED_MAY_BE_STALE()`. Used by analytics, compact, and other services.

**Forked Agent**
A sub-agent spawned by `runForkedAgent()` to perform a task (e.g., compaction, session memory extraction) without interrupting the main conversation loop.

**GrowthBook**
The feature flag and A/B testing service used for dynamic configuration. Accessed via `services/analytics/growthbook.ts`.

**LSPServerManager**
A manager returned by `createLSPServerManager()` that routes language server requests to the appropriate server instance based on file extension. See `services/lsp/LSPServerManager.ts`.

**MCPConnectionManager**
A React context provider (`MCPConnectionManager`) that exposes `reconnectMcpServer` and `toggleMcpServer` to child components. See [MCP Service](../entities/mcp-service.md).

**MCPServerConnection**
A discriminated union type representing one of five server states: `connected | failed | needs-auth | pending | disabled`. See [MCP Service](../entities/mcp-service.md).

**OAuth PKCE**
Proof Key for Code Exchange — an OAuth extension that prevents auth code interception. Used by [OAuth Service](../entities/oauth-service.md) via `crypto.generateCodeVerifier()` and `generateCodeChallenge()`.

**OAuthService**
The class in `services/oauth/index.ts` that orchestrates the full OAuth 2.0 + PKCE authorization code flow. See [OAuth Service](../entities/oauth-service.md).

**PartitionToolCalls**
A function in [tools/toolOrchestration.ts](../entities/api-service.md) that separates tool calls into concurrency-safe batches (run in parallel) and non-concurrency-safe batches (run serially).

**PKCE**
See OAuth PKCE.

**PolicyLimits**
Rate-limit policies enforced on Claude.ai subscription tiers. Stored in `services/policyLimits/` and consumed by the API service.

**PostSamplingHook**
A hook registered via `registerPostSamplingHook()` that runs after each model sampling turn. Session Memory uses this to schedule background memory extraction.

**ProtoField**
A `_PROTO_*`-prefixed analytics metadata key that carries PII-tagged data to privileged BigQuery columns. Stripped before Datadog fanout; only the first-party exporter sees them.

**QuerySource**
A string enum identifying the origin of a model query (`session_memory | compact | marble_origami | ...`). Used to guard against recursive compaction.

**Rate Limit Tier**
A subscription-based API rate limit level (e.g., free, pro) fetched from the Anthropic profile endpoint after OAuth authentication.

**ScopedMcpServerConfig**
An MCP server configuration augmented with a `scope` field indicating its origin (local, user, project, etc.). See [MCP Service](../entities/mcp-service.md).

**Session Memory**
A background service (`services/SessionMemory/`) that maintains a running markdown file summarizing the current conversation for use in future prompts.

**Settings Sync**
A service (`services/settingsSync/`) that uploads local user settings to remote storage (for interactive CLI) or downloads them (for remote Claude Code Runner environments).

**Sink Killswitch**
A mechanism in `services/analytics/sinkKillswitch.ts` that can disable individual analytics backends (e.g., Datadog) without redeploying.

**StdioTransport**
An MCP transport type where the server process is launched as a child process and communicates via stdin/stdout. One of several transport types (`stdio | sse | http | ws | sdk`).

**ToolUseContext**
The context object threaded through the entire tool execution pipeline, containing references to tools, options, app state, and permission context.
