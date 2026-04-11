# Evals System

## Overview

The evals system (`libs/evals/`) is a behavioral end-to-end test harness for the Deep Agents SDK. Rather than mocking the model or graph, each eval runs a real agent against a real LLM and asserts on the resulting trajectory — tool calls made, files mutated, and final text produced. Results are logged to LangSmith under the `deepagents-evals` test suite, which powers cross-model comparisons and regression tracking. The package also integrates with [Harbor](https://harborframes.com/) as a runner for the Terminal Bench 2.0 benchmark, exposing deepagents as a `DeepAgentsWrapper` that Harbor can evaluate in Docker, Daytona, Modal, or Runloop sandboxes.

## Key Types / Key Concepts

```python
class TrajectoryScorer:
    """Fluent builder for trajectory assertions."""
    def expect(self, agent_steps: int | None = None,
               tool_call_requests: int | None = None) -> TrajectoryScorer:
        """Soft efficiency checks — logged but never fail the test."""

    def success(self, *assertions: SuccessAssertion) -> TrajectoryScorer:
        """Hard correctness checks — any failure hard-fails the test."""

class AgentTrajectory:
    """Captured run: messages, tool calls, final text, timing, file state."""

# Built-in success assertions
final_text_contains(substring: str, *, case_insensitive: bool = False) -> SuccessAssertion
file_equals(path: str, expected: str) -> SuccessAssertion
llm_judge(*criteria: str) -> SuccessAssertion   # openevals-backed semantic grading

def run_agent(
    agent: CompiledStateGraph,
    *,
    model: BaseChatModel,
    query: str,
    scorer: TrajectoryScorer,
) -> AgentTrajectory: ...
```

**Eval categories** (defined in `deepagents_evals/categories.json`):
| Category | Description |
|----------|-------------|
| `file_operations` | Read, write, edit, ls, parallel ops, pagination |
| `retrieval` | Grep, glob, deep-nesting search, multi-file parallel reads, FRAMES benchmark |
| `tool_use` | Tool selection, multi-step chaining, Nexus, BFCL v3 |
| `memory` | AGENTS.md recall, preference persistence, MemoryAgentBench (ICLR 2026) |
| `conversation` | Followup question relevance, tau2-bench airline domain |
| `summarization` | Summarization middleware triggers, filesystem offload, `/compact` tool |
| `unit_test` | HITL interrupts, subagent delegation, system-prompt adherence, skill loading |

**Total: 85 evals across 7 categories.**

## Architecture

**Two-tier assertion model**: Every eval uses a `TrajectoryScorer` with two tiers. `.success()` assertions are correctness checks that hard-fail the pytest test if they do not pass (e.g. `final_text_contains`, `file_equals`, `llm_judge`). `.expect()` assertions are efficiency targets — expected step count, expected tool call count — that are always logged to LangSmith but never fail the test. This separation lets the suite track efficiency regressions without blocking CI on soft metrics.

```python
@pytest.mark.langsmith
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

**LLM-as-judge**: When substring matching is insufficient, `llm_judge(*criteria)` wraps [openevals](https://github.com/langchain-ai/openevals) to grade the agent's final answer against free-text human-readable criteria. The judge model runs separately from the agent under test.

**pytest infrastructure**: `conftest.py` provides a `--model` CLI flag and `model`/`model_name` fixtures. It aborts the entire suite if `LANGSMITH_TRACING=true` without a `LANGSMITH_API_KEY`. A custom `pytest_reporter.py` plugin collects efficiency data and prints a summary after each run:

```
correctness: 0.85       # fraction of tests passing all success assertions
step_ratio: 1.10        # actual steps / expected steps (micro-averaged)
tool_call_ratio: 1.05   # actual tool calls / expected
solve_rate: 0.0342      # mean of expected_steps / duration_s for passing tests
median_duration_s: 3.12
```

**Running evals**:
```bash
cd libs/evals
export ANTHROPIC_API_KEY="sk-ant-..."
export LANGSMITH_API_KEY="lsv2_..."
export LANGSMITH_TRACING=true

make evals                                      # all evals, default model
pytest tests/evals --model claude-sonnet-4-6-20250514  # specific model
pytest tests/evals --eval-category memory       # single category
pytest tests/evals/test_file_operations.py      # single file
```

**External benchmarks**: `test_external_benchmarks.py` runs three curated benchmarks against real data:
- **FRAMES** — multi-hop retrieval over Wikipedia-style documents
- **Nexus** — nested function composition
- **BFCL v3** — multi-turn stateful tool calling with Python API implementations in `tests/evals/data/bfcl_apis/`

**Harbor / Terminal Bench 2.0**: The `deepagents_harbor` package exposes `DeepAgentsWrapper`, a Harbor-compatible agent class that runs deepagents inside any Harbor-supported environment. Terminal Bench 2.0 has 90+ tasks spanning software engineering, biology, security, and gaming. Harbor rewards score 0.0–1.0 based on test pass rate and can be pushed to LangSmith as `harbor_reward` feedback.

```bash
# Run via Docker (sequential)
uv run harbor run --agent-import-path deepagents_harbor:DeepAgentsWrapper \
  --dataset terminal-bench@2.0 -n 1 --env docker

# Run via Daytona (40 concurrent)
make run-terminal-bench-daytona
```

**Radar charts**: Full runs (3+ categories) generate a per-category radar chart uploaded as the `radar-chart` CI artifact:
```bash
python scripts/generate_radar.py --summary evals_summary.json -o charts/radar.png
```

**Catalog drift check**: `EVAL_CATALOG.md` is auto-generated by `scripts/generate_eval_catalog.py`. A unit test (`tests/unit_tests/test_eval_catalog.py`) fails CI if the file is stale after adding or removing evals.

## Source Files

| File | Purpose |
|------|---------|
| `libs/evals/tests/evals/utils.py` | Core framework: `AgentTrajectory`, assertion classes, `TrajectoryScorer`, `run_agent` |
| `libs/evals/tests/evals/llm_judge.py` | `llm_judge` success assertion backed by openevals |
| `libs/evals/tests/evals/conftest.py` | pytest fixtures: `--model` flag, `model`/`model_name`, LangSmith metadata |
| `libs/evals/tests/evals/pytest_reporter.py` | Custom pytest plugin: efficiency data collection and summary report |
| `libs/evals/tests/evals/test_file_operations.py` | 13 file-ops evals: read/write/edit/ls, parallel, grep, glob, pagination |
| `libs/evals/tests/evals/test_tool_selection.py` | Tool selection from intent: direct, indirect, multi-step |
| `libs/evals/tests/evals/test_tool_usage_relational.py` | Multi-step chaining with dependent lookups (1–5 tool chain depth) |
| `libs/evals/tests/evals/test_memory.py` | Memory recall from AGENTS.md, preference persistence, composite backends |
| `libs/evals/tests/evals/test_memory_multiturn.py` | Multi-turn implicit/explicit preference extraction |
| `libs/evals/tests/evals/test_external_benchmarks.py` | FRAMES, Nexus, BFCL v3 runners |
| `libs/evals/tests/evals/memory_agent_bench/` | MemoryAgentBench (ICLR 2026) runner |
| `libs/evals/tests/evals/tau2_airline/` | tau2-bench airline domain: multi-turn conversation scoring |
| `libs/evals/tests/evals/test_summarization.py` | Summarization middleware and filesystem offload |
| `libs/evals/tests/evals/test_hitl.py` | Human-in-the-loop via `interrupt_on` configs |
| `libs/evals/tests/evals/test_subagents.py` | Subagent delegation behavior |
| `libs/evals/tests/evals/test_skills.py` | Skill discovery, reading, and application |
| `libs/evals/deepagents_evals/categories.json` | Category registry: names, labels, radar inclusion flags |
| `libs/evals/deepagents_harbor/` | Harbor `DeepAgentsWrapper` for Terminal Bench 2.0 |
| `libs/evals/scripts/generate_radar.py` | Radar chart generator from eval summary JSON |
| `libs/evals/EVAL_CATALOG.md` | Auto-generated catalog: all 85 evals grouped by category with source links |

## See Also

- [Subagent System](./subagent-system.md)
- [Memory System](./memory-system.md)
- [Skills System](./skills-system.md)
- [Sandbox Partners](./sandbox-partners.md)
