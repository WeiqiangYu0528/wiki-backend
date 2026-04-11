# Automation and Cron

## Overview

The cron subsystem is OpenClaw's scheduled automation layer. Rather than delegating to an external job runner, it runs scheduled work as full isolated agent turns — each job execution gets its own namespaced session, executes a complete assistant turn against the configured agent, and then has its session reaped by a dedicated cleanup process. This means scheduled jobs participate in the same session, permission, and delivery infrastructure as interactive turns.

`CronService` is the public interface to this subsystem. It wraps an internal state machine (`createCronServiceState`) and exposes a uniform API for managing jobs, triggering runs, and querying status. Schedule expressions are evaluated using the `croner` library with local-timezone defaulting and an expression cache capped at 512 entries. In addition to standard cron syntax, the subsystem supports ISO 8601 absolute timestamps via `parseAbsoluteTimeMs()`, enabling one-shot future-dated jobs alongside recurring schedules.

Failure handling is a first-class concern. A dedicated delivery module (`src/cron/delivery.ts`) resolves where to send job output and failure notifications, enforces a 30-second timeout on notification delivery, and routes failure announcements through the same outbound pipeline used for interactive replies. The gateway integrates the cron service via `buildGatewayCronService()` in `src/gateway/server-cron.ts`, making all job management operations available as gateway control-plane commands.

## Key Types

### CronService

| Method | Signature | Notes |
|---|---|---|
| `start()` | `(): Promise<void>` | Starts the cron timer loop |
| `stop()` | `(): Promise<void>` | Gracefully stops the timer loop |
| `status()` | `(): CronServiceStatus` | Returns current service health and state |
| `list()` | `(): CronJob[]` | Returns all registered jobs |
| `listPage()` | `(opts): CronJobPage` | Paginated job listing |
| `add()` | `(input: CronJobCreate): Promise<CronJob>` | Creates and persists a new job |
| `update()` | `(id: string, patch: CronJobPatch): Promise<CronJob>` | Applies a partial update to an existing job |
| `remove()` | `(id: string): Promise<void>` | Deletes a job and cancels its timer |
| `run()` | `(id: string, mode?: "due" \| "force"): Promise<CronRunResult>` | Runs a job immediately; `"due"` skips if not yet scheduled, `"force"` always executes |
| `enqueueRun()` | `(id: string, mode?: "due" \| "force"): Promise<void>` | Enqueues a run without blocking the caller |
| `wake()` | `(opts: { mode?: string; text?: string }): Promise<void>` | Triggers a wake-style agent turn (used for notification-driven activation) |

### Core Data Types (`src/cron/types.ts`, `src/cron/types-shared.ts`)

| Type | Key Fields |
|---|---|
| `CronJob` | `id`, `agentId`, `schedule: CronSchedule`, `enabled`, `lastRunAt`, `nextRunAt`, `name`, `description` |
| `CronJobCreate` | Subset of `CronJob` fields required at creation time; `schedule` is required |
| `CronJobPatch` | Partial `CronJob` — any field except `id` may be updated |
| `CronSchedule` | `{ expr?: string; cron?: string; tz?: string; interval?: number }` — `expr`/`cron` hold the cron expression; `tz` overrides timezone; `interval` supports fixed-interval scheduling |

### Schedule Constants

| Constant | Value | Location |
|---|---|---|
| `CRON_EVAL_CACHE_MAX` | `512` expressions | `src/cron/schedule.ts` |
| `FAILURE_NOTIFICATION_TIMEOUT_MS` | `30 000` ms | `src/cron/delivery.ts` |

### Session Key Format

Cron runs use a compound session key that encodes the agent, job, and run identifiers:

```
agent:<agentId>:cron:<jobId>:run:<runId>
```

This key is created when a run begins and passed through `runCronIsolatedAgentTurn()`. The session reaper uses this key to identify and clean up ephemeral cron sessions after the run completes.

## Architecture

### CronService and State Delegation

`CronService` is a thin public facade. The real logic lives in the `createCronServiceState(deps)` factory, which returns an `ops` object containing the implementations of every service method. `CronService` simply delegates each public method call to the corresponding `ops.*` function. This separation keeps the public API stable while allowing the internal implementation to be tested and composed independently of the service class.

Gateway integration (`src/gateway/server-cron.ts`) calls `buildGatewayCronService()` to produce a fully wired `CronService` instance. The gateway then registers cron management methods on the control-plane command surface, so job lifecycle operations are accessible via the same authenticated WebSocket connection used by the Control UI and API clients.

### Schedule Evaluation

Cron expressions are compiled using the `croner` library with `catch: false` (errors propagate rather than being silently swallowed). The compiled expression object is cached in an LRU cache capped at `CRON_EVAL_CACHE_MAX = 512` entries. `resolveCronTimezone()` picks the system timezone via `Intl.DateTimeFormat().resolvedOptions().timeZone` when no explicit `tz` is specified.

For one-shot jobs, `parseAbsoluteTimeMs()` parses an ISO 8601 timestamp and converts it to a millisecond epoch value. The timer subsystem treats this as a special case: it fires once at the specified time and does not reschedule.

### Isolated Agent Execution

Each run is executed by `runCronIsolatedAgentTurn()` (`src/cron/isolated-agent/run.ts`). The function receives the job definition, constructs the compound session key, and invokes the agent runtime in isolation — meaning the cron turn does not share conversation history with interactive sessions unless the job is explicitly configured to target an existing session. The run is fully observable through the standard session event stream.

After the turn completes (success or failure), `session-reaper.ts` identifies the ephemeral cron session by its key pattern and tears it down. This prevents unbounded session accumulation from high-frequency scheduled jobs.

### Delivery and Failure Routing

`resolveCronDeliveryPlan()` determines where to route run output by inspecting the job's configured delivery targets (channels, announcements, notification addresses). `CronFailureDeliveryPlan` encodes the specific routing for failure notifications, which travel through the same outbound announce pipeline as interactive assistant replies. The `FAILURE_NOTIFICATION_TIMEOUT_MS = 30 000` constant sets an upper bound on how long `sendFailureNotificationAnnounce()` will wait for delivery confirmation before abandoning and logging the failure.

## Runtime Behavior

### Job Execution Flow

1. The cron timer fires for a job whose `nextRunAt` has elapsed (or `run(id, "force")` is called explicitly).
2. `CronService.run()` delegates to `ops.run()`, which checks the `"due" | "force"` mode. Under `"due"`, the job is skipped if `nextRunAt` is still in the future.
3. A new run ID is generated and the compound session key `agent:<agentId>:cron:<jobId>:run:<runId>` is formed.
4. `runCronIsolatedAgentTurn()` is called. It starts an isolated agent session using the cron session key and submits the job's configured prompt to the agent runtime.
5. The agent executes a complete assistant turn (tool calls, replies, streaming events) within the isolated session.
6. On successful completion, `resolveCronDeliveryPlan()` routes output to any configured delivery targets.
7. On failure, `sendFailureNotificationAnnounce()` routes a failure notification through the outbound pipeline with a 30-second delivery timeout.
8. After delivery (success or failure), `session-reaper.ts` identifies the session by its `cron:` key pattern and tears it down.
9. `nextRunAt` is updated based on the next evaluation of the cron expression.

### Adding a New Job

1. Caller invokes `CronService.add(input: CronJobCreate)`.
2. The schedule expression in `input.schedule.expr` (or `.cron`) is compiled via `croner` and cached.
3. The job record is persisted.
4. A timer is registered for `nextRunAt`; the job enters the active schedule.

## Source Files

| File | Purpose |
|---|---|
| `src/cron/service.ts` | `CronService` class; `createCronServiceState(deps)` factory; public API surface |
| `src/cron/schedule.ts` | Schedule expression parsing via `croner`; `CRON_EVAL_CACHE_MAX`; `resolveCronTimezone()`; `parseAbsoluteTimeMs()` |
| `src/cron/isolated-agent.ts` | Public export for isolated-agent execution; entry point called by `ops.run()` |
| `src/cron/isolated-agent/run.ts` | `runCronIsolatedAgentTurn()` — core isolated agent turn execution with compound session key |
| `src/cron/delivery.ts` | `resolveCronDeliveryPlan()`; `sendFailureNotificationAnnounce()`; `CronFailureDeliveryPlan`; `FAILURE_NOTIFICATION_TIMEOUT_MS` |
| `src/cron/session-reaper.ts` | Post-run ephemeral session cleanup keyed on `cron:` session key pattern |
| `src/cron/types.ts` | `CronJob`, `CronJobCreate`, `CronJobPatch` type definitions |
| `src/cron/types-shared.ts` | `CronSchedule` and other shared type definitions |
| `src/gateway/server-cron.ts` | `buildGatewayCronService()` — gateway integration wiring |

## See Also

- [Gateway Control Plane](gateway-control-plane.md)
- [Session System](session-system.md)
- [Isolated Agent Automation](../concepts/isolated-agent-automation.md)
- [Scheduled Job Delivery Flow](../syntheses/scheduled-job-delivery-flow.md)
