# Cron System

## Overview

The cron subsystem is Hermes's scheduled automation layer. It does not run a separate kind of agent. Instead, it stores job definitions, wakes up on a scheduler tick, and launches the same Hermes agent runtime in a fresh, tightly scoped session for each due job.

That distinction matters. A cron job is not "a background chat that kept going." It is a stored instruction set made up of a prompt, optional skills, optional script input, schedule metadata, and a delivery target. When the job becomes due, the scheduler creates a new isolated run, lets the main runtime answer once, saves the output to disk, and then optionally routes the final response to a chat platform or leaves it as local output only.

What cron owns is the automation-specific behavior around those pieces: job persistence, schedule parsing, due-job selection, lock ownership, fresh-session isolation, recursion prevention, and delivery routing. The gateway may host the scheduler loop, but cron still defines what a job means and how a scheduled run is allowed to behave.

## Key Interfaces and Configs

The easiest way to understand cron is to look at the job record it stores and the few runtime knobs that change scheduler behavior. Most of the subsystem revolves around these fields rather than around a long list of classes.

| Job field or config | Why it matters at runtime |
| --- | --- |
| `schedule` / `schedule_display` | Defines whether the job is one-shot, interval-based, or cron-expression-based, and controls how `next_run_at` is computed. |
| `repeat.times` / `repeat.completed` | Limits how many successful runs a job may complete before it is disabled or removed. One-shot jobs default to a single completion. |
| `deliver` | Chooses delivery routing: `local`, `origin`, a plain platform name, or an explicit platform target such as `telegram:<chat_id>`. |
| `origin` | Captures the platform, chat, and optional thread/topic from the session that created the job. This is what makes "send it back where it came from" possible later. |
| `skills` | Names the skills whose contents should be loaded into the job prompt before execution. Being listed here affects prompt construction, not schedule timing. |
| `script` | Points to a script under `~/.hermes/scripts/` whose stdout is prepended into the prompt as structured context. |
| `state`, `enabled`, `paused_at`, `paused_reason` | Represent lifecycle state for scheduled, paused, completed, and manually controlled jobs. |
| `next_run_at`, `last_run_at`, `last_status`, `last_error` | Drive due-job selection and preserve enough execution state to resume safely after restarts or failures. |

Cron also relies on a few filesystem and environment conventions:

- Jobs are persisted in `~/.hermes/cron/jobs.json`.
- Per-run output is written to `~/.hermes/cron/output/<job_id>/<timestamp>.md`.
- The tick lock lives at `~/.hermes/cron/.tick.lock`.
- `HERMES_CRON_TIMEOUT` sets the inactivity timeout for a job run. The default is 600 seconds.
- `cron.wrap_response` in `config.yaml` controls whether delivered results are wrapped with a cron-specific heading and footer.
- Platform home-channel environment variables matter when a job delivers to `origin` without a stored origin, or to a plain platform name that needs a default destination.

## Architecture

Cron is built from three cooperating layers.

### Job store and schedule semantics

`cron/jobs.py` is the durable model. It parses schedule strings, stores jobs, updates lifecycle state, computes `next_run_at`, persists repeat counters, and writes output files with secure permissions. It also encodes the main recovery policy after restarts or downtime.

### Scheduler and executor

`cron/scheduler.py` owns the actual tick. On each tick it acquires a file lock, asks the job store for due work, launches fresh runs, saves output, routes delivery, and records completion or failure. It also enforces the key execution constraints: fresh session IDs, fresh session storage, config reloads, and disabled toolsets.

### Management surfaces

`tools/cronjob_tools.py` and `hermes_cli/cron.py` are control planes, not the scheduler itself. The `cronjob` tool is the model-facing surface and applies cron-specific guardrails such as prompt scanning and script-path validation. The CLI is the operator-facing surface and can also run a manual tick, but it still delegates to the same underlying job and scheduler modules.

### Gateway and delivery boundary

The gateway often hosts cron by calling `tick()` from a background maintenance loop and by passing live adapters for delivery. That makes the gateway the usual runtime host for scheduled execution, but not the owner of cron semantics.

The division is clean: cron decides which jobs are due, how they execute, when they are marked complete, and what destination a result should target. The gateway and platform adapters provide the transport needed to actually deliver a message, especially for cases such as encrypted Matrix rooms where a live adapter is preferable to a stateless send.

## Runtime Behavior

### 1. Job creation normalizes the schedule and delivery contract

Jobs can be created from the model-facing `cronjob` tool or from the CLI. Either way, the same creation rules apply.

Cron accepts relative delays, interval schedules, cron expressions, and ISO timestamps for one-time runs.

Creation time is also where several defaults are fixed:

- One-shot schedules default to a single allowed completion if `repeat` is not specified.
- `skill` and `skills` inputs are normalized into a canonical `skills` list.
- Delivery defaults to `origin` when the job was created from a platform session that exposed origin metadata; otherwise it defaults to `local`.

That is why "send the result back here later" works without requiring the user to spell out a chat ID. The creation surface captures the origin context once, stores it into the job record, and the scheduler reuses that record later.

### 2. Due-job selection is conservative, not backlog-hungry

On each tick, cron does not simply run every job whose timestamp is in the past forever. `get_due_jobs()` applies more careful behavior.

One-shot jobs can recover after a restart if they missed their exact run time only recently. The recovery window is intentionally short.

Recurring jobs behave differently. If a job is far behind, cron fast-forwards its next run rather than replaying every missed interval. Cron prefers "resume the recurring schedule from now" over "make up every missed execution."

### 3. Locking gives one tick owner at a time

The scheduler uses a file lock at `~/.hermes/cron/.tick.lock` and attempts to acquire it in nonblocking mode. If another process already owns the lock, the new tick simply skips work and returns.

This matters because both the gateway and manual operator actions may trigger ticks. Cron avoids overlap by making lock ownership the first scheduling decision.

### 4. Recurring jobs advance before execution

Before a recurring job actually runs, the scheduler advances its stored `next_run_at`. This is a deliberate reliability tradeoff.

For recurring jobs, Hermes prefers at-most-once behavior over crash-loop replay. One-shot jobs are treated differently because retrying a missed one-time action after a restart is usually more useful than silently dropping it.

### 5. Each run gets a fresh isolated session

When a job is due, `run_job()` launches the normal `AIAgent`, but it does so under strict session constraints:

- a new cron session ID is created
- a fresh `SessionDB` handle is used
- `.env` and config are reloaded for that run
- provider, model, and base URL overrides are resolved again
- `skip_memory=True` disables memory writes and reads
- `platform="cron"` marks the session as automation-originated

Several toolsets are also disabled: `cronjob`, `messaging`, and `clarify`.

These choices define the cron boundary. A scheduled run is not allowed to create or mutate cron jobs recursively, ask clarifying questions, send its own platform messages directly, or write into the user-memory system.

This is also why cron deliveries are intentionally separate from ordinary conversation history. The delivery may arrive in a room or chat, but the execution itself happened in a dedicated cron session that is not the same as the user's ongoing conversational thread inside Hermes.

### 6. Prompt assembly pulls in script output and skill content

Cron job prompts are built in a fixed order.

First, the scheduler adds a cron-specific system hint. It tells the agent that it is running as a scheduled job, that the final response will be auto-delivered, that it should not try to use messaging tools, and that it may return exactly `[SILENT]` if there is nothing worth sending.

Second, if the job references a script, cron runs that script from inside `~/.hermes/scripts/` and prepends its stdout into the prompt. This is the supported way to gather live context before the agent thinks. The script runner enforces path restrictions, applies a timeout, and treats failures as explicit prompt context or execution errors.

Third, cron resolves each configured skill and injects the full skill content into the prompt. If a named skill is missing, the prompt includes a warning note so the resulting response can acknowledge degraded behavior.

Only after that scaffolding is in place does the scheduler append the user-authored job prompt.

### 7. Delivery routing is explicit and separate from execution

A cron run always saves an output document. Delivery is a second step.

The routing rules are:

- `local`: do not send a platform message; keep the result in cron output storage only
- `origin`: deliver to the stored origin platform/chat/thread if present, otherwise fall back to a configured home channel for a known platform
- plain platform name such as `telegram`: if the origin platform matches, reuse the origin chat/thread; otherwise use that platform's configured home channel
- explicit target such as `discord:<channel>` or a target with thread/topic metadata: resolve and deliver there

If the scheduler has access to live gateway adapters and an event loop, it prefers that delivery path because some platforms need live session context for reliable sending. Otherwise it falls back to standalone send helpers.

The message can also be wrapped with a cron header and footer. The footer makes the isolation model explicit to the human recipient: the agent cannot see replies to that delivered message unless a new ordinary session is started.

### 8. Completion, silence, and failure handling

After execution, cron always writes a markdown output file containing the prompt and result or the error context. That file write is not conditional on successful delivery.

Delivery then follows three main outcomes:

1. A successful run with a normal final response is delivered if the job's target is not `local`.
2. A successful run whose final response is exactly `[SILENT]` suppresses delivery, but the run is still recorded and the output file is still saved.
3. A failed run produces an error summary for delivery, because failures are operationally significant even when the normal result would have been silent.

Finally, `mark_job_run()` updates `last_run_at`, `last_status`, `last_error`, repeat counters, and `next_run_at`. If the repeat limit is reached, the job is completed or removed. If no future run remains, the job is disabled and marked complete.

Cron uses an inactivity timeout, not just a total wall-clock budget. If a run stops making progress for too long, Hermes interrupts it and marks the job as failed.

### End-to-end example

Consider a job created from a Telegram chat with:

- schedule: `every day at 09:00`
- skills: `daily-briefing`
- script: `news_snapshot.sh`
- deliver: left unspecified

The runtime story is:

1. The `cronjob` tool captures the Telegram chat as `origin`, normalizes the skill list, parses the schedule, and stores the job in `jobs.json`.
2. On a later gateway tick, `get_due_jobs()` sees that the job is due and the tick acquires the lock.
3. Because the job is recurring, cron advances the next scheduled slot before execution.
4. `run_job()` creates a fresh cron session, reloads config and provider settings, disables `cronjob`, `messaging`, and `clarify`, and skips memory.
5. The scheduler runs `news_snapshot.sh`, prepends its stdout, injects the `daily-briefing` skill, appends the saved prompt, and invokes the normal agent runtime.
6. If the final response is ordinary text, cron delivers it back to the original Telegram chat. If the response is `[SILENT]`, nothing is sent, but the output markdown is still stored under `~/.hermes/cron/output/...`.
7. The job state is updated with the new `last_run_at`, status, and next daily run.

## Source Files

These files are the best anchors if you need to verify the mechanism described above rather than just browse names:

- `hermes-agent/cron/jobs.py`: job schema, schedule parsing, due-job selection, repeat handling, persistence, output files, and recovery behavior
- `hermes-agent/cron/scheduler.py`: tick ownership, fresh-session execution, disabled toolsets, prompt construction, delivery routing, and failure handling
- `hermes-agent/tools/cronjob_tools.py`: model-facing creation and lifecycle management, including prompt scanning and script-path restrictions
- `hermes-agent/hermes_cli/cron.py`: operator-facing control surface and manual tick entry points
- `hermes-agent/tests/cron/`: the clearest place to confirm guarantees such as recursion prevention, timeout behavior, silent delivery suppression, and delivery/error handling
- `hermes-agent/website/docs/developer-guide/cron-internals.md` and `hermes-agent/website/docs/user-guide/features/cron.md`: concise cross-checks for the intended maintainer and user mental model

Taken together, these sources show that cron is best understood as "scheduler plus policy around a normal Hermes run," not as a separate agent engine.

## See Also

- [Gateway Runtime](gateway-runtime.md)
- [CLI Runtime](cli-runtime.md)
- [Tool Registry and Dispatch](tool-registry-and-dispatch.md)
- [Session Storage](session-storage.md)
- [Cron Delivery and Platform Routing](../syntheses/cron-delivery-and-platform-routing.md)
