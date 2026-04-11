# Environment Abstraction for Agent Execution

## Overview

Hermes does not bind agent commands to one shell or one sandbox type. It treats the execution environment as an abstraction because the same agent has to run across product and research surfaces that do not all want the same placement model.

In plain terms: the model says “run this command,” and Hermes decides where it should execute. The same command path must work for the interactive CLI, gateway-style sessions, cron or batch jobs, and research rollouts. A local shell is one backend. Docker, SSH, Modal, Daytona, and Singularity are other backends with different isolation and persistence properties.

## Why Hermes Uses An Abstraction

Hermes needs one execution contract for a few reasons:

1. The product has multiple front doors. CLI sessions, gateway sessions, and automation surfaces all need terminal commands.
2. The research stack reuses the same agent behavior for rollouts, scoring, and training.
3. The runtime has to make approval, persistence, and cleanup decisions consistently.
4. Task identity matters. Hermes needs to know which commands belong to which session so it can reuse the right sandbox and tear down the right resources.

If Hermes tied commands to one shell implementation, every new surface would either duplicate command logic or accept a narrower execution model. The abstraction keeps the behavior stable while allowing the transport to vary.

## Mechanism

The execution path is intentionally layered.

### 1. The surface issues a terminal call

The model-facing `terminal` tool is the entry point. The tool runtime does not promise “local subprocess.” It promises “execute this command in the environment configured for this task and return a normalized result.”

At runtime, `hermes-agent/tools/terminal_tool.py` owns that handoff. It resolves the active backend, applies environment-specific overrides, and caches execution environments by `task_id`.

### 2. Hermes resolves a backend for the task

`TERMINAL_ENV` selects the backend family, and per-task overrides can refine the choice. The supported backends are:

- `local`
- `docker`
- `ssh`
- `modal`
- `daytona`
- `singularity`

The important detail is not the list itself. The important detail is that all of these are different realizations of the same interface. `tools/environments/base.py` defines the common contract through `BaseEnvironment`, and each backend implements `execute(...)` plus `cleanup()`.

### 3. Hermes reuses the environment by task identity

The environment is cached under the task’s identity, not recreated for every command. That means repeated calls in the same task usually hit the same backend object and, when supported, the same live shell or persistent sandbox.

This is where task identity becomes a real runtime guarantee. The `task_id` is not just bookkeeping. It is the key that ties together:

- environment reuse
- filesystem continuity
- background process tracking
- teardown and idle cleanup

### 4. Approval happens before execution

Hermes keeps policy separate from transport. Before the backend runs the command, `terminal_tool()` runs the guard checks. If the command is dangerous, blocked, or waiting for user approval, execution stops there.

That separation matters because the approval layer does not care whether the command would have run locally or in Modal. It only cares whether the command is allowed. The backend is only responsible for carrying out an already-approved command.

### 5. The backend executes and Hermes normalizes the result

After approval, the backend performs the work. Hermes then normalizes the response into a stable tool result shape so higher layers do not need backend-specific handling for ordinary success, failure, or timeout cases.

This is what makes the abstraction useful in practice: the caller gets one tool contract even though the runtime may have used very different infrastructure underneath.

## Shared Guarantees and Backend Differences

The abstraction shares some guarantees across every backend while leaving other behavior backend-specific.

| Property | Shared Across Backends | Varies by Backend |
| --- | --- | --- |
| Tool contract | Yes. `terminal` returns a normalized result shape. | No. The transport used to execute the command differs. |
| Approval boundary | Yes. Guard checks run before execution. | No. Some surfaces collect human approval differently. |
| Task identity | Yes. `task_id` scopes reuse and cleanup. | No. The actual state attached to that task can differ. |
| Environment reuse | Yes. Hermes caches active environments by task. | No. Reuse may mean a live shell, a resumed container, or a reused remote session. |
| Filesystem persistence | Sometimes. Hermes can preserve state when the backend supports it. | Yes. Docker, Modal, Daytona, and Singularity model persistence differently. |
| Live shell continuity | Sometimes. Local and SSH can keep a persistent shell. | Yes. Container and cloud backends care more about sandbox persistence than one shell process. |
| Resource cleanup | Yes. Backends must implement cleanup. | No. Cleanup semantics depend on the backend and transport. |

Shared behavior lives in the abstraction; placement-specific behavior lives in the backend.

## What The Backends Actually Guarantee

It is easy to blur three different kinds of continuity, so Hermes keeps them distinct.

| Guarantee | What It Means | What It Does Not Mean |
| --- | --- | --- |
| Same cached environment | Hermes reuses the same backend object for the same task. | It does not guarantee that a shell process is still alive. |
| Persistent filesystem | Files written in the sandbox can survive between commands. | It does not guarantee that the same process or shell state survives. |
| Persistent live shell | The backend keeps one shell process alive so cwd and shell variables can carry forward. | It does not guarantee that the whole sandbox is immortal or that cleanup can never interrupt it. |

This distinction is the core invariant of the subsystem. Hermes reuses environment identity, but the strength of the underlying persistence depends on the backend.

## Why This Matters Across Surfaces

### CLI and gateway sessions

For interactive users, the abstraction keeps the command model consistent. A person can ask Hermes to inspect files, run tests, or edit code without caring whether the runtime selected a local shell or a remote sandbox.

In gateway-style sessions, the same abstraction also makes approval workable. The policy layer can block or request confirmation before the command touches any backend. That is especially important when the execution surface is remote, shared, or long-lived.

### Cron and batch jobs

Scheduled or batch-driven runs need the same terminal semantics, but they usually care more about reproducibility and teardown than interactive shell continuity.

### Research and evaluation

The research stack reuses the same execution model instead of inventing a parallel one. `HermesAgentBaseEnv` in `hermes-agent/environments/hermes_base_env.py` sets `TERMINAL_ENV` and related timeout/lifetime settings so Hermes tools behave consistently inside Atropos rollouts. `ToolContext` gives reward and verification code access to the same task-scoped state the agent used during the rollout.

Research surfaces are another consumer of the same Hermes execution semantics, so the abstraction has to be stable enough for training, evaluation, and reward computation.

## Invariants And Implications

The subsystem has a few invariants worth stating directly:

1. Commands are always routed through a task-scoped environment.
2. Approval is a separate step from execution.
3. The backend choice can change, but the tool contract should not.
4. Persistence is not a single binary property; filesystem persistence and live-shell persistence are separate concerns.
5. Task identity is the key to reuse, cleanup, and continuity.

Those invariants imply a few design constraints:

- If a backend cannot provide a live shell, Hermes still needs a normal `execute(...)` path.
- If a surface needs strong reproducibility, it should rely on the shared contract, not on accidental shell state.
- If a verifier or benchmark needs to inspect the world after a rollout, it should do so through the task-scoped environment, not by assuming the run happened on the host.

This is why the abstraction is not just architectural neatness. It is what keeps policy, persistence, and evaluation from drifting apart.

## Source Evidence

The best anchors for this page are:

- `hermes-agent/tools/terminal_tool.py` for backend resolution, caching, approval checks, and normalization.
- `hermes-agent/tools/environments/base.py` for the shared backend contract.
- `hermes-agent/tools/environments/local.py`, `docker.py`, `ssh.py`, `modal.py`, `daytona.py`, and `singularity.py` for concrete transports.
- `hermes-agent/environments/hermes_base_env.py` and `hermes-agent/environments/tool_context.py` for the research-side bridge.

## See Also

- [Terminal and Execution Environments](../entities/terminal-and-execution-environments.md)
- [Research and Batch Surfaces](../entities/research-and-batch-surfaces.md)
- [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md)
- [Tool Call Execution and Approval Pipeline](../syntheses/tool-call-execution-and-approval-pipeline.md)
- [Agent Loop Runtime](../entities/agent-loop-runtime.md)
