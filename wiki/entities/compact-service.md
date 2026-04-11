# Compact Service

## Overview

The Compact Service manages context window compaction — the process of summarizing an ongoing conversation to prevent it from exceeding the model's token limit. When a conversation grows too large, the service spawns a forked sub-agent that generates a structured summary of the session, then replaces the full message history with that summary plus a compact boundary marker. The service has two compaction paths: a "full" compaction (rewrites the entire history via `compactConversation`) and a lighter "session memory" compaction (uses the pre-built session memory markdown file as the summary). Both paths are triggered automatically by `autoCompactIfNeeded()` on each query loop turn.

## Key Types / Key Concepts

```typescript
// Returned by both compaction paths
type CompactionResult = {
  summary: string
  newMessages: Message[]
}

// Threading through re-compaction chains
type RecompactionInfo = {
  isRecompactionInChain: boolean
  turnsSincePreviousCompact: number
  previousCompactTurnId: string | undefined
  autoCompactThreshold: number
  querySource: QuerySource | undefined
}

// Tracking state passed turn-to-turn in the query loop
type AutoCompactTrackingState = {
  compacted: boolean
  turnCounter: number
  turnId: string
  consecutiveFailures?: number   // Circuit breaker counter
}
```

Key threshold constants:

```typescript
const AUTOCOMPACT_BUFFER_TOKENS = 13_000      // Headroom before threshold triggers
const MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3 // Circuit breaker limit
const MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000  // Reserved for compaction output
```

The effective context window is: `getContextWindowForModel(model) - MAX_OUTPUT_TOKENS_FOR_SUMMARY`.

The auto-compact threshold is: `effectiveContextWindow - AUTOCOMPACT_BUFFER_TOKENS`.

## Architecture

The compact service is organized into several focused modules:

**`autoCompact.ts`** — The public entry point for the query loop. Contains:
- `isAutoCompactEnabled()`: checks env vars and user config
- `shouldAutoCompact()`: checks token count against threshold, guards against recursive compaction (from `session_memory` or `compact` query sources), and respects feature gates (reactive compact, context collapse)
- `autoCompactIfNeeded()`: orchestrates the flow — tries session memory compaction first, falls back to full compaction, implements the circuit breaker
- `calculateTokenWarningState()`: computes warning/error/blocking levels for UI display

**`compact.ts`** — The core compaction engine:
- `compactConversation()`: Runs the forked sub-agent to produce a summary, replaces messages with `SystemCompactBoundaryMessage` + summary, handles pre/post compact hooks
- Supports both automatic (suppress user questions) and manual (`/compact` command) invocations

**`sessionMemoryCompact.ts`** — The lighter compaction path:
- `trySessionMemoryCompaction()`: If a session memory file exists and is recent enough, uses it as the compaction summary instead of running a full sub-agent call

**`autoCompact.ts` → `postCompactCleanup.ts`** — Post-compaction cleanup:
- `runPostCompactCleanup()`: Resets analytics state, clears file caches, notifies prompt cache break detection

**`microCompact.ts` / `apiMicrocompact.ts`** — Micro-compaction:
- A lighter alternative that summarizes just recent messages without rewriting the full history

**`grouping.ts`** — Groups messages into logical conversation segments for more coherent summaries.

**`compactWarningHook.ts` / `compactWarningState.ts`** — UI warning system:
- Hooks that update app state with warning/error/blocking levels for the token meter in the UI

**`timeBasedMCConfig.ts`** — Time-based configuration:
- Adjusts compaction behavior based on session duration

The [Context Window Management](../concepts/context-window-management.md) concept describes the broader threshold and warning system.

## Source Files

| File | Purpose |
|------|---------|
| `services/compact/autoCompact.ts` | Query-loop entry point, threshold logic, circuit breaker |
| `services/compact/compact.ts` | Core compaction engine with forked sub-agent |
| `services/compact/sessionMemoryCompact.ts` | Session-memory-backed lightweight compaction |
| `services/compact/postCompactCleanup.ts` | Post-compaction state cleanup |
| `services/compact/microCompact.ts` | Micro-compaction for recent messages only |
| `services/compact/apiMicrocompact.ts` | API-based micro-compaction variant |
| `services/compact/grouping.ts` | Message grouping for coherent summarization |
| `services/compact/compactWarningHook.ts` | UI warning hook |
| `services/compact/compactWarningState.ts` | Warning threshold state |
| `services/compact/prompt.ts` | Compaction system prompt templates |
| `services/compact/timeBasedMCConfig.ts` | Time-based configuration adjustments |

## See Also

- [API Service](api-service.md) — compaction calls the API service via a forked agent
- [Analytics Service](analytics-service.md) — compaction events are logged; feature gates via growthbook
- [Context Window Management](../concepts/context-window-management.md) — the broader threshold and warning pattern
- [Request Lifecycle](../syntheses/request-lifecycle.md) — compaction may occur before each query turn
