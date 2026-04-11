# API Service

## Overview

The API Service is the primary gateway between Claude Code and Anthropic's language model backend. It handles every model call: assembles request parameters (messages, tools, betas, system prompt), submits them to the Anthropic SDK, streams the response back, and tracks token usage and rate limits. It also implements retry logic, prompt cache management, and request logging. All other services that need model output — including [Compact Service](compact-service.md), Session Memory, and Agent Summary — ultimately call through this service.

## Key Types / Key Concepts

The central function is `query()` (in `services/api/claude.ts`), which accepts a fully-assembled message array, tool list, and options, then returns an async generator of `StreamEvent` objects. Callers consume this stream to process assistant text, tool calls, and stop reasons.

Key types:

```typescript
// Message types threaded through the request
type AssistantMessage = { ... }
type UserMessage = { ... }
type Message = AssistantMessage | UserMessage | SystemMessage | ...

// Usage tracking
type BetaUsage = {
  input_tokens: number
  output_tokens: number
  cache_read_input_tokens?: number
  cache_creation_input_tokens?: number
}

// Stream events emitted by query()
type StreamEvent = BetaRawMessageStreamEvent | ...
```

Tool serialization converts internal `Tool` objects into the `BetaToolUnion` format the API expects via `toolToAPISchema()`.

## Architecture

The API service is organized into specialized modules:

- **`claude.ts`**: Core `query()` function and model-selection helpers (`getDefaultSonnetModel`, `getMaxOutputTokensForModel`). This is the main entry point. It assembles beta flags, system prompt prefixes, cache scope, and tool schemas before making the call.
- **`client.ts`**: Creates the Anthropic SDK `Anthropic` client instance, wires in the upstream proxy (if configured), and sets authentication headers.
- **`withRetry.ts`**: Exponential back-off retry wrapper with configurable `getRetryDelay`. Handles overload errors and transient failures.
- **`usage.ts`**: Accumulates token counts across streamed chunks and exposes `currentLimits()`.
- **`errors.ts` / `errorUtils.ts`**: Typed error classes for quota exhaustion, network errors, and policy violations.
- **`grove.ts`**: Grove (content storage) integration for large message bodies.
- **`logging.ts`**: Structured request/response logging via `captureAPIRequest`.
- **`promptCacheBreakDetection.ts`**: Detects unexpected drops in cache read tokens that indicate a cache invalidation.
- **`sessionIngress.ts`**: Records session start events for analytics and rate limit tracking.
- **`adminRequests.ts`**: Internal admin-only API calls.
- **`bootstrap.ts`**: Bootstraps API credentials during startup.

Betas are assembled by merging three sources — model-specific defaults, user-configured betas, and Bedrock-specific params — via `getMergedBetas()` in `utils/betas.ts`.

## Source Files

| File | Purpose |
|------|---------|
| `services/api/claude.ts` | Core model query function, model selection, beta assembly |
| `services/api/client.ts` | Anthropic SDK client initialization and proxy support |
| `services/api/withRetry.ts` | Exponential back-off retry wrapper |
| `services/api/usage.ts` | Token usage accumulation and rate limit state |
| `services/api/errors.ts` | Typed API error classes |
| `services/api/errorUtils.ts` | Error parsing utilities |
| `services/api/logging.ts` | Request/response structured logging |
| `services/api/promptCacheBreakDetection.ts` | Detects cache invalidation events |
| `services/api/sessionIngress.ts` | Session start recording |
| `services/api/grove.ts` | Large-content storage integration |

## See Also

- [MCP Service](mcp-service.md) — tool schemas from MCP servers flow into API requests
- [Analytics Service](analytics-service.md) — all API calls emit analytics events
- [Compact Service](compact-service.md) — uses API service to summarize conversations
- [Context Window Management](../concepts/context-window-management.md) — token limits enforced at API layer
- [Request Lifecycle](../syntheses/request-lifecycle.md) — API service is the central node
