# Human-in-the-Loop Approval

## Overview

Agents that can write files, run shell commands, browse the web, or launch subagents need a safety gate before side effects are committed. The Human-in-the-Loop (HITL) system pauses agent execution at nominated tool calls, presents the pending action to the operator, and resumes only after an explicit decision is received.

In deepagents this is implemented on two levels:

1. **`HumanInTheLoopMiddleware`** (from `langchain.agents.middleware`) — intercepts tool calls at the graph layer and emits a LangGraph `interrupt()` when a tool name matches the `interrupt_on` map.
2. **`AskUserMiddleware`** (`libs/cli/deepagents_cli/ask_user.py`) — adds an `ask_user` tool the agent can call at any point to pose free-form or multiple-choice questions to the operator.

Both mechanisms use the same underlying LangGraph interrupt/resume protocol: the graph suspends, the CLI adapter collects a response, and the graph resumes with that response injected as a `ToolMessage`.

## Mechanism

### `interrupt_on` configuration

`create_deep_agent()` accepts an `interrupt_on` parameter:

```python
agent = create_deep_agent(
    interrupt_on={
        "edit_file": True,
        "execute": {"allowed_decisions": ["approve", "reject"]},
    }
)
```

Values can be:
- `True` — pause with default approve/reject options.
- `InterruptOnConfig` dict — specify `allowed_decisions` and an optional `description` callable that formats the tool arguments into a human-readable summary.

When `interrupt_on` is not `None`, `create_deep_agent()` appends `HumanInTheLoopMiddleware(interrupt_on=interrupt_on)` to the main agent middleware stack. Declarative `SubAgent` specs inherit the top-level `interrupt_on` map unless they provide their own override. `CompiledSubAgent` and `AsyncSubAgent` do not inherit it.

The CLI's `_add_interrupt_on()` function (in `agent.py`) builds the default interrupt map for interactive sessions, gating these tools:
- `execute` — formatted description of the shell command
- `write_file`, `edit_file` — file path and content previews
- `web_search`, `fetch_url` — URL/query descriptions
- `task` — subagent name and prompt
- async subagent launch/cancel/update tools

When `auto_approve=True` (non-interactive / CI mode), `interrupt_on` is set to `{}` and no interrupts fire. `ShellAllowListMiddleware` then takes over shell validation inline without pausing the graph.

### LangGraph interrupt and resume

When `HumanInTheLoopMiddleware` intercepts a matching tool call, it invokes LangGraph's `interrupt()` with a payload describing the pending action. The graph state is checkpointed and the current execution thread suspends.

The CLI adapter receives the interrupt payload, renders the approval UI, and waits for operator input. The operator's decision is passed back via `graph.invoke(..., command=Command(resume=decision))`. The middleware receives the resume value, either proceeds with the tool call (approve) or injects an error `ToolMessage` (reject), and graph execution continues from the checkpoint.

### `ask_user` tool

`AskUserMiddleware` registers an `ask_user` tool and injects a system prompt section:

```
Use this tool sparingly - only when you genuinely need information from the user
that you cannot determine from context.
```

When the agent calls `ask_user`, the tool:
1. Validates the question list with `_validate_questions()`.
2. Packages questions into an `AskUserRequest` and calls `interrupt(ask_request)`.
3. The graph suspends; the CLI adapter renders the question UI.
4. On resume, `_parse_answers()` processes the response dict and returns a `Command` with a `ToolMessage` containing formatted Q&A pairs.

The resume payload carries a `status` field:
- `"answered"` — consume the `answers` list (one entry per question).
- `"cancelled"` — synthesize `"(cancelled)"` for every question.
- `"error"` — synthesize `"(error: ...)"` for every question.

### Data structures (`_ask_user_types.py`)

```python
class Question(TypedDict):
    question: str                           # Display text
    type: Literal["text", "multiple_choice"]
    choices: NotRequired[list[Choice]]      # Only for multiple_choice
    required: NotRequired[bool]             # Default: True

class AskUserRequest(TypedDict):
    type: Literal["ask_user"]
    questions: list[Question]
    tool_call_id: str                       # Routes response back to the tool call

class AskUserAnswered(TypedDict):
    type: Literal["answered"]
    answers: list[str]                      # One answer per question

class AskUserCancelled(TypedDict):
    type: Literal["cancelled"]

AskUserWidgetResult = AskUserAnswered | AskUserCancelled
```

`AskUserRequest` is what the graph emits via `interrupt()`. `AskUserWidgetResult` is what the CLI widget places into the resume future.

### Answer formatting

`_parse_answers()` formats each Q&A pair as:

```
Q: {question text}
A: {answer}
```

Multiple pairs are joined with double newlines and returned as a single `ToolMessage` content string.

## Involved Entities

- [Graph Factory](../entities/graph-factory.md) — `create_deep_agent()` in `graph.py` accepts and applies `interrupt_on`; it is the primary integration point for HITL configuration.
- [CLI Runtime](../entities/cli-runtime.md) — `agent.py` builds the default `interrupt_on` map via `_add_interrupt_on()`, manages `auto_approve` logic, and drives the interrupt/resume cycle through the Textual adapter.

## Source Evidence

**`libs/deepagents/deepagents/graph.py`** — `interrupt_on` wiring in `create_deep_agent()`:

```python
if interrupt_on is not None:
    deepagent_middleware.append(HumanInTheLoopMiddleware(interrupt_on=interrupt_on))
```

Subagent inheritance:
```python
subagent_interrupt_on = spec.get("interrupt_on", interrupt_on)
```

**`libs/cli/deepagents_cli/agent.py`** — Default interrupt map construction:

```python
execute_interrupt_config: InterruptOnConfig = {
    "allowed_decisions": ["approve", "reject"],
    "description": _format_execute_description,
}
# ... similarly for write_file, edit_file, web_search, fetch_url, task
interrupt_on = _add_interrupt_on()
```

Auto-approve bypass:
```python
if auto_approve or shell_middleware_added:
    interrupt_on = {}
else:
    interrupt_on = _add_interrupt_on()
```

**`libs/cli/deepagents_cli/ask_user.py`** — Core interrupt call inside the `ask_user` tool:

```python
ask_request = AskUserRequest(
    type="ask_user",
    questions=questions,
    tool_call_id=tool_call_id,
)
response = interrupt(ask_request)
return _parse_answers(response, questions, tool_call_id)
```

`AskUserMiddleware` constructor showing configurable prompts:
```python
def __init__(
    self,
    *,
    system_prompt: str = ASK_USER_SYSTEM_PROMPT,
    tool_description: str = ASK_USER_TOOL_DESCRIPTION,
) -> None:
```

## See Also

- [Context Management and Summarization](context-management-and-summarization.md)
- [Local vs Remote Execution](local-vs-remote-execution.md)
- [Batteries-Included Agent Architecture](batteries-included-agent-architecture.md)
