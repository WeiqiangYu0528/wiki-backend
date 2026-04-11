# Batteries-Included Agent Architecture

## Overview

deepagents is described in its own README as "the batteries-included agent harness." This means that calling `create_deep_agent()` with no arguments produces a fully functional agent — one with planning, filesystem access, context management, subagent delegation, prompt caching, and memory — without the user wiring up any of that infrastructure.

The middleware-first design is the mechanism that makes this possible. Every capability is delivered as a discrete layer in a composable middleware stack, and the default stack is pre-assembled inside `create_deep_agent()`. Users extend the agent by appending to `middleware=` or passing `tools=`; they do not replace what already works.

## Mechanism

`create_deep_agent()` builds two parallel middleware stacks — one for the main agent and one for each subagent — then hands them to LangGraph's `create_agent()`.

### Main agent middleware assembly order

The stack is assembled in `graph.py`. The order determines both the tool registration order and the model-call wrapping order (outermost middleware wraps innermost):

```python
# libs/deepagents/deepagents/graph.py  (lines 292–322)

deepagent_middleware: list[AgentMiddleware] = [
    TodoListMiddleware(),                                          # 1. Planning
]
# SkillsMiddleware inserted here when skills= is set             # 2. Skills (optional)
deepagent_middleware.extend([
    FilesystemMiddleware(backend=backend),                        # 3. File + shell tools
    SubAgentMiddleware(backend=backend, subagents=inline_subagents),  # 4. task tool
    create_summarization_middleware(model, backend),              # 5. Auto-summarization
    PatchToolCallsMiddleware(),                                   # 6. Tool-call normalization
])
# AsyncSubAgentMiddleware appended when async subagents present  # 7. Async delegation
# ── user middleware inserted here via middleware= param ──      # 8. User extensions
deepagent_middleware.append(
    AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")  # 9. Prompt caching
)
# MemoryMiddleware appended when memory= is set                  # 10. Memory (optional)
# HumanInTheLoopMiddleware appended when interrupt_on= is set   # 11. HITL (conditional)
```

The comment in the source is explicit about why caching and memory come last:

```python
# Caching + memory after all other middleware so memory updates don't
# invalidate the Anthropic prompt cache prefix.
```

### What each layer contributes

Each middleware layer can independently:
- **Add tools** — expose new `BaseTool` instances the model can call.
- **Wrap the model call** — intercept `wrap_model_call` / `awrap_model_call` to modify the request or response (inject a system-prompt section, rewrite messages, add caching headers, etc.).

| Layer | Tools added | Model-call effect |
|---|---|---|
| `TodoListMiddleware` | `write_todos` | None |
| `SkillsMiddleware` | Loaded skill tools | Injects skill catalog into system prompt |
| `FilesystemMiddleware` | `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute` | None |
| `SubAgentMiddleware` | `task` | None |
| `SummarizationMiddleware` | None | Compacts conversation when token threshold exceeded |
| `PatchToolCallsMiddleware` | None | Normalizes tool-call formatting |
| `AnthropicPromptCachingMiddleware` | None | Adds Anthropic cache headers |
| `MemoryMiddleware` | None | Injects AGENTS.md content into system prompt |
| `HumanInTheLoopMiddleware` | None | Gates specified tool calls for approval |

### Subagent middleware stack

Every declarative `SubAgent` receives its own copy of the base layers before any subagent-specific middleware:

```python
subagent_middleware = [
    TodoListMiddleware(),
    FilesystemMiddleware(backend=backend),
    create_summarization_middleware(subagent_model, backend),
    PatchToolCallsMiddleware(),
    # SkillsMiddleware appended when subagent declares skills
    # subagent-specific user middleware appended here
    AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
]
```

A `general-purpose` subagent with this stack is always added unless the caller provides one by that name.

### Base system prompt

`create_deep_agent()` ships a `BASE_AGENT_PROMPT` that instructs the model to be concise, avoid preamble, read before acting, verify its work, and emit progress updates on long tasks. A caller-supplied `system_prompt` is prepended to (not replacing) this base.

### Zero-configuration usage

```python
from deepagents import create_deep_agent

agent = create_deep_agent()
result = agent.invoke({
    "messages": [{"role": "user", "content": "Research LangGraph and write a summary"}]
})
```

Out of the box the agent can manage a todo list, read and write files, run shell commands (if the backend implements sandboxing), delegate subtasks to a general-purpose subagent, summarize its own context when conversations grow long, and cache prompts for Anthropic models.

### Extending without replacing

User-supplied middleware slots in at position 8 — after `PatchToolCallsMiddleware`, before `AnthropicPromptCachingMiddleware` — leaving the default stack intact:

```python
from langchain.chat_models import init_chat_model

agent = create_deep_agent(
    model=init_chat_model("openai:gpt-4o"),
    tools=[my_custom_tool],
    system_prompt="You are a research assistant.",
    middleware=[my_custom_middleware],
)
```

MCP tools are supported via `langchain-mcp-adapters` and passed through `tools=`.

## Involved Entities

- [`create_deep_agent()`](../entities/graph-factory.md) — the factory that assembles the full stack
- [`TodoListMiddleware`](../entities/graph-factory.md) — planning layer (`write_todos`)
- [`FilesystemMiddleware`](../syntheses/agent-customization-surface.md) — file and shell tools
- [`SubAgentMiddleware`](../syntheses/agent-customization-surface.md) — `task` tool and subagent dispatch
- [`SummarizationMiddleware`](./context-management-and-summarization.md) — context management layer
- [`PatchToolCallsMiddleware`](../entities/graph-factory.md) — tool-call normalization
- [`AnthropicPromptCachingMiddleware`](../entities/graph-factory.md) — prompt caching
- [`MemoryMiddleware`](../syntheses/agent-customization-surface.md) — AGENTS.md injection
- [`HumanInTheLoopMiddleware`](./human-in-the-loop-approval.md) — approval gating

## Source Evidence

**Default stack assembly** — `libs/deepagents/deepagents/graph.py`, lines 292–322. The `deepagent_middleware` list is built in that block with the ordering documented above.

**Subagent stack** — same file, lines 261–271. Mirrors the main agent's base layers, then appends subagent-specific middleware.

**README tagline** — `README.md`, lines 3 and 24:

> "The batteries-included agent harness."
> "An opinionated, ready-to-run agent out of the box. Instead of wiring up prompts, tools, and context management yourself, you get a working agent immediately and customize what you need."

**Public API surface** — `libs/deepagents/deepagents/__init__.py`: only `create_deep_agent` and the subagent types are exported, confirming the factory is the primary entry point.

**Middleware insertion comment** — `graph.py`, lines 314–317:

```python
if middleware:
    deepagent_middleware.extend(middleware)
# Caching + memory after all other middleware so memory updates don't
# invalidate the Anthropic prompt cache prefix.
```

## See Also

- [Context Management and Summarization](./context-management-and-summarization.md)
- [Human-in-the-Loop Approval](./human-in-the-loop-approval.md)
- [Agent Customization Surface](../syntheses/agent-customization-surface.md)
- [SDK to CLI Composition](../syntheses/sdk-to-cli-composition.md)
- [Architecture Overview](../summaries/architecture-overview.md)
