# Isolated Agent Automation

## Overview

OpenClaw's automation system treats scheduled and background work as full agent turns rather than shell scripts or webhook callbacks. A cron job is not a bash one-liner fired by `crond`; it is a complete isolated agent execution that gets its own namespaced session, runs through the same agent runtime that handles interactive turns, delivers output through the same outbound channel pipeline, and has its session reaped by a dedicated cleanup process when finished. This means cron jobs participate in the same permission, model selection, skill injection, and delivery infrastructure as interactive conversations.

The isolation guarantee is structural: cron session keys use the format `agent:<agentId>:cron:<jobId>:run:<runId>`, which routes transcript storage, permission checks, and session lifecycle events to a dedicated namespace, preventing cross-contamination with interactive sessions even when the same agent handles both.

## Mechanism

### CronService

`CronService` in `src/cron/service.ts` is the public API for the cron subsystem. It wraps `createCronServiceState(deps)` and delegates all operations to `src/cron/service/ops.ts`:

```ts
class CronService {
  start(): Promise<void>
  stop(): void
  add(input: CronJobCreate): Promise<CronJob>
  update(id: string, patch: CronJobPatch): Promise<CronJob>
  remove(id: string): Promise<void>
  run(id: string, mode?: "due" | "force"): Promise<void>
  enqueueRun(id: string, mode?: "due" | "force"): Promise<void>
  wake(opts: { mode: "now" | "next-heartbeat"; text: string }): void
}
```

`"due"` mode runs a job only if its schedule has fired. `"force"` runs unconditionally — used for manual testing.

### Schedule Evaluation

`src/cron/schedule.ts` uses the `croner` library:

```ts
const cron = new Cron(expr, { timezone, catch: false });
```

An LRU cache of `CRON_EVAL_CACHE_MAX = 512` entries stores parsed `Cron` objects to avoid repeated expression compilation. `resolveCronTimezone()` defaults to the local timezone from `Intl.DateTimeFormat().resolvedOptions().timeZone`.

In addition to standard cron expressions, `parseAbsoluteTimeMs()` handles ISO 8601 absolute timestamps — useful for one-shot future jobs.

### Isolated Agent Execution

When a job fires, `runCronIsolatedAgentTurn()` in `src/cron/isolated-agent/run.ts` executes a complete agent turn:

1. Constructs the cron session key: `agent:<agentId>:cron:<jobId>:run:<runId>`.
2. Resolves agent config via `resolveSessionAgentIds()`.
3. Loads skills and tools for the agent.
4. Runs the agent turn with the job's prompt as input.
5. Delivers output via `resolveCronDeliveryPlan()` + `deliverOutboundPayloads()`.

The `RunCronAgentTurnResult` indicates success, failure, or partial completion.

### Delivery

`src/cron/delivery.ts` handles outbound delivery for cron runs:
- `resolveCronDeliveryPlan()` — determines where to send output (which channel, which peer).
- `resolveFailureDestination()` — determines where to send failure notifications.
- `sendFailureNotificationAnnounce()` — delivers failure messages within `FAILURE_NOTIFICATION_TIMEOUT_MS = 30,000ms`.

The delivery plan consults the cron job's `channel`, `to`, `accountId`, and `sessionKey` fields. If the job has no explicit destination, output goes to the job's configured channel account.

### Session Reaper

`src/cron/session-reaper.ts` runs after a cron turn completes. It removes the ephemeral cron session from the gateway's session registry, preventing unbounded session accumulation from recurring jobs.

### Heartbeat Integration

`heartbeat-policy.ts` controls whether a cron job's heartbeat can wake a sleeping gateway. The `wake()` method on `CronService` dispatches a wake signal with `"now"` or `"next-heartbeat"` mode, unblocking the gateway's next scheduled wakeup.

## Operational Implications

- Each job run has its own transcript. Successive runs of the same job produce separate transcripts identifiable by `runId` in the session key.
- Failures trigger delivery to a `failure` destination that can differ from the success destination — allowing separate alert channels for errors.
- The `"force"` run mode bypasses schedule checks, which is useful for testing and administrative intervention.
- Because cron runs are full agent turns, they can use all skills, tools, and model features available to the agent — there is no reduced capability mode for scheduled tasks.

## Invariants

1. **Every cron run has a unique session key.** `runId` prevents two concurrent runs of the same job from sharing state.
2. **Delivery is best-effort with bounded timeout.** `FAILURE_NOTIFICATION_TIMEOUT_MS = 30s` caps how long failure notification delivery can block.
3. **Sessions are reaped.** `session-reaper.ts` ensures completed cron sessions do not persist indefinitely.

## Involved Entities

- [Automation and Cron](../entities/automation-and-cron.md) — concrete implementation
- [Agent Runtime](../entities/agent-runtime.md) — executes the agent turn
- [Session System](../entities/session-system.md) — cron session keys are classified by `isCronSessionKey()`
- [Gateway Control Plane](../entities/gateway-control-plane.md) — integrates `CronService` at startup via `buildGatewayCronService()`

## Source Evidence

| File | Contribution |
|------|-------------|
| `src/cron/service.ts` | `CronService` class and public API |
| `src/cron/service/ops.ts` | Operation implementations |
| `src/cron/schedule.ts` | `Cron` evaluation, LRU cache, `resolveCronTimezone()` |
| `src/cron/isolated-agent.ts` | `runCronIsolatedAgentTurn()` export |
| `src/cron/isolated-agent/run.ts` | Core isolated agent turn execution |
| `src/cron/delivery.ts` | `resolveCronDeliveryPlan()`, `sendFailureNotificationAnnounce()` |
| `src/cron/session-reaper.ts` | Post-run session cleanup |
| `src/cron/heartbeat-policy.ts` | Wake policy for scheduled heartbeats |
| `src/gateway/server-cron.ts` | `buildGatewayCronService()` — gateway integration |

## See Also

- [Automation and Cron](../entities/automation-and-cron.md)
- [Session System](../entities/session-system.md) — cron session key classification
- [Agent Runtime](../entities/agent-runtime.md)
- [Scheduled Job Delivery Flow](../syntheses/scheduled-job-delivery-flow.md)
- [Gateway as Control Plane](gateway-as-control-plane.md)
