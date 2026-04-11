# Context Window Management

## Overview

Context Window Management is the cross-cutting strategy Claude Code uses to keep active conversations within the token budget of the underlying language model. Because model context windows are finite (typically 200K tokens for Claude 3.x), long conversations or tool-heavy sessions can exhaust the budget. The system addresses this at three levels: proactive monitoring (warning thresholds), automatic compaction (summarization), and blocking (preventing new queries when the budget is fully consumed). The [Compact Service](../entities/compact-service.md) owns the compaction logic, while the [API Service](../entities/api-service.md) enforces the hard limits and provides token counts.

## Mechanism

### Token Counting

Token usage is tracked from the Anthropic API response (`BetaUsage`). The field `tokenCountFromLastAPIResponse()` (in `utils/tokens.ts`) returns the total input tokens from the most recent response. `tokenCountWithEstimation()` estimates the total token count of a message array without making an API call, using a fast heuristic for intermediate turns.

### Threshold Levels

The `calculateTokenWarningState()` function (in `services/compact/autoCompact.ts`) computes five boolean flags:

```typescript
function calculateTokenWarningState(tokenUsage: number, model: string): {
  percentLeft: number
  isAboveWarningThreshold: boolean    // UI: yellow warning
  isAboveErrorThreshold: boolean      // UI: red warning
  isAboveAutoCompactThreshold: boolean // Triggers auto-compact
  isAtBlockingLimit: boolean           // Blocks new queries
}
```

The thresholds cascade from a shared `effectiveContextWindow`:

```
effectiveContextWindow = getContextWindowForModel(model) - MAX_OUTPUT_TOKENS_FOR_SUMMARY (20K)
autoCompactThreshold   = effectiveContextWindow - AUTOCOMPACT_BUFFER_TOKENS (13K)
warningThreshold       = autoCompactThreshold - WARNING_THRESHOLD_BUFFER_TOKENS (20K)
errorThreshold         = autoCompactThreshold - ERROR_THRESHOLD_BUFFER_TOKENS (20K)
blockingLimit          = effectiveContextWindow - MANUAL_COMPACT_BUFFER_TOKENS (3K)
```

The `MAX_OUTPUT_TOKENS_FOR_SUMMARY` reservation ensures there is always headroom for the compaction summary itself.

### Auto-Compact Flow

On every query loop turn, `autoCompactIfNeeded()` is called with the current message array and model:

1. Check `isAutoCompactEnabled()` (env vars + user config)
2. Check `shouldAutoCompact()` — guards against recursive calls (session_memory, compact query sources), checks the circuit breaker (stops after 3 consecutive failures), and reads the feature gate
3. If needed: try `trySessionMemoryCompaction()` first (lighter path using pre-built summary)
4. If session memory compaction not available: run `compactConversation()` via a forked sub-agent
5. After compaction: call `runPostCompactCleanup()` to reset state

### UI Warning Display

The `compactWarningHook.ts` module registers a post-sampling hook that updates app state with the current warning level after each model turn. The UI renders a token meter based on `isAboveWarningThreshold` and `isAboveErrorThreshold`.

### Circuit Breaker

If compaction fails (e.g., the context is already larger than the model can process), the `consecutiveFailures` counter in `AutoCompactTrackingState` increments. After `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES` (3) failures, the circuit breaker trips and auto-compact is skipped for the rest of the session, preventing runaway API calls.

### Feature Gate Interaction

Both the compact service and session memory service read feature gates from `analytics/growthbook.ts` (e.g., `tengu_cobalt_raccoon` for reactive-only compact mode, `CONTEXT_COLLAPSE` for the context collapse experiment). These gates can alter which compaction path is used or suppress auto-compact entirely.

## Involved Entities

- **[Compact Service](../entities/compact-service.md)**: Owns all compaction paths — full compaction, session memory compaction, micro-compaction, and the circuit breaker
- **[API Service](../entities/api-service.md)**: Provides `getMaxOutputTokensForModel()` and `getContextWindowForModel()` used to compute thresholds; enforces hard limits at the API boundary
- **[Analytics Service](../entities/analytics-service.md)**: Feature gates (GrowthBook) influence compaction behavior; compaction events are logged

## Source Evidence

- `services/compact/autoCompact.ts`: `calculateTokenWarningState()`, `isAutoCompactEnabled()`, `shouldAutoCompact()`, `autoCompactIfNeeded()`, threshold constants
- `services/compact/compact.ts`: `compactConversation()`, `RecompactionInfo`, hooks integration
- `services/compact/sessionMemoryCompact.ts`: Lightweight compaction path
- `services/api/claude.ts`: `getMaxOutputTokensForModel()`, `CAPPED_DEFAULT_MAX_TOKENS`
- `utils/context.ts`: `getContextWindowForModel()`, `COMPACT_MAX_OUTPUT_TOKENS`
- `utils/tokens.ts`: `tokenCountWithEstimation()`, `tokenCountFromLastAPIResponse()`

## See Also

- [Compact Service](../entities/compact-service.md) — implements the compaction engine
- [API Service](../entities/api-service.md) — provides context window sizes and token counts
- [Analytics Service](../entities/analytics-service.md) — feature gates and event logging
- [Async Event Queue](async-event-queue.md) — another cross-cutting pattern
- [Request Lifecycle](../syntheses/request-lifecycle.md) — context management is checked every turn
