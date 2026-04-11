# Scheduled Job Delivery Flow

## Overview

This synthesis traces the complete path a scheduled OpenClaw job takes from the moment a cron expression fires to the point where output is delivered (or failure is reported) and the session is cleaned up. No single entity page shows this full path because the work crosses at least four subsystems — schedule evaluation, isolated agent execution, delivery routing, and session lifecycle — each with distinct ownership.

The central insight is that cron jobs in OpenClaw are not shell scripts. They are complete agent turns running inside isolated, namespaced sessions. The same model selection, skill injection, tool access, and delivery pipeline that handles an interactive Discord message also handles a midnight scheduled report. The only structural difference is the session key and how delivery is resolved.

## Systems Involved

| System | Role in This Flow |
|---|---|
| [Automation and Cron](../entities/automation-and-cron.md) | `CronService`, schedule evaluation, delivery, session reaper |
| [Agent Runtime](../entities/agent-runtime.md) | Config resolution, skill loading, model execution |
| [Session System](../entities/session-system.md) | Session key schema, lifecycle events, key classifiers |
| [Isolated Agent Automation](../concepts/isolated-agent-automation.md) | Architectural pattern that cron implements |
| `src/gateway/server-cron.ts` | Gateway integration wiring via `buildGatewayCronService()` |

## Schedule Evaluation and Trigger

### Expression Evaluation

Schedule expressions are evaluated by `src/cron/schedule.ts` using the `croner` library. A `Cron` object is constructed with `catch: false`, which means malformed expressions raise exceptions rather than silently failing. The compiled `Cron` object is stored in an LRU cache capped at `CRON_EVAL_CACHE_MAX = 512` entries. Jobs that fire frequently do not recompile their expression on every tick — the cache returns the previously compiled object, making high-frequency schedule evaluation cheap.

`resolveCronTimezone()` determines the timezone for expression evaluation. When a job's `CronSchedule` includes an explicit `tz` field, that value is used directly. When `tz` is absent, `resolveCronTimezone()` calls `Intl.DateTimeFormat().resolvedOptions().timeZone` to read the local system timezone. This means a job with `cron: "0 9 * * *"` and no `tz` fires at 9 AM in whatever timezone the gateway process is running on.

For one-shot future jobs, `parseAbsoluteTimeMs()` accepts an ISO 8601 absolute timestamp and converts it to a millisecond epoch value. The timer treats these as non-recurring: it fires once and does not reschedule.

### Job Trigger: `CronService.run(id, mode)`

When a job's `nextRunAt` elapses, the timer loop calls `CronService.run(id, mode)`, delegating to `ops.run()` inside `createCronServiceState`. The `mode` parameter controls whether the check proceeds:

- `"due"` — the job runs only if `nextRunAt` is in the past. If the timer fires slightly early due to system scheduling jitter, `"due"` mode skips the run and waits for the next tick. This is the mode used for normal scheduled execution.
- `"force"` — the job runs unconditionally regardless of `nextRunAt`. This mode is used for manual testing, administrative intervention, and the `enqueueRun()` path when an operator explicitly triggers a job from the Control UI or API.

After `ops.run()` decides to proceed, a new `runId` is generated. This UUID becomes part of the session key constructed next.

## Isolated Agent Execution

### Session Key Construction

Before any agent code runs, a compound session key is formed:

```
agent:<agentId>:cron:<jobId>:run:<runId>
```

All four segments carry meaning. `agentId` routes the turn to the correct agent config and workspace. `cron` marks the session as a cron session (detectable by `isCronSessionKey()` in `src/sessions/session-key-utils.ts`). `jobId` ties the session to its originating job record. `runId` is a fresh UUID for every execution.

The `runId` segment is the concurrency safeguard. Without it, two concurrent executions of the same job — possible during a slow run that overlaps the next scheduled fire — would share a session key and potentially corrupt each other's transcript state. With `runId`, each execution occupies a distinct key. The session system, transcript storage, and permission checks all scope to the full key, so concurrent runs of job `abc` become `agent:main:cron:abc:run:uuid1` and `agent:main:cron:abc:run:uuid2` — completely separate namespaces.

### `runCronIsolatedAgentTurn()` Steps

`runCronIsolatedAgentTurn()` in `src/cron/isolated-agent/run.ts` is the core execution function. It receives the job definition, the constructed session key, and produces a `RunCronAgentTurnResult`. Internally it follows the same sequence as an interactive turn:

1. **Config resolution** — `resolveSessionAgentIds()` extracts `agentId` from the session key and confirms which agent handles this run. `resolveAgentWorkspaceDir()` and `resolveOpenClawAgentDir()` locate the workspace and agent directory on disk.

2. **Skill loading** — `resolveEffectiveAgentSkillFilter()` reads the per-agent skill filter from config. Skills are loaded from disk by `src/agents/skills/local-loader.ts`. Skills marked `always: true` in their frontmatter are injected unconditionally. The same skill set available to interactive turns is available here — cron jobs are not restricted to a subset of capabilities.

3. **Tool assembly** — bash tools, process tools, and any plugin-contributed tools are assembled for the turn.

4. **Model execution** — the agent runtime streams a reply from the Anthropic API via `anthropic-transport-stream.ts`. Tool calls are dispatched and their results fed back into the loop. The full assistant turn runs to completion.

5. **Result capture** — `RunCronAgentTurnResult` indicates success, failure, or partial completion and carries the output for delivery.

The turn is fully observable through the standard session event stream. Transcript events flow through `src/sessions/transcript-events.ts`, making the run visible in the Control UI alongside interactive sessions.

## Delivery and Failure Notification

### `resolveCronDeliveryPlan()`

After the agent turn completes, `src/cron/delivery.ts` decides where output goes. `resolveCronDeliveryPlan()` inspects four fields on the cron job record:

- `channel` — the channel type to route output through (e.g., a messaging platform integration).
- `to` — the specific peer or destination within that channel (e.g., a user ID or room ID).
- `accountId` — which channel account to use for sending.
- `sessionKey` — if set, routes output to an existing session rather than creating a new delivery target.

If a job has no explicit destination fields, output is delivered to the job's configured channel account. The delivery plan produced by `resolveCronDeliveryPlan()` is then executed by `deliverOutboundPayloads()`, which uses the same outbound pipeline as interactive assistant replies.

### Delivery Strategy

The selection logic inside `resolveCronDeliveryPlan()` works in priority order:

1. If `sessionKey` is set, deliver into that session's channel context — the output appears as if it came from an interactive session.
2. Otherwise, if `channel` + `to` + `accountId` are all present, construct a targeted delivery address and send to that peer.
3. Otherwise, fall back to the job's channel account default.

This means a cron job can be configured to post a morning summary into a specific Slack channel, reply into an ongoing Discord DM thread, or simply emit to the gateway's default output channel. The delivery plan is resolved fresh for each run, so a job's destination can be changed between executions by updating the job record.

### Failure Delivery

When `runCronIsolatedAgentTurn()` returns a failure result, the flow diverges to `resolveFailureDestination()`. This function reads a separate failure routing configuration from the job record, allowing failure notifications to go to a different destination than success output — for example, a dedicated alerts channel.

`sendFailureNotificationAnnounce()` then sends the failure notification through the outbound announce pipeline. A hard timeout of `FAILURE_NOTIFICATION_TIMEOUT_MS = 30000` ms (30 seconds) caps how long delivery can block. If the underlying channel is unavailable or the send hangs, delivery is abandoned and the failure is logged locally. This prevents a broken notification channel from blocking the job execution loop indefinitely.

## Session Lifecycle and Cleanup

### Session Reaper

After delivery (success or failure), `src/cron/session-reaper.ts` runs. It identifies the ephemeral cron session in the gateway's session registry by matching the session key against the `cron:` key pattern (detectable via `isCronSessionKey()` and `isCronRunSessionKey()`). The session record is removed from the registry.

Without the reaper, high-frequency scheduled jobs would accumulate sessions indefinitely, consuming memory and polluting the session list visible in the Control UI. The reaper is the mechanism that makes recurring jobs safe to run at high frequency.

Session lifecycle events (`SessionLifecycleEvent` from `src/sessions/session-lifecycle-events.ts`) are emitted at both the start and end of the run, allowing the Control UI and any subscribed clients to observe the full session lifetime even for short-lived cron sessions.

### Heartbeat: `wake()`

`CronService.wake()` dispatches a wake signal with one of two modes:

- `"now"` — immediately unblocks the gateway's sleep state. Used when a cron job needs to trigger immediate processing.
- `"next-heartbeat"` — schedules a wakeup at the next heartbeat interval. Used for softer activation that does not need to interrupt the current sleep cycle.

`wake()` integrates with `heartbeat-policy.ts` to control whether a cron job's heartbeat can wake a sleeping gateway. This is the mechanism by which cron jobs can drive periodic agent activity even when no interactive user is present.

After each run, `nextRunAt` is updated by re-evaluating the cron expression against the current time, scheduling the next tick.

## Cron vs Interactive Sessions

| Dimension | Cron Session | Interactive Session |
|---|---|---|
| Key format | `agent:<agentId>:cron:<jobId>:run:<runId>` | `agent:<agentId>:<channel>:<peerKind>:<peerId>` |
| Key classifier | `isCronSessionKey()`, `isCronRunSessionKey()` | No `cron:` prefix; matched by channel/peer pattern |
| Session scope | Unique per run; `runId` prevents collision | Persistent across reconnects for same peer |
| Lifecycle | Ephemeral: created at run start, reaped by `session-reaper.ts` | Persistent: survives channel reconnects |
| Delivery resolution | `resolveCronDeliveryPlan()` using job's `channel`/`to`/`accountId`/`sessionKey` | Direct channel response to originating peer |
| Failure routing | Separate `resolveFailureDestination()` path with 30 s timeout | Error surfaced in same channel as the message |
| Concurrency | Each run isolated by `runId`; parallel runs allowed | One active turn per session key |
| Trigger | Timer or `run(id, "force")` | Inbound channel message |
| Transcript persistence | Per-run transcript; successive runs produce separate transcripts | Continuous transcript across turns |

## Job Configuration Reference

A `CronJob` record contains the following fields:

| Field | Type | Purpose |
|---|---|---|
| `id` | `string` | Unique job identifier |
| `agentId` | `string` | Agent that executes the job turn |
| `name` | `string` | Human-readable name shown in Control UI |
| `description` | `string` | Optional description of what the job does |
| `enabled` | `boolean` | Whether the job participates in the timer loop |
| `schedule` | `CronSchedule` | Schedule definition (see below) |
| `lastRunAt` | `Date \| null` | Timestamp of the most recent run |
| `nextRunAt` | `Date \| null` | Timestamp of the next scheduled run |
| `channel` | `string \| undefined` | Delivery channel type for output |
| `to` | `string \| undefined` | Delivery peer/destination within the channel |
| `accountId` | `string \| undefined` | Channel account to use for sending |
| `sessionKey` | `string \| undefined` | Target session key for output delivery |

The `CronSchedule` type controls when the job fires:

| Field | Type | Purpose |
|---|---|---|
| `expr` / `cron` | `string` | Standard cron expression (e.g. `"0 9 * * *"`) |
| `tz` | `string \| undefined` | Timezone override; defaults to system timezone via `resolveCronTimezone()` |
| `interval` | `number \| undefined` | Fixed-interval scheduling in milliseconds |

## Operational Monitoring

### Determining Whether a Job Ran

Each cron run creates a session with key `agent:<agentId>:cron:<jobId>:run:<runId>`. The Control UI shows sessions matching the `cron:` key pattern. A completed run will have a session that has been reaped (removed from the registry) but whose transcript remains accessible. A run currently in progress will appear as an active session.

`CronService.list()` and `CronService.listPage()` return all job records with `lastRunAt` and `nextRunAt` populated. `lastRunAt` being recent confirms a run occurred; comparing it to the expected schedule interval confirms the job is firing on time.

### Determining What Ran

Each run's transcript is stored under its unique session key. Because `runId` makes each session key distinct, transcripts from successive runs of the same job do not overwrite each other. To inspect what a specific run did, look up the session by its full key `agent:<agentId>:cron:<jobId>:run:<runId>`. The transcript shows the submitted prompt, all tool calls, and the final assistant reply.

### Determining What Failed

Failed runs trigger `sendFailureNotificationAnnounce()` through the outbound announce pipeline. The failure notification is delivered to the destination resolved by `resolveFailureDestination()`. If delivery itself fails or times out after 30 seconds, the failure is logged by the gateway process.

To audit failures without relying on notification delivery, inspect the `RunCronAgentTurnResult` logged by the cron service on run completion. Session lifecycle events (`SessionLifecycleEvent`) are emitted at the start and end of every cron session, with the `reason` field indicating termination cause. A gateway log search for `cron:<jobId>` combined with failure lifecycle events identifies all failed runs for a specific job.

`CronService.status()` returns the current health of the timer service itself, which is distinct from individual job success or failure. A healthy service with a failing job will still show a healthy status — the job-level outcome is in `lastRunAt` and the session transcript, not the service status.

## Source Evidence

| File | Contribution to This Flow |
|---|---|
| `src/cron/service.ts` | `CronService` class; `createCronServiceState(deps)` factory; `run(id, mode)` public API |
| `src/cron/service/ops.ts` | `ops.run()` — checks `"due" \| "force"` mode, generates `runId`, orchestrates execution |
| `src/cron/schedule.ts` | `Cron` expression parsing via `croner`; `CRON_EVAL_CACHE_MAX = 512`; `resolveCronTimezone()`; `parseAbsoluteTimeMs()` |
| `src/cron/isolated-agent.ts` | Public export for isolated-agent execution |
| `src/cron/isolated-agent/run.ts` | `runCronIsolatedAgentTurn()` — session key construction, config resolution, skill loading, model execution |
| `src/cron/delivery.ts` | `resolveCronDeliveryPlan()`; `resolveFailureDestination()`; `sendFailureNotificationAnnounce()`; `FAILURE_NOTIFICATION_TIMEOUT_MS = 30000` |
| `src/cron/session-reaper.ts` | Post-run ephemeral session removal from gateway registry |
| `src/cron/heartbeat-policy.ts` | `wake()` mode policy; `"now"` vs `"next-heartbeat"` dispatch |
| `src/cron/types.ts` | `CronJob`, `CronJobCreate`, `CronJobPatch` type definitions |
| `src/cron/types-shared.ts` | `CronSchedule` type definition |
| `src/sessions/session-key-utils.ts` | `isCronSessionKey()`, `isCronRunSessionKey()`, `parseAgentSessionKey()` |
| `src/sessions/session-lifecycle-events.ts` | Lifecycle event emission and subscription for cron session start/end |
| `src/agents/agent-scope.ts` | `resolveSessionAgentIds()`, `resolveDefaultAgentId()` — agent config resolution |
| `src/agents/skills/agent-filter.ts` | `resolveEffectiveAgentSkillFilter()` — per-agent skill filter applied during execution |
| `src/gateway/server-cron.ts` | `buildGatewayCronService()` — gateway integration wiring |

## See Also

- [Automation and Cron](../entities/automation-and-cron.md) — full entity reference for `CronService` and subsystem internals
- [Agent Runtime](../entities/agent-runtime.md) — execution core that runs the isolated agent turn
- [Session System](../entities/session-system.md) — session key schema and lifecycle events
- [Isolated Agent Automation](../concepts/isolated-agent-automation.md) — conceptual overview of cron-as-agent-turns
- [Inbound Message to Agent Reply Flow](inbound-message-to-agent-reply-flow.md) — interactive counterpart to this flow
- [Gateway As Control Plane](../concepts/gateway-as-control-plane.md) — how `CronService` integrates into the gateway control surface
