# Error Handling Patterns

## Overview

Claude Code employs a structured set of error handling patterns across the system to maintain resilience in the face of API failures, user interruptions, resource limits, and filesystem issues. The patterns range from simple typed error classes to sophisticated retry-with-fallback strategies, all designed to surface actionable information to users while keeping the session alive when possible.

## Mechanism

### Error Class Hierarchy

The codebase defines several purpose-built error classes in `utils/errors.ts` and across service modules:

| Error Class | Module | Purpose |
|-------------|--------|---------|
| `AbortError` | `utils/errors.ts` | User cancellation or programmatic abort. Sets `name = 'AbortError'` for compatibility with DOM `AbortController`. |
| `ShellError` | `utils/errors.ts` | Shell command failure with exit code, stdout, stderr, and interrupted flag. |
| `ClaudeError` | `utils/errors.ts` | Base error with optional `exitCode` for CLI process exit. |
| `ConfigParseError` | `utils/errors.ts` | Settings file parse failure with file path context. |
| `FallbackTriggeredError` | `services/api/withRetry.ts` | Signals that the retry loop exhausted 529 retries and should switch to a fallback model. Not a true error -- it is a control-flow mechanism. |
| `CannotRetryError` | `services/api/withRetry.ts` | Wraps the original error when retries are exhausted or the error is non-retryable. Preserves original stack trace. |
| `ImageSizeError` | `utils/imageValidation.ts` | Image exceeds API size limits before the request is made. |
| `ImageResizeError` | `utils/imageResizer.ts` | Image resize operation failed during pre-processing. |
| `TeleportOperationError` | `utils/errors.ts` | Teleport (session transfer) operation failure. |

### Abort Detection

The `isAbortError()` utility recognizes three forms of abort:

1. The custom `AbortError` class.
2. The SDK's `APIUserAbortError` (thrown when a streaming request is cancelled).
3. Any `Error` with `name === 'AbortError'` (DOM `AbortController.abort()` convention).

This unified check is used throughout the tool execution pipeline and the permission system to short-circuit cleanly when the user cancels.

### API Retry with Exponential Backoff

The `withRetry` generator in `services/api/withRetry.ts` implements the core API retry loop:

**Configuration:**
- `DEFAULT_MAX_RETRIES = 10`
- `BASE_DELAY_MS = 500`
- `MAX_529_RETRIES = 3` (before fallback)
- Persistent mode (unattended sessions): up to 6 hours of retries with 5-minute max backoff and 30-second heartbeat yields

**Retry logic per attempt:**
1. Check abort signal; throw `APIUserAbortError` if aborted.
2. Refresh the API client if the previous error was a 401, 403 (token revoked), Bedrock/Vertex auth error, or stale connection (ECONNRESET/EPIPE).
3. Execute the operation.
4. On failure, classify the error:
   - **Fast mode 429/529**: check `retry-after` header. Short delays (<threshold) retry with fast mode active. Long delays trigger cooldown and switch to standard speed.
   - **529 overloaded (non-foreground)**: bail immediately -- no retry amplification for background queries (summaries, classifiers, suggestions).
   - **529 overloaded (foreground)**: count consecutive errors. After `MAX_529_RETRIES`, throw `FallbackTriggeredError` if a fallback model is configured.
   - **Persistent mode (429/529)**: retry indefinitely with capped backoff, yielding heartbeat `SystemAPIErrorMessage`s to keep the session alive.
   - **401/403 auth errors**: refresh credentials and retry.
   - **Connection errors**: retry with fresh client.
   - **Non-retryable errors**: throw `CannotRetryError`.

**Backoff calculation:**
- Standard: `BASE_DELAY_MS * 2^(attempt-1)` plus jitter, capped at the retry-after header value when present.
- Persistent: quadratic or exponential with `PERSISTENT_MAX_BACKOFF_MS` (5 min) cap.
- Analytics first-party exporter: quadratic backoff (`base * attempts^2`).

### Prompt-Too-Long Handling

When the API returns a "prompt is too long" error:

1. `isPromptTooLongMessage()` detects it from the assistant message content.
2. `parsePromptTooLongTokenCounts()` extracts actual vs. limit token counts from the raw error string (e.g., "137500 tokens > 135000 maximum").
3. `getPromptTooLongTokenGap()` computes the overage so reactive compact can skip multiple conversation groups at once instead of peeling one at a time.
4. The system triggers automatic compaction to reduce the conversation size and retries.

### FallbackTriggeredError Flow

This error is a control-flow signal, not a failure:

1. `withRetry` throws `FallbackTriggeredError` after `MAX_529_RETRIES` consecutive 529s when a `fallbackModel` is configured.
2. The error propagates up to `query.ts`, which catches it and re-runs the query with the fallback model.
3. `services/api/claude.ts` explicitly re-throws `FallbackTriggeredError` to prevent the general error handler from swallowing it.

### Image Size and Resize Errors

Image errors are caught early, before the API request:

1. `ImageSizeError` is thrown during validation if dimensions or file size exceed API limits.
2. `ImageResizeError` is thrown if the resize operation itself fails (e.g., corrupt image, unsupported format).
3. Both are caught in `query.ts` at the top level and produce user-friendly messages via `getImageTooLargeErrorMessage()`, which varies for interactive vs. non-interactive sessions.
4. `isMediaSizeError()` in `services/api/errors.ts` detects API-side media rejections (image exceeds maximum, too many images, PDF too large) from the raw error text, enabling reactive compact to strip images and retry.

### Tool Error Formatting

`utils/toolErrors.ts` provides structured error formatting:

- `formatError()`: handles `AbortError` (returns interrupt message), `ShellError` (exit code + stdout/stderr), and generic errors. Truncates output to 10,000 characters with a middle-ellipsis to stay within context limits.
- `formatZodValidationError()`: converts Zod validation failures into LLM-friendly messages distinguishing missing parameters, unexpected parameters, and type mismatches.

### Filesystem Inaccessibility

Settings and configuration file reads handle filesystem errors gracefully:

- `ENOENT` (file not found): logged at debug level, treated as empty/absent settings. Expected for optional settings files.
- `ENOTDIR`: silently ignored when scanning drop-in directories.
- Broken symlinks: detected and logged as debug messages.
- JSON syntax errors in settings files: `updateSettingsForSource` returns an `Error` rather than overwriting the corrupt file, preserving the user's content.
- All settings cache reads return deep clones to prevent mutation of cached state.

### In-Memory Error Tracking

Several subsystems maintain in-memory error state:

- **Validation errors**: `getSettingsWithErrors()` accumulates `ValidationError[]` across all settings sources, deduplicating by file+path+message. Surfaced via `/status`.
- **Permission decision logging**: every tool use decision (accept/reject, source, timing) is logged via `logPermissionDecision` for analytics and debugging.
- **Hook outcomes**: each hook execution produces a `HookResult` with an `outcome` field (`success`, `blocking`, `non_blocking_error`, `cancelled`). Blocking errors from hooks halt the pipeline.
- **Auto-mode denials**: `recordAutoModeDenial` tracks classifier-based permission denials in memory for the `/permissions` UI.

### Transport-Level Retry

Network transports each implement their own retry strategies:

- **SSE transport**: automatic reconnection with exponential backoff and `Last-Event-ID` for resumption.
- **WebSocket transport**: reconnection with exponential backoff and time budget.
- **Hybrid transport**: exponential backoff with jitter; drops oldest events if queue exceeds `maxQueueSize`.
- **Serial batch uploader**: exponential backoff (clamped) with jitter, retries indefinitely. Server-provided `retryAfterMs` overrides backoff when present.
- **First-party analytics exporter**: quadratic backoff (`base * attempts^2`), dropped after max attempts. Spills to disk on persistent failure.

## Involved Entities

- [Query Engine](../entities/query-engine.md) -- orchestrates API calls and catches top-level errors
- [Tool System](../entities/tool-system.md) -- tool execution produces `ShellError`, `AbortError`, and validation errors
- [Configuration System](../entities/configuration-system.md) -- settings parse errors and validation tracking
- [Permission System](../entities/permission-system.md) -- permission decision logging and auto-mode denial tracking
- [Bridge System](../entities/bridge-system.md) -- transport-level retry and reconnection

## Source Evidence

| File | Role |
|------|------|
| `utils/errors.ts` | `AbortError`, `ShellError`, `ClaudeError`, `ConfigParseError`, `isAbortError()` |
| `services/api/withRetry.ts` | `withRetry` generator, `FallbackTriggeredError`, `CannotRetryError`, retry classification, backoff calculation |
| `services/api/errors.ts` | `isPromptTooLongMessage`, `parsePromptTooLongTokenCounts`, `getPromptTooLongTokenGap`, `isMediaSizeError`, user-facing error messages |
| `utils/toolErrors.ts` | `formatError()`, `formatZodValidationError()` |
| `query.ts` | Top-level error handling: `FallbackTriggeredError` catch, `ImageSizeError`/`ImageResizeError` catch |
| `services/api/claude.ts` | API call orchestration, `FallbackTriggeredError` re-throw |
| `utils/settings/settings.ts` | Filesystem error handling, JSON syntax error protection, validation error dedup |
| `cli/transports/SSETransport.ts` | SSE reconnection with exponential backoff |
| `cli/transports/SerialBatchEventUploader.ts` | Batch upload retry with server-hint backoff |
| `services/analytics/firstPartyEventLoggingExporter.ts` | Quadratic backoff, disk spill on failure |

## See Also

- [Hook System](./hook-system.md) -- hooks produce blocking errors and cancellation signals
- [Settings Hierarchy](./settings-hierarchy.md) -- settings validation errors flow through the hierarchy
- [Query Engine](../entities/query-engine.md) -- primary consumer of retry and prompt-too-long handling
- [Tool System](../entities/tool-system.md) -- tools produce the errors that these patterns handle
