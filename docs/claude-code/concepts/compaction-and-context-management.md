# Compaction and Context Management

## Overview

Claude Code operates within a finite context window. As conversations grow, token usage approaches the model's limit, degrading performance and eventually blocking further interaction. The compaction and context management system keeps conversations within budget through a layered set of strategies: microcompaction (selectively clearing old tool results), auto-compaction (summarizing the full conversation via a forked agent), session memory compaction (pruning messages while relying on persisted session memory), and reactive compaction (recovering from API prompt-too-long errors). These layers work together so the user rarely hits a hard wall.

## Mechanism

### Auto-Compaction Triggers

Auto-compaction is governed by a token threshold derived from the model's effective context window minus a buffer (`AUTOCOMPACT_BUFFER_TOKENS = 13,000`). Before each query loop iteration, `shouldAutoCompact()` estimates current token usage and compares it against this threshold. When usage exceeds the threshold and auto-compact is enabled (checked via `isAutoCompactEnabled()`), compaction fires automatically.

Several guards prevent inappropriate compaction:
- **Recursion guards**: Forked agents whose `querySource` is `'session_memory'` or `'compact'` never trigger auto-compaction, avoiding deadlocks.
- **Circuit breaker**: After `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES` (3) consecutive failures, the system stops retrying for the remainder of the session to avoid wasting API calls.
- **Feature interactions**: When Context Collapse or Reactive Compact experiments are active, proactive auto-compaction is suppressed in favor of those systems.

The `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` and `CLAUDE_CODE_AUTO_COMPACT_WINDOW` environment variables allow overriding thresholds for testing.

### The Compact Service

Full compaction (`compactConversation()` in `services/compact/compact.ts`) works by forking a summarizer agent that receives the full conversation history and produces a structured summary. The summary replaces all prior messages with a compact boundary message containing the condensed context. Key behaviors:

- Messages are grouped by API round via `groupMessagesByApiRound()` so the summarizer can reason about complete interaction turns.
- Images and documents are stripped before sending to the summarizer to avoid hitting the compaction call's own token limit.
- A `MAX_OUTPUT_TOKENS_FOR_SUMMARY` (20,000) reserve ensures the summarizer has room to produce its output.
- Post-compact, recently read files (up to 5, within a 50K token budget) are re-injected so the model retains working file context.
- Invoked skill content survives compaction so that `createSkillAttachmentIfNeeded()` can re-include skill text in subsequent compaction attachments.

### Microcompaction

Microcompaction (`microCompact.ts`) is a lighter-weight strategy that runs before every API call. Rather than summarizing the full conversation, it selectively clears the content of old tool results (from tools like Read, Bash, Grep, Glob, Edit, Write, and web tools) to reclaim tokens while preserving the conversation structure.

Two microcompaction paths exist:

1. **Cached microcompaction** (primary path): Uses the cache editing API to remove tool results without invalidating the server-side prompt cache. It tracks registered tool results, applies a count-based trigger/keep threshold from remote config, and queues `cache_edits` blocks for the API layer. Local message content is not mutated.

2. **Time-based microcompaction**: Fires when the gap since the last assistant message exceeds a configurable threshold (default 60 minutes, matching the server cache TTL). Since the cache is guaranteed cold, it content-clears old tool results directly in the message array, keeping only the most recent N results (`keepRecent`, default 5).

### Reactive Compaction

When the API returns a `prompt_too_long` error, reactive compaction kicks in as a fallback. It consults `isAutoCompactEnabled()` directly (bypassing the proactive suppression gates) and attempts compaction on the spot. This ensures that even when proactive compaction is disabled or suppressed by feature experiments, conversations can recover from hard limit errors.

### Post-Compact Cleanup

After any compaction (auto or manual), `runPostCompactCleanup()` resets accumulated caches and tracking state that are invalidated by the message replacement:

- Microcompact state is reset (registered tool IDs are stale after compaction).
- Context Collapse state is reset (for main-thread compacts only).
- The `getUserContext` memoization cache and `getMemoryFiles` cache are cleared so CLAUDE.md re-evaluation fires on the next turn.
- System prompt sections, classifier approvals, speculative checks, beta tracing state, and session messages cache are all cleared.
- Subagent compacts (identified by `querySource` starting with `'agent:'`) skip main-thread resets to avoid corrupting shared module-level state.

### Session Memory Compaction

`trySessionMemoryCompaction()` is attempted before full compaction. If session memory content exists and is non-empty, it prunes older messages while relying on the persisted session memory to preserve context. Configuration is controlled by `SessionMemoryCompactConfig` with defaults of `minTokens: 10,000`, `minTextBlockMessages: 5`, and `maxTokens: 40,000`.

### Time-Based Configuration

Time-based microcompact configuration (`TimeBasedMCConfig`) is fetched from GrowthBook remote config with defaults:
- `enabled: false` (master switch)
- `gapThresholdMinutes: 60` (matching server cache TTL)
- `keepRecent: 5` (number of recent tool results to preserve)

### Warning State

The `compactWarningStore` tracks whether the "context left until autocompact" warning should be suppressed. It is set after successful compaction and cleared at the start of each new microcompact attempt. The React hook `useCompactWarningSuppression()` subscribes to this store for UI display.

## Involved Entities

- [Auto-Compact Service](../claude_code/src/services/compact/autoCompact.ts) -- threshold calculation, trigger logic, circuit breaker
- [Compact Service](../claude_code/src/services/compact/compact.ts) -- full conversation summarization via forked agent
- [Microcompact Service](../claude_code/src/services/compact/microCompact.ts) -- lightweight tool result clearing (cached and time-based paths)
- [Post-Compact Cleanup](../claude_code/src/services/compact/postCompactCleanup.ts) -- cache/state reset after compaction
- [Session Memory Compaction](../claude_code/src/services/compact/sessionMemoryCompact.ts) -- message pruning with session memory fallback
- [Compact Prompt](../claude_code/src/services/compact/prompt.ts) -- summarizer system prompt construction
- [Time-Based MC Config](../claude_code/src/services/compact/timeBasedMCConfig.ts) -- remote config for time-based microcompact
- [Compact Warning State](../claude_code/src/services/compact/compactWarningState.ts) -- UI suppression tracking
- [Message Grouping](../claude_code/src/services/compact/grouping.ts) -- API-round boundary grouping for summarization
- [Compact Command](../claude_code/src/commands/compact/compact.ts) -- manual `/compact` slash command

## Source Evidence

- `autoCompact.ts:62-65` defines buffer constants: `AUTOCOMPACT_BUFFER_TOKENS = 13_000`, `WARNING_THRESHOLD_BUFFER_TOKENS = 20_000`.
- `autoCompact.ts:70` sets `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3` for the circuit breaker.
- `autoCompact.ts:170-173` recursion guard: `if (querySource === 'session_memory' || querySource === 'compact') return false`.
- `microCompact.ts:41-50` defines `COMPACTABLE_TOOLS` set governing which tool results can be cleared.
- `microCompact.ts:267-268` shows time-based microcompact running first and short-circuiting cached MC.
- `postCompactCleanup.ts:31-77` resets microcompact state, context collapse, user context cache, system prompt sections, classifier approvals, and more.
- `timeBasedMCConfig.ts:30-34` defaults: `enabled: false, gapThresholdMinutes: 60, keepRecent: 5`.
- `sessionMemoryCompact.ts:57-61` default config: `minTokens: 10_000, minTextBlockMessages: 5, maxTokens: 40_000`.
- `compact.ts:122-131` post-compact file restoration constants: `POST_COMPACT_MAX_FILES_TO_RESTORE = 5`, `POST_COMPACT_TOKEN_BUDGET = 50_000`.

## See Also

- [Session Lifecycle](./session-lifecycle.md) -- compaction is a key event in the session lifecycle
- [Agent Isolation](./agent-isolation.md) -- subagent compaction respects isolation boundaries
