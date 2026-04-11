# Benchmark-Driven Agent Evaluation

## Overview

AutoGen includes a dedicated evaluation surface because agent quality is not fully visible from framework APIs alone. `agbench` exists to repeatedly run scenarios under controlled conditions, capture artifacts, and support later analysis. That makes evaluation a surrounding architecture concern rather than a method hidden inside the main runtime stack.

## Mechanism

The evaluation mechanism is:

1. Define benchmark scenarios and templates.
2. Expand those templates into concrete run directories.
3. Execute scenarios repeatedly under controlled environments, usually Docker.
4. Persist logs, outputs, messages, and artifacts into a structured results tree.
5. Summarize or compare those results later using tabulation and analysis tools.

This setup gives the AutoGen ecosystem a feedback loop: framework and application designs can be exercised repeatedly, then measured separately from their runtime implementation.

## Involved Entities

- [AutoGen Bench](../entities/agbench.md)
- [Magentic-One](../entities/magentic-one.md)
- [Package and Distribution Surface](../entities/package-and-distribution-surface.md)

## Source Evidence

- `python/packages/agbench/README.md` describes controlled initial conditions, blank-slate runs, Docker isolation, and results logging.
- `python/packages/agbench/src/agbench/run_cmd.py` implements scenario expansion, environment preparation, and Docker/native execution.
- `python/packages/agbench/src/agbench/tabulate_cmd.py` provides the analysis-facing result summarization path.

## See Also

- [AutoGen Bench](../entities/agbench.md)
- [Magentic-One](../entities/magentic-one.md)
- [Benchmark and Agent Runtime Feedback Loop](../syntheses/benchmark-and-agent-runtime-feedback-loop.md)
- [Tool-Augmented Agent Execution](tool-augmented-agent-execution.md)
- [Package Selection and Entrypoint Flow](../syntheses/package-selection-and-entrypoint-flow.md)
