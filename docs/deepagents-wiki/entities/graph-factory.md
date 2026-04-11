# Graph Factory

## Overview

`create_deep_agent()` is the central entry point of the Deep Agents SDK. It is the "policy-rich constructor" that assembles a LangGraph compiled state graph with a pre-wired middleware stack, built-in tools, and a pluggable backend. Callers get back a `CompiledStateGraph` that is already configured for planning, file manipulation, subagent delegation, context summarization, and (optionally) shell execution — no manual middleware wiring required.

The factory encodes product opinion into the assembly layer itself. It decides what a Deep Agents runtime looks like before any CLI, API surface, or UI gets involved. Every Deep Agents deployment — CLI, SDK integration, or remote deployment — is ultimately rooted in a graph produced by this function.

This page should be read alongside [Backend System](backend-system.md) (what storage and execution the graph can reach), [Subagent System](subagent-system.md) (how the `task` tool is wired), and [Batteries Included Agent Architecture](../concepts/batteries-included-agent-architecture.md) (the design rationale for the middleware defaults).

---

## Key Types / Key Concepts

### Full signature of `create_deep_agent()`

```python
def create_deep_agent(
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    *,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    subagents: Sequence[SubAgent | CompiledSubAgent | AsyncSubAgent] | None = None,
    skills: list[str] | None = None,
    memory: list[str] | None = None,
    response_format: ResponseFormat[ResponseT] | type[ResponseT] | dict[str, Any] | None = None,
    context_schema: type[ContextT] | None = None,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    backend: BackendProtocol | BackendFactory | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache | None = None,
) -> CompiledStateGraph[AgentState[ResponseT], ContextT, _InputAgentState, _OutputAgentState[ResponseT]]
```

#### Parameter reference

| Parameter | Type | Default | Description |
|---|---|---|---|
| `model` | `str \| BaseChatModel \| None` | `None` | Model to use. Defaults to `claude-sonnet-4-6`. Accepts `provider:model` strings (e.g. `openai:gpt-5`). `openai:` prefixed strings default to the Responses API. |
| `tools` | `Sequence[BaseTool \| Callable \| dict] \| None` | `None` | Custom tools to add alongside the built-in file/shell/subagent tools. |
| `system_prompt` | `str \| SystemMessage \| None` | `None` | Custom instructions prepended before `BASE_AGENT_PROMPT`. String values are concatenated; `SystemMessage` values have the base prompt appended as a text block. |
| `middleware` | `Sequence[AgentMiddleware]` | `()` | Additional middleware inserted after the base stack but before `AnthropicPromptCachingMiddleware` and `MemoryMiddleware`. |
| `subagents` | `Sequence[SubAgent \| CompiledSubAgent \| AsyncSubAgent] \| None` | `None` | Subagent specs available via the `task` tool. See Subagent types below. |
| `skills` | `list[str] \| None` | `None` | POSIX paths to skill source directories (relative to backend root). Later entries override earlier ones for same-name skills. |
| `memory` | `list[str] \| None` | `None` | Paths to `AGENTS.md` memory files loaded at startup and injected into the system prompt. |
| `response_format` | `ResponseFormat \| type \| dict \| None` | `None` | Structured output schema for the agent's final response. |
| `context_schema` | `type[ContextT] \| None` | `None` | Schema for the agent's typed context object. |
| `checkpointer` | `Checkpointer \| None` | `None` | LangGraph checkpointer for persisting state between runs. |
| `store` | `BaseStore \| None` | `None` | Persistent store (required when using `StoreBackend`). |
| `backend` | `BackendProtocol \| BackendFactory \| None` | `None` | Storage/execution backend. Defaults to `StateBackend()`. |
| `interrupt_on` | `dict[str, bool \| InterruptOnConfig] \| None` | `None` | Tool names mapped to interrupt configs for human-in-the-loop approval. Inherited by declarative `SubAgent` specs unless overridden. |
| `debug` | `bool` | `False` | Enable LangGraph debug mode. |
| `name` | `str \| None` | `None` | Agent name, passed through to `create_agent` and stored in run metadata. |
| `cache` | `BaseCache \| None` | `None` | LangGraph cache for node-level caching. |

### Subagent spec types

Three forms are accepted in the `subagents` sequence:

- **`SubAgent`** — declarative synchronous spec. Provides `name`, `description`, `system_prompt`, and optionally overrides `tools`, `model`, `middleware`, `interrupt_on`, and `skills`. Invoked via the `task` tool.
- **`CompiledSubAgent`** — provides a pre-built `runnable` instead of a declarative config. Also exposed via `task`. Does not inherit top-level `interrupt_on`.
- **`AsyncSubAgent`** — identified by `graph_id` (and optionally `url`/`headers`). Routed into `AsyncSubAgentMiddleware` for non-blocking background execution. Exposes tools for launching, checking, updating, cancelling, and listing async tasks.

If no subagent named `general-purpose` is present in the provided list, a default general-purpose synchronous subagent is added automatically at position 0.

### `BASE_AGENT_PROMPT`

The base system prompt wired into every deep agent (defined in `graph.py`, module-level constant):

```
You are a Deep Agent, an AI assistant that helps users accomplish tasks using tools.
You respond with text and tool calls. The user can see your responses and tool outputs
in real time.

## Core Behavior
- Be concise and direct. Don't over-explain unless asked.
- NEVER add unnecessary preamble ("Sure!", "Great question!", "I'll now...").
- Don't say "I'll now do X" — just do it.
- If the request is ambiguous, ask questions before acting.
- If asked how to approach something, explain first, then act.

## Professional Objectivity
- Prioritize accuracy over validating the user's beliefs
- Disagree respectfully when the user is incorrect
- Avoid unnecessary superlatives, praise, or emotional validation

## Doing Tasks
1. Understand first — read relevant files, check existing patterns.
2. Act — implement the solution. Work quickly but accurately.
3. Verify — check your work against what was asked, not against your own output.

Keep working until the task is fully complete. Only yield back to the user when the
task is done or you're genuinely blocked.

## Progress Updates
For longer tasks, provide brief progress updates at reasonable intervals.
```

When `system_prompt` is provided, it is prepended: string values are joined with `\n\n`, and `SystemMessage` values have the base prompt appended as an additional text content block.

### `get_default_model()`

```python
def get_default_model() -> ChatAnthropic:
    return ChatAnthropic(model_name="claude-sonnet-4-6")
```

Called when `model=None`. Returns a `ChatAnthropic` instance configured with `claude-sonnet-4-6`.

### `resolve_model()` (from `_models.py`)

```python
def resolve_model(model: str | BaseChatModel) -> BaseChatModel
```

String models are resolved via `init_chat_model`. Special cases:
- `openai:*` strings default to the Responses API (`use_responses_api=True`).
- `openrouter:*` strings inject default app attribution headers unless overridden by `OPENROUTER_APP_URL` / `OPENROUTER_APP_TITLE` env vars. Requires `langchain-openrouter>=0.2.0`.
- Pre-constructed `BaseChatModel` instances are returned unchanged.

---

## Architecture

### Middleware stack assembly

The factory builds two separate middleware stacks: one for the main agent and one for each declarative `SubAgent` spec.

**Main agent middleware stack** (assembled in order):

1. `TodoListMiddleware()` — provides the `write_todos` planning tool
2. `SkillsMiddleware(backend, sources)` — only if `skills` is not `None`
3. `FilesystemMiddleware(backend)` — provides `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`
4. `SubAgentMiddleware(backend, subagents)` — provides the `task` tool for synchronous subagents
5. `create_summarization_middleware(model, backend)` — context window management via summarization
6. `PatchToolCallsMiddleware()` — corrects malformed tool call arguments from the model
7. `AsyncSubAgentMiddleware(async_subagents)` — only if async subagent specs were provided
8. *User-supplied `middleware`* — inserted here, after the base stack
9. `AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")` — prompt cache prefix optimization; placed last before memory so memory updates don't invalidate the cache
10. `MemoryMiddleware(backend, sources)` — only if `memory` is not `None`
11. `HumanInTheLoopMiddleware(interrupt_on)` — only if `interrupt_on` is not `None`

**Each declarative `SubAgent`** receives an independent copy of the following base stack (prepended to any middleware the spec declares, followed by `AnthropicPromptCachingMiddleware`):

1. `TodoListMiddleware()`
2. `FilesystemMiddleware(backend)`
3. `create_summarization_middleware(subagent_model, backend)`
4. `PatchToolCallsMiddleware()`
5. `SkillsMiddleware(backend, sources)` — only if the spec declares `skills`
6. *Spec's own `middleware`*
7. `AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")`

The general-purpose subagent is treated specially: it gets the same base middleware stack plus `SkillsMiddleware` (if top-level `skills` is set), but its middleware list is constructed separately from the user-provided subagents list.

### Built-in tools

The following tools are automatically available via the middleware stack. They require no explicit configuration:

| Tool | Source middleware | Requires backend feature |
|---|---|---|
| `write_todos` | `TodoListMiddleware` | None |
| `ls` | `FilesystemMiddleware` | `BackendProtocol` |
| `read_file` | `FilesystemMiddleware` | `BackendProtocol` |
| `write_file` | `FilesystemMiddleware` | `BackendProtocol` |
| `edit_file` | `FilesystemMiddleware` | `BackendProtocol` |
| `glob` | `FilesystemMiddleware` | `BackendProtocol` |
| `grep` | `FilesystemMiddleware` | `BackendProtocol` |
| `execute` | `FilesystemMiddleware` | `SandboxBackendProtocol` (returns error if unavailable) |
| `task` | `SubAgentMiddleware` | None |

### LangGraph graph structure

The factory calls `create_agent(...)` from `langchain.agents`, passing the resolved model, system prompt, tools, and assembled middleware. The result is a `CompiledStateGraph` operating over `AgentState[ResponseT]`.

After compilation, `.with_config()` is applied to set:
- `recursion_limit`: `9_999` (effectively unlimited for long-running agents)
- `metadata.ls_integration`: `"deepagents"`
- `metadata.versions.deepagents`: the installed package version
- `metadata.lc_agent_name`: the `name` parameter value

The graph is a standard LangGraph agent loop (call model → route to tools or end → call tools → repeat). The middleware stack wraps this loop with pre/post-processing at each step.

---

## Source Files

| File | Purpose |
|---|---|
| `libs/deepagents/deepagents/graph.py` | `create_deep_agent()` factory, `BASE_AGENT_PROMPT`, `get_default_model()`, full middleware assembly logic |
| `libs/deepagents/deepagents/__init__.py` | Public SDK export surface — re-exports `create_deep_agent`, subagent types, middleware classes, and `__version__` |
| `libs/deepagents/deepagents/_models.py` | `resolve_model()`, `get_model_identifier()`, `model_matches_spec()`, OpenRouter version check and attribution helpers |

---

## See Also

- [Backend System](backend-system.md)
- [Subagent System](subagent-system.md)
- [Batteries Included Agent Architecture](../concepts/batteries-included-agent-architecture.md)
- [Agent Customization Surface](../syntheses/agent-customization-surface.md)
- [Sdk To Cli Composition](../syntheses/sdk-to-cli-composition.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
