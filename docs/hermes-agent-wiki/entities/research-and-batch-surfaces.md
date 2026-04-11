# Research and Batch Surfaces

## Overview

Hermes is both a user-facing agent product and a research substrate.

Most of the wiki focuses on the product side: a person talks to Hermes through the CLI, gateway, or ACP, Hermes runs its agent loop, and tools execute on the user's behalf. But the same repository also contains a second family of surfaces where there is no human chat shell at the center. Instead, Hermes is run over datasets, benchmarks, or reinforcement-learning tasks so researchers can generate trajectories, score behaviors, and train or evaluate models.

That second family matters because it reuses a large part of Hermes rather than rebuilding it from scratch.

The mental model is:

- product surfaces run Hermes for a human session
- research and batch surfaces run Hermes for a dataset item or rollout

The reused parts are the agent/tool abstractions: tool schemas, tool dispatch, terminal backends, browser/file/web tools, and conversation trajectories. The divergent parts are orchestration, scoring, checkpointing, parser-backed tool extraction, and training/evaluation infrastructure.

This page covers those non-interactive surfaces:

- `batch_runner.py` for dataset-driven parallel agent execution
- the `environments/` stack for Atropos-backed evaluation, data generation, and RL rollouts
- RL orchestration surfaces such as `rl_cli.py` and `tools/rl_training_tool.py`

## Key Interfaces / Key Concepts

| Anchor | Why it matters |
| --- | --- |
| `BatchRunner` in `hermes-agent/batch_runner.py` | Main dataset-driven batch surface: parallel processing, resume logic, per-batch outputs, and aggregate statistics. |
| `_process_single_prompt()` in `hermes-agent/batch_runner.py` | Clearest example of "ordinary `AIAgent` run, but in a dataset worker rather than a live shell." |
| `agent._convert_to_trajectory_format(...)` and helpers in `hermes-agent/agent/trajectory.py` | Show how Hermes trajectories are normalized into training/eval-friendly JSONL artifacts. |
| `trajectory_compressor.py` | Post-processing layer for shrinking saved trajectories while preserving training signal. |
| `HermesAgentBaseEnv` in `hermes-agent/environments/hermes_base_env.py` | Main bridge from Hermes tools/runtime behavior into Atropos environments. |
| `HermesAgentLoop` in `hermes-agent/environments/agent_loop.py` | Reusable multi-turn tool-calling loop for evaluation and RL rollouts. |
| `ToolContext` in `hermes-agent/environments/tool_context.py` | Gives verifiers and reward functions access to the same task-scoped tool/session state the model used. |
| `environments/tool_call_parsers/*` | Client-side parser family used when the research stack must recover tool calls from raw model text. |
| `rl_cli.py` and `tools/rl_training_tool.py` | User-facing orchestration layer for Tinker-Atropos training workflows, distinct from the lower-level environment framework. |

## Architecture

The easiest way to understand this subsystem is to separate reuse from divergence.

### What research surfaces reuse

These surfaces still depend on core Hermes machinery:

- tool definitions from `model_tools.py`
- tool dispatch via `handle_function_call()`
- terminal/browser/file/web tools
- task-scoped execution environments
- the same idea of multi-turn tool-calling conversations
- trajectory normalization into stable artifacts

In other words, Hermes is still the tool-using agent runtime.

### What research surfaces add

The research stack adds orchestration that the product runtime does not need:

- dataset loading and batch partitioning
- multiprocessing and resumable checkpoints
- reward computation and benchmark scoring
- rollout groups and training/eval loops under Atropos
- tool-call parsing for raw-text generations in some training modes
- run tracking, metrics, and training-process management

That means this is not "another shell." It is a layer around Hermes for experimentation.

### Boundary table

| Layer | Owns | Stops before |
| --- | --- | --- |
| Product runtime (`run_agent.py`, CLI, gateway, ACP) | Interactive sessions, user-facing UX, ordinary tool-calling turns | Batch scheduling, benchmark scoring, RL rollout orchestration |
| Batch surface (`batch_runner.py`) | Dataset iteration, multiprocessing, checkpoint/resume, output artifacts, aggregate stats | Defining new reward environments or training infrastructure |
| Environment framework (`environments/`) | Embedding Hermes behavior into Atropos environments, rollout collection, verifier access, parser-backed tool extraction | User chat UX and general CLI/gateway lifecycle |
| RL orchestration (`rl_cli.py`, `rl_training_tool.py`) | Discovering environments, editing training config, launching and monitoring training runs | Replacing the underlying environment framework or Hermes tools themselves |

This boundary is deliberate. The research stack wants Hermes' tool-using behavior, but not the product shell around it.

## Runtime Behavior

### 1. Batch runner is the simplest research surface: many normal Hermes runs over a dataset

`batch_runner.py` is the clearest entry point for understanding reuse.

At its core, `_process_single_prompt()` does something very familiar:

1. pick one dataset row
2. create an `AIAgent`
3. run `agent.run_conversation(...)`
4. collect messages and normalize them into a trajectory

What changes is the surrounding orchestration.

Each prompt is treated as a task with its own `task_id`, optional per-row container image, optional cwd override, sampled toolset distribution, and isolated execution context. The batch surface is not trying to give a human a live shell. It is trying to produce a large number of comparable agent runs with consistent outputs.

That is why the batch runner also disables a few product-oriented behaviors by default, such as persistent memory and context-file loading, so runs do not get polluted by local profile state or repo-specific instruction files.

### 2. Batch orchestration adds parallelism, checkpoints, and artifact discipline

The real batch-specific logic lives around that per-prompt run.

`BatchRunner` loads a JSONL dataset, partitions it into batches, and uses a multiprocessing `Pool` to process multiple batches in parallel. Each batch writes its own `batch_<n>.jsonl` file, and the runner maintains a checkpoint file plus aggregate statistics.

The important behavior is resumability. Resume does not just trust prompt indices. The runner can scan existing batch files, match completed prompts by content, and skip already-finished work even if the dataset order changed. That makes it a research surface rather than a quick scripting helper. It assumes long runs, crashes, and retries are normal.

It also treats artifact quality as part of the runtime:

- trajectories are saved in normalized JSONL form
- tool stats are normalized across all possible tools for schema stability
- reasoning coverage is measured
- zero-reasoning samples can be discarded
- corrupted entries with invalid tool names are filtered during final merge

So the batch runner is not only "parallel agent execution." It is a batch artifact pipeline for training and evaluation data.

### 3. Trajectories are first-class research outputs, not just debug logs

This subsystem relies heavily on Hermes trajectories.

`agent/trajectory.py` and the conversion path used by the batch runner normalize conversations into ShareGPT-style records with stable role mappings, normalized reasoning markup, and XML-style tool call and tool response formatting. The developer guide on trajectory format makes clear that these artifacts are intended for training data, debugging, and RL datasets, not just casual logging.

That is one place where the research stack and product runtime overlap cleanly:

- product runtime may save trajectories as artifacts of an interactive session
- research stack depends on trajectories as primary outputs

`trajectory_compressor.py` extends that pipeline further. It is not part of live agent execution, but it matters to the research story because it compresses long completed trajectories into a target token budget while trying to preserve useful training signal. That is an experimentation need, not a product-shell need.

### 4. The environment stack embeds Hermes into Atropos instead of calling `AIAgent` directly

The `environments/` tree is the deeper research integration.

Here the goal is no longer "run a lot of agent sessions." The goal is "define an environment that Atropos can roll out, score, and train against." `HermesAgentBaseEnv` is the main bridge. It extends Atropos `BaseEnv` with Hermes-specific concerns:

- terminal backend selection through `TERMINAL_ENV`
- tool resolution through Hermes tool definitions
- a reusable multi-turn agent loop
- task-scoped verifier access through `ToolContext`
- handling for different rollout phases and server types

This is where reuse and divergence are easiest to see side by side.

Reuse:

- environments still call Hermes tools
- environments still use Hermes tool schemas
- rollout tasks still execute in Hermes terminal/browser/file contexts

Divergence:

- Atropos owns worker scheduling, eval/training CLI modes, and server management
- the environment author defines dataset loading, prompt formatting, and reward computation
- results are packaged into Atropos scoring objects rather than user-visible chat history

### 5. `HermesAgentLoop` recreates the tool-calling pattern for rollout collection

`HermesAgentLoop` is intentionally similar to the main product loop, but it is not the same object as `AIAgent`.

Its runtime pattern is:

1. send `messages` plus `tools` to the active server
2. inspect the returned tool calls
3. dispatch tool calls through Hermes tool handling
4. append tool results
5. continue until the model stops or the max-turn budget is reached

That similarity is the point. The research stack wants rollout behavior that still looks like Hermes tool use.

But the loop also diverges in ways the product runtime does not:

- it packages results as `AgentResult`
- it is designed for Atropos server abstractions
- it uses a thread pool specifically to keep tool execution compatible with Atropos event loops
- it can fall back to parser-backed tool extraction when the serving layer does not return structured tool calls

So `HermesAgentLoop` is best understood as a research-facing replay of Hermes' tool-calling semantics, not as a second user runtime.

### 6. `ToolContext` is the key verifier abstraction

`ToolContext` is one of the most important pieces in this page because it explains how evaluation stays grounded in actual agent effects.

After a rollout finishes, reward functions do not have to guess from final text alone. `ToolContext(task_id)` lets the verifier call Hermes tools against the same task-scoped state the model used:

- run tests in the same terminal sandbox
- inspect or modify files in the same filesystem
- download artifacts
- query browser or web state
- call any Hermes tool directly if needed

That is what makes these environments more than transcript scorers. The verifier has access to the concrete world state produced by the rollout.

This is a direct reuse of Hermes' environment abstractions. The task ID ties the reward function to the same sandbox and sessions that served the agent during the rollout.

### 7. Parser-backed tool extraction exists because research serving modes are not always product serving modes

In product usage, the ideal case is that the model provider or server already returns structured tool calls.

The research stack cannot always assume that. In the `environments/` framework, especially Phase 2 / ManagedServer flows, the serving layer may return raw text without parsed tool calls. That is why `environments/tool_call_parsers/` exists.

Those parsers are a compatibility layer:

- they take raw model output
- recover structured `tool_calls`
- let the rollout continue through the same Hermes tool dispatch path

This is a research-specific divergence from the product runtime. The point is not that Hermes changed how tools work. The point is that experimental serving backends sometimes require the research stack to reconstruct the tool-call structure itself.

### 8. RL orchestration is a surface above the environment framework, not a replacement for it

`rl_cli.py` and `tools/rl_training_tool.py` form another layer again.

These files are not the environment framework itself. They are an orchestration surface for Tinker-Atropos RL workflows:

- discover available environments
- inspect and edit environment/training config
- launch runs
- check status
- stop runs
- retrieve results

`rl_training_tool.py` does environment discovery with AST scanning, maintains run state, protects locked infrastructure fields, and manages subprocess lifecycles for the API server, trainer, and environment processes. `rl_cli.py` then wraps that machinery in an RL-focused Hermes agent session with extended timeouts and the `rl` toolset enabled.

That means the RL stack has its own internal layering:

- environments define tasks and rewards
- HermesAgentBaseEnv and HermesAgentLoop run rollouts with Hermes tools
- RL tools and CLI orchestrate training infrastructure around those environments

This is still part of the research surface, but it is more operational than the batch runner and more orchestration-heavy than the base environments.

## Source Files

| File | Why it is an anchor |
| --- | --- |
| `hermes-agent/batch_runner.py` | Main batch-processing entry point: dataset loading, multiprocessing, checkpoint/resume, trajectory capture, filtering, and statistics. |
| `hermes-agent/agent/trajectory.py` | Shared trajectory-saving and normalization helpers used by research artifacts and product-side saves. |
| `hermes-agent/trajectory_compressor.py` | Post-processing pipeline for shrinking trajectories into training-friendly token budgets. |
| `hermes-agent/environments/README.md` | Best compact explanation of the Atropos integration layer and its major components. |
| `hermes-agent/environments/hermes_base_env.py` | Core bridge from Hermes tool/runtime behavior into Atropos environments. |
| `hermes-agent/environments/agent_loop.py` | Reusable research-facing multi-turn loop that preserves Hermes tool-calling semantics. |
| `hermes-agent/environments/tool_context.py` | Verifier interface for calling Hermes tools against the same rollout state. |
| `hermes-agent/environments/tool_call_parsers/*` | Parser family for recovering structured tool calls from raw output in Phase 2-style flows. |
| `hermes-agent/rl_cli.py` | RL-focused CLI runner that wraps the training/orchestration toolset for long-running workflows. |
| `hermes-agent/tools/rl_training_tool.py` | Environment discovery, locked config handling, run-state management, and training process orchestration. |
| `hermes-agent/website/docs/developer-guide/environments.md` | Maintainer-oriented guide to environments, benchmarks, and data generation. |
| `hermes-agent/website/docs/developer-guide/trajectory-format.md` | Detailed reference for saved trajectory structure and normalization rules. |
| `hermes-agent/website/docs/user-guide/features/batch-processing.md` | User-facing batch-runner guide, especially useful for checkpointing and output artifact behavior. |
| `hermes-agent/website/docs/user-guide/features/rl-training.md` | User-facing guide to the RL orchestration surface and its workflow. |

## See Also

- [Agent Loop Runtime](agent-loop-runtime.md)
- [Terminal and Execution Environments](terminal-and-execution-environments.md)
- [Tool Registry and Dispatch](tool-registry-and-dispatch.md)
- [Environment Abstraction for Agent Execution](../concepts/environment-abstraction-for-agent-execution.md)
- [CLI to Agent Loop Composition](../syntheses/cli-to-agent-loop-composition.md)
