# Terminal and Execution Environments

## Overview

When Hermes exposes the `terminal` tool to the model, it is not promising "I will run a local subprocess." It is promising something narrower and more useful: "I can run this command in the execution environment configured for this task, and I will return the result in a consistent shape."

That is the main idea of this page. Hermes has one model-facing terminal capability, but it can fulfill that capability through different backends. A command might run on the local machine, inside Docker, on a remote SSH host, in a Singularity instance, or in a cloud sandbox such as Modal or Daytona. The model does not have to learn a new tool for each of those cases because Hermes hides that variation behind one execution contract.

The simplest runtime story is:

1. Hermes decides that the `terminal` tool is available.
2. The model calls `terminal`.
3. `tools/terminal_tool.py` chooses or reuses one backend.
4. Hermes runs command-policy checks.
5. If the command is allowed, the backend executes it and returns normalized output.

That makes this page an execution-backend page, not a backend catalog. The point is to understand where backend choice happens, what guarantees Hermes does and does not make, and where command policy stops and actual execution begins.

## Architecture

Hermes splits terminal execution into three layers on purpose.

| Layer | Owns | Stops before |
| --- | --- | --- |
| Tool runtime | Making `terminal` visible to the model and dispatching into `terminal_tool()` | Backend choice and process transport |
| Terminal runtime | Reading config, creating or reusing backend instances, foreground/background orchestration, normalizing results | The transport details of one backend |
| Backend implementation | Actually running the command in one concrete place and cleaning up any resources | Tool visibility and approval UX |

That split prevents two common kinds of confusion.

First, it prevents "tool exists" from being mixed up with "tool runs locally." A tool can be visible even when execution happens in a container, a remote host, or a cloud sandbox.

Second, it prevents approval policy from being mixed up with process transport. Hermes wants one command-policy layer for dangerous-command detection, but it also wants multiple execution backends. Those are related at runtime, but they are different responsibilities.

In practice, the terminal runtime is centered in `hermes-agent/tools/terminal_tool.py`, while the backend implementations live under `hermes-agent/tools/environments/`.

## Key Interfaces and Guarantees

The core contract is small. Each backend is expected to look like a `BaseEnvironment`:

```python
class BaseEnvironment(ABC):
    def execute(self, command: str, cwd: str = "", *,
                timeout: int | None = None,
                stdin_data: str | None = None) -> dict: ...
    def cleanup(self): ...
```

Around that contract, a few interfaces matter more than the rest:

| Anchor | Why it matters |
| --- | --- |
| `BaseEnvironment` in `hermes-agent/tools/environments/base.py` | Defines the shared execution and cleanup contract plus common helpers such as timeout results and sudo preparation. |
| `_get_env_config()` in `hermes-agent/tools/terminal_tool.py` | Resolves `TERMINAL_ENV` and the backend-specific settings that decide where commands run. |
| `_create_environment()` in `hermes-agent/tools/terminal_tool.py` | Turns the chosen backend name into one concrete environment object. |
| `terminal_tool()` in `hermes-agent/tools/terminal_tool.py` | Owns the handoff from tool dispatch into backend execution, including environment caching, guard checks, and result shaping. |
| `PersistentShellMixin` in `hermes-agent/tools/environments/persistent_shell.py` | Adds long-lived shell state for backends that want session continuity across multiple commands. |
| `BaseModalExecutionEnvironment` in `hermes-agent/tools/environments/modal_common.py` | Shows how Hermes shares one execute-flow even when Modal has more than one transport path. |

The other important interface is not a Python class but a runtime guarantee distinction. Hermes uses several kinds of continuity, and they are easy to conflate if the page does not name them directly.

| Guarantee | What it means | What it does not mean |
| --- | --- | --- |
| Same cached environment | Hermes reuses the same backend object for the same `task_id` instead of creating a fresh backend for every command. | It does not by itself guarantee that a long-lived shell process still exists. |
| Persistent filesystem | Files written in the sandbox or container can survive backend recreation or restart, depending on the backend. | It does not guarantee that background jobs or the same live process are still running. |
| Persistent live shell | The backend keeps one shell process alive across commands, so cwd, shell variables, and similar shell state can carry forward. | It does not mean the environment is immortal; cleanup, interrupt handling, or backend failure can still end it. |

This distinction is the clearest way to read the rest of the subsystem. Hermes is careful to reuse environments, but different backends preserve different kinds of state.

## Runtime Behavior

### 1. The model reaches `terminal_tool()`

The flow starts after the normal tool-dispatch path has already made the `terminal` capability available. `model_tools.handle_function_call(...)` routes the call into `terminal_tool()`. By that point, the question is no longer "should the model see this tool?" The question is "where should this command execute?"

That ownership boundary matters because this page begins after tool governance. If the model cannot see `terminal`, the problem is upstream in [Tool Registry and Dispatch](tool-registry-and-dispatch.md). If the model can see `terminal` but command execution behaves unexpectedly, this page is the right place to look.

### 2. Hermes resolves the backend

`terminal_tool.py` reads backend settings through `_get_env_config()`. The main selector is `TERMINAL_ENV`, but the config bundle also resolves:

- cwd defaults and path sanity rules
- container CPU, memory, disk, and persistence settings
- SSH host, user, port, and key settings
- whether a local or SSH backend should keep a persistent shell
- whether Modal should use direct or managed transport

`_create_environment()` then turns that config into one concrete backend instance.

The supported variants are all implementations of the same idea:

- `LocalEnvironment` runs on the host machine
- `DockerEnvironment` runs in a hardened container
- `SSHEnvironment` runs on a remote host
- `SingularityEnvironment` runs in an Apptainer or Singularity instance
- `ModalEnvironment` runs through the native Modal SDK
- `ManagedModalEnvironment` still targets Modal, but through a managed tool-gateway transport
- `DaytonaEnvironment` runs in a Daytona cloud sandbox

Hermes caches the environment by `task_id`. That means repeated tool calls in the same task usually talk to the same backend instance instead of rebuilding the execution context from scratch. This is where "same cached environment" comes from.

### 3. Approval and policy happen before execution

Once Hermes has a backend, it still has not run the command. Before calling `env.execute(...)`, `terminal_tool()` runs `_check_all_guards(...)`, which delegates into `tools/approval.py`.

This is the command-policy boundary. That layer can:

- match dangerous patterns such as destructive deletes or writes to sensitive paths
- consult per-session approval state
- request a blocking approval in gateway-style sessions
- return "blocked" or "approval required" without executing anything

This is also the place where the page needs to stay strict about ownership:

- `tools/approval.py` decides whether the command may proceed
- the calling surface decides how to present or collect approval from a human
- the backend executes only after the command is approved

So approval and execution are adjacent, but they are not the same subsystem.

### 4. Foreground and background paths both depend on the backend abstraction

If the command is approved, `terminal_tool()` chooses one of two orchestration paths.

For foreground execution, Hermes calls `env.execute(...)`, applies retry logic for transient failures, strips ANSI escapes, redacts sensitive output, and returns a normalized JSON payload with fields such as `output` and `exit_code`.

For background execution, Hermes uses `tools.process_registry`. The important detail is that this still depends on the same backend abstraction:

- local execution can spawn a host-side process directly
- non-local execution uses `spawn_via_env(...)`, which runs against the selected environment

So Hermes does not have one system for "terminal backends" and another for "background terminal work." It has one backend abstraction with two orchestration modes on top of it.

### 5. Backends vary mainly in transport and persistence behavior

The backends differ, but not in arbitrary ways. Most of the variation falls into two questions: where is the command running, and what kind of state survives across commands?

`LocalEnvironment` and `SSHEnvironment` can use `PersistentShellMixin`, which gives Hermes a real long-lived shell. In those modes, shell state such as cwd and shell variables can persist because the shell process itself persists.

The container and cloud backends are different. Docker and Singularity emphasize isolated execution plus optional filesystem persistence. Modal and Daytona also emphasize sandbox continuity, but their continuity model is closer to "restore or resume the task sandbox" than "keep one shell process alive forever." `BaseModalExecutionEnvironment` exists because Hermes wants the same high-level execute flow even when the transport underneath is direct Modal or managed Modal.

The practical consequence is simple:

- if a user cares that files survive, filesystem persistence is the important question
- if a user cares that shell session state survives, persistent-shell support is the important question
- if a user cares that Hermes does not recreate the whole backend between calls, task-scoped environment caching is the important question

Those guarantees overlap, but they are not interchangeable.

### 6. The abstraction is shared beyond the interactive terminal

The backend layer is not only for the local chat experience. Hermes also reuses it in other runtime consumers. The Atropos-facing `hermes-agent/environments/` layer, for example, uses the same family of execution environments for training, evaluation, and benchmark workflows. Files such as `hermes-agent/environments/README.md` and `mini_swe_runner.py` show the same backend contract being reused outside the normal chat loop.

That is why Hermes invested in the abstraction instead of baking execution directly into one shell. The backends are shared infrastructure for multiple runtime contexts, even though the simplest way to learn them is still through the `terminal` tool.

## Source Files

The best source anchors for this page are the ones that show the handoff from tool runtime into backend execution, then the concrete backend variations:

| File | Why it matters |
| --- | --- |
| `hermes-agent/tools/terminal_tool.py` | Main ownership anchor for backend selection, environment caching, guard checks, foreground/background branching, and result normalization. |
| `hermes-agent/tools/environments/base.py` | Defines the common backend contract and shared helpers. |
| `hermes-agent/tools/environments/persistent_shell.py` | Explains what Hermes means by a persistent live shell. |
| `hermes-agent/tools/environments/local.py`, `docker.py`, `ssh.py`, `singularity.py`, `modal.py`, `managed_modal.py`, `daytona.py` | Show how one contract is realized through local, container, remote, and cloud transports. |
| `hermes-agent/tools/approval.py` | Defines the policy boundary that runs before backend execution begins. |
| `hermes-agent/website/docs/developer-guide/tools-runtime.md` | Maintainer-facing summary of the same tool-runtime and backend model. |

Read together, these files reinforce the page's main mental model: `terminal_tool.py` owns the runtime handoff, and `tools/environments/*` owns where the command actually runs.

## See Also

- [Tool Registry and Dispatch](tool-registry-and-dispatch.md)
- [CLI Runtime](cli-runtime.md)
- [Research and Batch Surfaces](research-and-batch-surfaces.md)
- [Environment Abstraction for Agent Execution](../concepts/environment-abstraction-for-agent-execution.md)
- [Tool Call Execution and Approval Pipeline](../syntheses/tool-call-execution-and-approval-pipeline.md)
