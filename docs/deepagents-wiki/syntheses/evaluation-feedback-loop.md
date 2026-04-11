# Evaluation Feedback Loop

## Overview

The `deepagents-evals` package (`libs/evals/`) is the behavioral validation layer for the SDK and CLI. It runs agents end-to-end against a real LLM, asserts on the resulting trajectory (tool calls, final text, file mutations), and reports correctness and efficiency metrics to LangSmith. Two evaluation harnesses are provided: a pytest-based unit/behavioral suite and a Harbor integration for Terminal Bench 2.0. Together they form a feedback loop: run evals → observe failure patterns → improve prompts, tools, or middleware → re-run evals.

## Systems Involved

- [Evals System](../entities/evals-system.md) — `deepagents_evals`, `deepagents_harbor`, pytest suite
- [Graph Factory](../entities/graph-factory.md) — agents under test are created with `create_deep_agent()`
- [Batteries Included Agent Architecture](../concepts/batteries-included-agent-architecture.md) — planning, filesystem, and subagent tools are the primary subjects of evaluation
- [Context Management and Summarization](../concepts/context-management-and-summarization.md) — summarization middleware is exercised in `test_summarization.py`
- [SDK to CLI Composition](sdk-to-cli-composition.md)

## Interaction Model

### Part A — pytest Behavioral Suite

#### Test Structure

Tests live in `libs/evals/tests/evals/`. Each test file is tagged with an `eval_category` marker:

| Category | Test File | What It Measures |
|---|---|---|
| `file_operations` | `test_file_operations.py` | read/write/edit/ls/grep/glob tool usage, parallel file ops |
| `tool_use` | `test_tool_selection.py`, `test_tool_usage_relational.py`, `test_todos.py` | tool selection from intent, multi-step tool chaining, todo list planning |
| `retrieval` | `test_file_operations.py`, `test_external_benchmarks.py` | FRAMES multi-hop retrieval, BFCL v3 stateful tool calling |
| `memory` | `test_memory.py`, `test_memory_multiturn.py`, `memory_agent_bench/` | AGENTS.md recall, preference persistence, MemoryAgentBench (ICLR 2026) |
| `conversation` | `test_followup_quality.py`, `tau2_airline/` | followup question relevance (LLM judge), tau2-bench airline tasks |
| `summarization` | `test_summarization.py` | summarization middleware triggers, post-compaction task continuation |
| `unit_test` | `test_hitl.py`, `test_subagents.py`, `test_system_prompt.py`, `test_skills.py` | HITL approval flow, subagent delegation, prompt adherence, skill loading |

Categories are the single source of truth in `deepagents_evals/categories.json`. A drift test (`tests/unit_tests/test_eval_catalog.py`) fails CI if `EVAL_CATALOG.md` is stale.

#### Two-Tier Assertion Model (`TrajectoryScorer`)

Each test uses `TrajectoryScorer` with two tiers:

```python
scorer = (
    TrajectoryScorer()
    .expect(agent_steps=2, tool_call_requests=1)   # soft: logged, never fails
    .success(
        final_text_contains("three", case_insensitive=True),  # hard: fails test
    )
)
```

- **`.success(...)`** — hard assertions on correctness: `final_text_contains`, `file_equals`, `llm_judge`
- **`.expect(...)`** — soft efficiency targets: expected step count, expected tool calls; logged but never fail

For semantic grading, `llm_judge` (in `tests/evals/llm_judge.py`) wraps the `openevals` library to grade agent answers against human-readable criteria.

#### Running Tests

```bash
# All evals (default model)
make evals

# Specific model
LANGSMITH_TEST_SUITE=deepagents-evals uv run --group test pytest tests/evals \
  --model claude-sonnet-4-6-20250514

# Single category
uv run --group test pytest tests/evals --eval-category memory

# Single file
uv run --group test pytest tests/evals/test_file_operations.py
```

Required environment variables: `ANTHROPIC_API_KEY`, `LANGSMITH_API_KEY`, `LANGSMITH_TRACING=true`.

#### Metrics and Reporting

The custom pytest plugin (`pytest_reporter.py`) collects efficiency data and prints a summary after each run:

```
========== deepagents evals summary ==========
correctness: 0.85         # fraction passing all success assertions
step_ratio: 1.10          # actual steps / expected steps (micro-averaged)
tool_call_ratio: 1.05     # actual tool calls / expected tool calls
solve_rate: 0.0342        # mean of expected_steps / duration_s for passing tests
median_duration_s: 3.1200
```

Results are logged to LangSmith under the `deepagents-evals` test suite. Set `DEEPAGENTS_EVALS_REPORT_FILE` or pass `--evals-report-file <path>` to also write a JSON summary.

Full runs (3+ categories) generate a radar chart comparing model scores across categories, using `deepagents_evals/radar.py`. The chart is skipped for narrow category-filtered runs.

#### Writing a New Eval

```python
@pytest.mark.langsmith
@pytest.mark.eval_category("tool_use")
def test_example(model: BaseChatModel) -> None:
    agent = create_deep_agent(model=model)
    run_agent(
        agent,
        model=model,
        query="What is 2 + 2?",
        scorer=(
            TrajectoryScorer()
            .expect(agent_steps=1)
            .success(final_text_contains("4"))
        ),
    )
```

The `model` fixture comes from `conftest.py` which resolves `--model` CLI option to a `BaseChatModel` instance. `run_agent` (in `tests/evals/utils.py`) invokes the agent and returns an `AgentTrajectory` passed to the scorer.

### Part B — Harbor Integration (Terminal Bench 2.0)

#### What Harbor Provides

[Harbor](https://harborframes.com/) orchestrates sandbox environments (Docker, Daytona, Modal, Runloop) and runs agents against challenging tasks from Terminal Bench 2.0 (90+ tasks across software engineering, biology, security, gaming).

The deep agent is exposed to Harbor via `DeepAgentsWrapper` in `deepagents_harbor/deepagents_wrapper.py`.

#### Running Harbor Benchmarks

```bash
# Docker (sequential)
uv run harbor run --agent-import-path deepagents_harbor:DeepAgentsWrapper \
  --dataset terminal-bench@2.0 -n 1 --jobs-dir jobs/terminal-bench --env docker

# Daytona (40 concurrent trials)
uv run harbor run --agent-import-path deepagents_harbor:DeepAgentsWrapper \
  --dataset terminal-bench@2.0 -n 40 --jobs-dir jobs/terminal-bench --env daytona
```

Makefile shortcuts: `make run-terminal-bench-docker`, `make run-terminal-bench-daytona`, `make run-terminal-bench-modal`, `make run-terminal-bench-runloop`.

#### LangSmith Integration for Harbor

The feedback loop from Harbor runs:

```
Deep Agents → Harbor (evaluate) → LangSmith (analyze) → Improve → Repeat
```

1. Create LangSmith dataset from Harbor tasks: `python scripts/harbor_langsmith.py create-dataset terminal-bench --version 2.0`
2. Run benchmark with `LANGSMITH_EXPERIMENT=<name>` set
3. Push reward scores (0.0–1.0) back to LangSmith: `python scripts/harbor_langsmith.py add-feedback <jobs-dir> --project-name <name>`

Reward scores are then available in LangSmith for filtering runs by performance and identifying patterns.

#### Common Failure Patterns (from `libs/evals/README.md`)

| Pattern | Symptom | Improvement Direction |
|---|---|---|
| Poor Planning | Agent jumps into coding without reading requirements | Strengthen upfront planning requirement in prompt |
| Incorrect Tool Usage | Uses `bash cat` instead of `read_file` | Improve tool descriptions with examples |
| No Incremental Testing | Writes 200 lines, then tests once | Prompt to test after each logical unit |
| Hallucinated Paths | Reads files before checking existence | Add "always `ls` before read" rule |
| Wrong Model | Model fails on complex reasoning | Use more capable model for hard tasks |

## Key Interfaces

| Interface | Location | Purpose |
|---|---|---|
| `TrajectoryScorer` | `tests/evals/utils.py` | Assembles success + efficiency assertions |
| `run_agent()` | `tests/evals/utils.py` | Entry point for running an agent and collecting `AgentTrajectory` |
| `AgentTrajectory` | `tests/evals/utils.py` | Captures tool calls, final text, file mutations |
| `llm_judge()` | `tests/evals/llm_judge.py` | LLM-as-judge `SuccessAssertion` using `openevals` |
| `DeepAgentsWrapper` | `deepagents_harbor/deepagents_wrapper.py` | Harbor-compatible wrapper around `create_deep_agent()` |
| `categories.json` | `deepagents_evals/categories.json` | Source of truth for category names, labels, radar inclusion |
| `radar.py` | `deepagents_evals/radar.py` | Generates radar charts from category scores |

## See Also

- [Evals System](../entities/evals-system.md)
- [Batteries Included Agent Architecture](../concepts/batteries-included-agent-architecture.md)
- [Graph Factory](../entities/graph-factory.md)
- [Context Management and Summarization](../concepts/context-management-and-summarization.md)
- [SDK to CLI Composition](sdk-to-cli-composition.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
