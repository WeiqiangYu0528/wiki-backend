# Cron Delivery and Platform Routing

## Overview

Cron in Hermes is scheduled automation, but it is not a separate agent runtime. When a job becomes due, Hermes starts a fresh isolated run, executes the normal agent stack once, saves the result locally, and then decides whether and where to deliver the final response.

That separation is the main idea of this synthesis. Cron owns timing and isolation. Gateway delivery owns how a response reaches a chat platform. The two are connected in the runtime, but they are not the same responsibility. Cron reuses the gateway delivery infrastructure because the outbound send problem is shared, yet the scheduled run itself stays isolated from ordinary chat sessions.

## Systems Involved

- [Cron System](../entities/cron-system.md)
- [Gateway Runtime](../entities/gateway-runtime.md)
- [Messaging Platform Adapters](../entities/messaging-platform-adapters.md)
- [Session Storage](../entities/session-storage.md)

## Interaction Model

The end-to-end flow is easiest to understand in ordered stages.

1. The scheduler finds a due job.
2. The scheduler advances recurring jobs before execution so a crash does not replay them on restart.
3. Hermes launches a fresh cron session with its own session ID, fresh session storage handle, and cron-specific tool restrictions.
4. The job prompt is assembled from the saved prompt, optional skill content, and optional script output.
5. The normal `AIAgent` run produces a final response.
6. Hermes always saves the job output to disk.
7. Hermes resolves the delivery target and decides whether to send the result to a platform or keep it local.
8. If delivery is enabled and the response is not silent, Hermes routes it through the gateway delivery layer, preferably through a live adapter when one exists.
9. Hermes updates job state, repeat counters, and next-run time.

The important boundary is between steps 3 to 5 and steps 7 to 9. Execution is isolated from the rest of the product. Delivery can still reuse the gateway stack, but the cron run itself does not become part of an ordinary conversation thread.

## Why Cron Stays Isolated

Cron jobs are not allowed to behave like background chat turns. If they inherited normal gateway session state, they could pollute conversation history, violate message alternation rules, or accidentally act as if they were part of a user’s live thread.

Hermes avoids that by giving each cron run a fresh session identity and a restricted runtime:

- no inherited conversation history
- memory reads and writes are skipped
- `cronjob`, `messaging`, and `clarify` toolsets are disabled
- the session is marked as `platform="cron"`

That isolation matters even when the final response is delivered back to a chat platform. The delivered message is not the same thing as the execution session. The session is private to cron. The delivery is an outbound message routed after the run completes.

## Key Interfaces

| Interface | Role in the flow |
| --- | --- |
| `tick()` in `cron/scheduler.py` | Owns due-job selection, isolated execution, and the final handoff into delivery. |
| `_resolve_delivery_target(...)` | Turns the job's `deliver` value plus origin/config data into one concrete destination. |
| `save_job_output(...)` | Persists the full local audit record regardless of whether platform delivery happens. |
| `SILENT_MARKER` | Suppresses outbound delivery without suppressing local output or state advancement. |
| `mark_job_run(...)` | Advances repeat counters, statuses, errors, and `next_run_at` after execution. |
| live adapter delivery path | Reuses an already-connected gateway adapter when available before falling back to standalone send helpers. |

## Delivery Target Resolution

Cron supports a small routing language, but the resolution order is subtle. The scheduler turns the job’s `deliver` field into a concrete destination, and that destination can come from the job itself, the stored origin, or platform configuration.

| Delivery spec | What it resolves to |
| --- | --- |
| `local` | No platform delivery. The output stays in cron storage only. |
| `origin` | The chat, thread, or room where the job was created, if that origin was stored. |
| `origin` without origin metadata | A configured home channel for a known platform, if one exists. |
| Plain platform name such as `telegram` | The origin chat if the job originated on that platform, otherwise that platform’s configured home channel. |
| Explicit target such as `telegram:123456` or `discord:#team` | The explicit chat, channel, or thread after target parsing and directory resolution. |

Two details are important here.

First, `local` is not a failed delivery. It is a valid output mode. Cron still saves the output file, but it does not emit a platform message.

Second, `origin` is not just a synonym for “reply somewhere.” It means “send back where this job came from,” and if the original origin is missing, Hermes falls back to platform home channels instead of silently dropping the result.

This routing logic is implemented in `hermes-agent/cron/scheduler.py` and then delivered through the same outbound path used by gateway messaging. That is the reuse boundary. Cron owns the policy for which destination should be used. Gateway delivery owns the mechanics of actually sending the message.

## Where Output Is Saved

Cron always writes a local output document, even when it also delivers the result to a platform.

The scheduler calls `save_job_output(...)` after the job run completes, and the saved markdown file becomes the audit record for the run. That file is independent of delivery. A job can be local-only, silently suppressed, or actively delivered, and the output file still exists either way.

When the platform message would exceed the configured output size, the delivery layer truncates the outbound content and saves the full result to disk. That means output persistence is not optional, it is part of the delivery path itself.

## SILENT, Delivery, And State Advancement

The `SILENT` marker is a suppression signal, not a special failure mode.

If the agent’s final response is exactly `[SILENT]`, the scheduler skips platform delivery but still saves the output file and still advances job state. This is the right behavior for cron jobs that only need side effects, file writes, or local audit trails.

The runtime order matters:

1. The job runs.
2. The full output is saved locally.
3. The final response is inspected for `[SILENT]`.
4. Delivery is skipped if the marker is present.
5. `mark_job_run(...)` updates `last_run_at`, `last_status`, `last_error`, repeat counters, and `next_run_at`.

Recurring jobs are also advanced before execution, not after it. That pre-advance is the crash-safety rule. If the process dies mid-run, the job should not refire endlessly on restart.

In other words, `SILENT` suppresses outbound messaging, not bookkeeping.

## How Live Adapter Reuse Works

Cron does not need a separate outbound stack when the gateway is already running.

When `tick()` is called with live adapters and an event loop, the delivery layer prefers the live adapter path first. That matters for platforms that benefit from an already-authenticated, already-connected session, especially cases like Matrix where the standalone path may be less capable for encrypted or session-sensitive delivery.

If the live adapter path is unavailable or fails, Hermes falls back to the standalone send helpers. So delivery has two layers:

- the gateway adapter path, when a live platform connection exists
- the standalone sender path, when it does not

That reuse is intentional. Cron is not reimplementing platform sending. It is borrowing the gateway’s delivery machinery while keeping scheduled execution itself separate from gateway conversation handling.

## End-to-End Example

Consider a daily cron job created from a Telegram conversation with no explicit `deliver` field.

1. Job creation stores the Telegram origin and defaults delivery to `origin`.
2. The scheduler later sees the job is due.
3. Because it is recurring, `next_run_at` is advanced before the run begins.
4. Hermes starts a fresh cron session, disables recursive and conversational toolsets, and runs the agent once.
5. The job output is written to `~/.hermes/cron/output/<job_id>/...`.
6. If the response is ordinary text, the scheduler resolves `origin` back to the Telegram chat and uses gateway delivery to send the response.
7. If the response is `[SILENT]`, nothing is delivered, but the run is still recorded and the next occurrence is still scheduled.
8. `mark_job_run(...)` persists the final state change.

That sequence is the pattern to keep in mind. Cron execution is isolated. Delivery is routed. State always advances.

## Source Evidence

The strongest anchors for this page are:

- `hermes-agent/cron/scheduler.py` for due-job execution, file locking, session setup, `SILENT` suppression, output saving, and delivery handoff.
- `hermes-agent/cron/jobs.py` for job creation, schedule normalization, repeat handling, `next_run_at` advancement, and final job-state updates.
- `hermes-agent/gateway/delivery.py` for delivery-target parsing, origin and home-channel resolution, local output, and live-adapter fallback.
- `hermes-agent/gateway/platforms/` for platform-specific send behavior and adapter reuse.
- `hermes-agent/website/docs/developer-guide/cron-internals.md` for the maintainer-facing version of the same model.

Taken together, these sources show that cron is best understood as “isolated scheduled execution plus routed delivery,” not as a distinct agent runtime.

## See Also

- [Cron System](../entities/cron-system.md)
- [Gateway Runtime](../entities/gateway-runtime.md)
- [Messaging Platform Adapters](../entities/messaging-platform-adapters.md)
- [Session Storage](../entities/session-storage.md)
