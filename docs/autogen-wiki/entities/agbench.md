# AutoGen Bench

## Overview

`agbench` is the evaluation harness in the AutoGen ecosystem. Its job is not to provide a new agent runtime or a new high-level API. Its job is to repeatedly run benchmark scenarios under controlled initial conditions and preserve the artifacts needed for later analysis. The README is explicit about this: Bench starts from a blank slate for each run, usually inside fresh Docker containers, logs the results, and lets metrics or analysis scripts consume those outputs later.

Architecturally, Bench matters because it gives AutoGen an evaluation surface separate from the framework runtime itself. That separation is healthy: the framework can focus on building agents, while Bench can focus on reproducibility, task templating, and result collection.

## Key Types

| Type / surface | Source | Role |
|----------------|--------|------|
| CLI command multiplexer | `python/packages/agbench/src/agbench/cli.py` | Exposes `run`, `tabulate`, `lint`, and `remove_missing` commands |
| Scenario runner | `python/packages/agbench/src/agbench/run_cmd.py` | Expands scenarios, prepares environments, runs them natively or in Docker |
| Tabulation command | `python/packages/agbench/src/agbench/tabulate_cmd.py` | Summarizes benchmark results |
| Linter | `python/packages/agbench/src/agbench/linter/` | Validates benchmark configuration |

## Architecture

Bench is built around three layers.

The first is the **CLI layer**. `cli.py` is a small dispatcher that routes to the main commands. This keeps the top-level interface simple while pushing heavy behavior into specific command modules.

The second is the **scenario-expansion and execution layer**. `run_cmd.py` is the architectural center. It loads scenario files or directories of scenarios, performs optional subsampling, expands scenario templates into concrete working directories, injects environment variables, and then chooses native or Docker execution. This is the core reason Bench exists: it standardizes how agent tasks are turned into repeatable experimental runs.

The third is the **result analysis layer**. Bench stores results in a structured directory hierarchy keyed by scenario, task id, and repetition. Separate commands then tabulate or clean those results. This keeps execution and analysis loosely coupled.

## Runtime Behavior

The main runtime flow in Bench looks like this:

1. The user invokes `agbench run ...`.
2. The CLI passes control to `run_cmd.py`.
3. Scenario files are discovered and loaded, with optional subsampling.
4. Each scenario instance is expanded into a concrete working folder by copying templates and applying substitutions.
5. Environment variables and auth/config material are prepared.
6. The scenario is executed either natively or, by default, inside Docker.
7. Outputs such as logs, timestamps, messages, and generated artifacts are persisted into a results tree.
8. Later, `agbench tabulate` or other scripts summarize those results.

The critical design choice is Docker-first execution. The README strongly recommends Docker because it provides consistency and safer isolation. Native execution is supported, but it is positioned as the exception rather than the norm.

## Variants, Boundaries, and Failure Modes

Bench sits outside the main runtime stack, so its boundaries are relatively clean:

- it consumes AutoGen-based systems rather than defining the framework substrate
- it owns reproducibility, scenario templating, and results management
- it does not own model-client behavior, agent orchestration semantics, or provider abstractions

Common issues at this layer include Docker/environment setup failures, missing config or key material, broken scenario templates, and incomplete result folders.

## Source Files

| File | Purpose |
|------|---------|
| `python/packages/agbench/README.md` | Positioning, Docker-first workflow, result layout |
| `python/packages/agbench/src/agbench/cli.py` | Top-level command dispatcher |
| `python/packages/agbench/src/agbench/run_cmd.py` | Scenario expansion and execution pipeline |
| `python/packages/agbench/src/agbench/tabulate_cmd.py` | Result summarization |
| `python/packages/agbench/src/agbench/linter/` | Benchmark config linting |
| `python/packages/agbench/benchmarks/` | Built-in benchmark suites and templates |

## See Also

- [Magentic-One](magentic-one.md)
- [Package and Distribution Surface](package-and-distribution-surface.md)
- [Benchmark-Driven Agent Evaluation](../concepts/benchmark-driven-agent-evaluation.md)
- [Benchmark and Agent Runtime Feedback Loop](../syntheses/benchmark-and-agent-runtime-feedback-loop.md)
- [Package Selection and Entrypoint Flow](../syntheses/package-selection-and-entrypoint-flow.md)
