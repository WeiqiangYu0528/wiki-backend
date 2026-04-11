# Analytics Service

## Overview

The Analytics Service provides a zero-dependency public API for emitting telemetry events throughout Claude Code. Its defining characteristic is that it can be called from any module without causing import cycles — events are simply queued if the backend sink is not yet attached. During app startup, `attachAnalyticsSink()` wires up the concrete routing logic (Datadog and first-party logging), and any queued events are drained asynchronously via `queueMicrotask`. The service also manages privacy: it enforces type-level annotations to prevent accidental logging of code, file paths, or PII, and strips PII-tagged fields before routing to general-access backends.

## Key Types / Key Concepts

The public API is intentionally narrow:

```typescript
// Log a synchronous event
function logEvent(
  eventName: string,
  metadata: { [key: string]: boolean | number | undefined }
): void

// Log an asynchronous event (same routing, kept for interface compatibility)
function logEventAsync(
  eventName: string,
  metadata: { [key: string]: boolean | number | undefined }
): Promise<void>

// Attach the concrete sink (idempotent — safe to call multiple times)
function attachAnalyticsSink(newSink: AnalyticsSink): void
```

Privacy enforcement via marker types:
```typescript
// Forces explicit verification that a string value isn't code or a file path
type AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS = never

// Marks a value as PII-tagged (only routed to privileged BigQuery columns)
type AnalyticsMetadata_I_VERIFIED_THIS_IS_PII_TAGGED = never
```

`_PROTO_*`-prefixed metadata keys are PII-tagged. The `stripProtoFields()` utility removes them before Datadog fanout.

## Architecture

The service follows a **producer/sink** split:

**`index.ts` (producer — zero dependencies)**:
Defines the public `logEvent` / `logEventAsync` functions and the in-memory `eventQueue`. Has no imports from other services, making it safe to call anywhere. This is the only file other services should import.

**`sink.ts` (consumer — app startup only)**:
Contains `initializeAnalyticsSink()` and the routing logic. On each event it: (1) checks the sampling config, (2) routes to Datadog if the feature gate is enabled and the sink is not killed, (3) routes to first-party logging. Called from app startup code.

**`datadog.ts`**:
Thin wrapper around the Datadog RUM/metrics SDK. Called from `sink.ts`.

**`firstPartyEventLogger.ts` / `firstPartyEventLoggingExporter.ts`**:
Implements the first-party event logging pipeline (BigQuery-backed). The exporter hoists `_PROTO_*` keys to top-level proto fields and then strips them from `additional_metadata`.

**`growthbook.ts`**:
GrowthBook feature gate and dynamic config client. Exposes `getFeatureValue_CACHED_MAY_BE_STALE()` and `getDynamicConfig_CACHED_MAY_BE_STALE()` — these return cached values immediately without blocking. Used by analytics sampling config, compact service, and session memory gating.

**`sinkKillswitch.ts`**:
Allows disabling individual sinks (e.g., `isSinkKilled('datadog')`) without redeploying.

**`metadata.ts`**:
Utilities for extracting telemetry-safe metadata from tool inputs (file extensions, sanitized tool names, MCP tool details).

**`config.ts`**:
Static analytics configuration (event sampling rates, backend endpoints).

The [Async Event Queue](../concepts/async-event-queue.md) pattern is central to this service's design.

## Source Files

| File | Purpose |
|------|---------|
| `services/analytics/index.ts` | Public API: `logEvent`, `logEventAsync`, `attachAnalyticsSink` |
| `services/analytics/sink.ts` | Routing implementation: Datadog + 1P |
| `services/analytics/datadog.ts` | Datadog SDK integration |
| `services/analytics/firstPartyEventLogger.ts` | First-party event logging |
| `services/analytics/firstPartyEventLoggingExporter.ts` | Proto field hoisting and BigQuery export |
| `services/analytics/growthbook.ts` | Feature gates and dynamic config (GrowthBook) |
| `services/analytics/sinkKillswitch.ts` | Per-sink disable mechanism |
| `services/analytics/metadata.ts` | Telemetry-safe metadata extraction utilities |
| `services/analytics/config.ts` | Static analytics configuration |

## See Also

- [API Service](api-service.md) — logs events for every model call
- [Compact Service](compact-service.md) — logs compaction events; reads feature gates from growthbook.ts
- [OAuth Service](oauth-service.md) — logs OAuth flow completion events
- [Async Event Queue](../concepts/async-event-queue.md) — the core design pattern of this service
- [Request Lifecycle](../syntheses/request-lifecycle.md) — analytics threads through the entire lifecycle
