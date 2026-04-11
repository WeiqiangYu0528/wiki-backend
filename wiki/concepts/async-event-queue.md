# Async Event Queue

## Overview

The Async Event Queue is a design pattern used throughout the Claude Code services to decouple event producers from their consumers when the consumer may not be ready at the time the producer fires. The canonical implementation is in the [Analytics Service](../entities/analytics-service.md): events can be logged from any module at any time during startup, but the actual routing logic (sink) is only attached after initialization is complete. Rather than block startup or drop events, the queue buffers them and drains asynchronously once the consumer is available. A similar race-and-resolve pattern appears in the [OAuth Service](../entities/oauth-service.md) for automatic vs. manual auth code capture.

## Mechanism

### Analytics Queue Pattern

1. **At module load time**: `index.ts` initializes an empty `eventQueue: QueuedEvent[]` and `sink = null`.

2. **During startup, before sink is attached**: Any call to `logEvent(name, metadata)` finds `sink === null` and pushes `{ eventName, metadata, async: false }` to `eventQueue`. The call returns immediately without blocking.

3. **At app initialization**: The startup sequence calls `attachAnalyticsSink(newSink)`. This sets `sink = newSink`. If `eventQueue.length > 0`, it:
   - Snapshots the queue: `const queuedEvents = [...eventQueue]`
   - Clears the queue: `eventQueue.length = 0`
   - Schedules drain via `queueMicrotask(() => { for (const event of queuedEvents) { sink!.logEvent(...) } })`
   - This avoids adding latency to the startup hot path — microtasks run after the current synchronous tick.

4. **After sink is attached**: All subsequent `logEvent` calls route directly to the sink without queuing.

```typescript
// Simplified implementation (services/analytics/index.ts)
let sink: AnalyticsSink | null = null
const eventQueue: QueuedEvent[] = []

export function attachAnalyticsSink(newSink: AnalyticsSink): void {
  if (sink !== null) return  // Idempotent
  sink = newSink
  if (eventQueue.length > 0) {
    const queuedEvents = [...eventQueue]
    eventQueue.length = 0
    queueMicrotask(() => {
      for (const event of queuedEvents) {
        sink!.logEvent(event.eventName, event.metadata)
      }
    })
  }
}

export function logEvent(name: string, metadata: LogEventMetadata): void {
  if (sink === null) {
    eventQueue.push({ eventName: name, metadata, async: false })
    return
  }
  sink.logEvent(name, metadata)
}
```

### OAuth Race Pattern

The [OAuth Service](../entities/oauth-service.md) uses a related pattern: two async paths race to resolve a single promise:

1. The `AuthCodeListener` awaits the browser redirect (automatic flow)
2. `handleManualAuthCodeInput()` resolves the same promise from a terminal paste (manual flow)

The first to arrive wins; the other is silently ignored. This is implemented with a shared `manualAuthCodeResolver` reference that is set to `null` after resolution.

## Involved Entities

- **[Analytics Service](../entities/analytics-service.md)**: Primary implementation of the event queue pattern. The queue is the reason `index.ts` has zero dependencies — it must be importable from anywhere.
- **[OAuth Service](../entities/oauth-service.md)**: Uses a promise-based race variant for automatic vs. manual auth code capture.
- **[MCP Service](../entities/mcp-service.md)**: Connection state transitions (pending → connected → failed) are handled asynchronously, with the React context providing the current state to subscribers.

## Source Evidence

- `services/analytics/index.ts` lines 80–123: Queue initialization, `attachAnalyticsSink`, `logEvent` implementation
- `services/oauth/index.ts` lines 134–167: `waitForAuthorizationCode`, `handleManualAuthCodeInput` race pattern
- `services/oauth/auth-code-listener.ts`: The local HTTP server that resolves the automatic flow promise

## See Also

- [Analytics Service](../entities/analytics-service.md) — canonical queue implementation
- [OAuth Service](../entities/oauth-service.md) — race variant of the pattern
- [Context Window Management](context-window-management.md) — another cross-cutting concern
- [Request Lifecycle](../syntheses/request-lifecycle.md) — analytics queue is active throughout
