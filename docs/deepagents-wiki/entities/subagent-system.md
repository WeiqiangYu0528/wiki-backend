# Subagent System

## Overview

The subagent system gives the main agent a `task` tool it can use to delegate work to short-lived, isolated sub-agents. Each sub-agent runs inside its own graph with its own tools, system prompt, and context window, then returns a single structured result to the parent.

Three modes cover different deployment needs:

- **`SubAgent`** — an inline spec compiled into a LangGraph at middleware construction time. Requires `model` and `tools` to be specified explicitly.
- **`CompiledSubAgent`** — wraps any pre-built LangGraph `Runnable`. The caller is responsible for construction; the middleware just invokes it.
- **`AsyncSubAgent`** — connects to a remote [Agent Protocol](https://github.com/langchain-ai/agent-protocol) server (LangGraph Platform or self-hosted) via the LangGraph SDK. Returns a task ID immediately so the main agent can continue working while the background job runs.

`SubAgentMiddleware` (inline) and `AsyncSubAgentMiddleware` (remote) each inject their own tool sets and system prompt additions into the parent agent.

## Key Types / Key Concepts

### `SubAgent` (TypedDict)

Defined in `libs/deepagents/deepagents/middleware/subagents.py`.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Unique identifier; used as `subagent_type` in the `task` tool. |
| `description` | `str` | yes | Shown in the `task` tool description so the parent knows when to delegate. |
| `system_prompt` | `str` | yes | Instructions for the sub-agent. Include output format requirements. |
| `tools` | `Sequence[BaseTool | Callable | dict]` | yes (in `SubAgentMiddleware`) | Tools available to the sub-agent. |
| `model` | `str | BaseChatModel` | yes (in `SubAgentMiddleware`) | Model string in `'provider:model-name'` format, e.g. `'openai:gpt-4o'`. |
| `middleware` | `list[AgentMiddleware]` | no | Additional middleware applied only to this sub-agent. |
| `interrupt_on` | `dict[str, bool | InterruptOnConfig]` | no | Human-in-the-loop configuration per tool. Requires a checkpointer. |
| `skills` | `list[str]` | no | Skill source paths passed to `SkillsMiddleware`. |

When using `create_deep_agent`, sub-agents automatically receive a default middleware stack (TodoListMiddleware, FilesystemMiddleware, SummarizationMiddleware, etc.) before any custom `middleware` specified in the spec.

### `CompiledSubAgent` (TypedDict)

| Field | Type | Notes |
| --- | --- | --- |
| `name` | `str` | Unique identifier. |
| `description` | `str` | Used in the `task` tool description. |
| `runnable` | `Runnable` | Any LangGraph or LangChain agent. The state schema **must** include a `messages` key; the middleware extracts `messages[-1]` as the final result. |

Use `CompiledSubAgent` when you need full control over the sub-agent graph (custom state schema, custom routing, etc.).

### `AsyncSubAgent` (TypedDict)

Defined in `libs/deepagents/deepagents/middleware/async_subagents.py`.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Unique identifier. |
| `description` | `str` | yes | Shown in the `start_async_task` tool description. |
| `graph_id` | `str` | yes | Graph name or assistant ID on the remote Agent Protocol server. |
| `url` | `str` | no | URL of the remote server. Omit to use ASGI transport for local servers. |
| `headers` | `dict[str, str]` | no | Additional HTTP headers. `x-auth-scheme: langsmith` is added automatically unless overridden. |

Authentication for LangGraph Platform is handled by the LangGraph SDK via `LANGGRAPH_API_KEY`, `LANGSMITH_API_KEY`, or `LANGCHAIN_API_KEY` environment variables.

### `AsyncTask` (TypedDict)

Persisted in `AsyncSubAgentState.async_tasks`, keyed by `task_id`. Tracks `thread_id`, `run_id`, `status`, and three ISO-8601 UTC timestamps: `created_at`, `last_checked_at`, `last_updated_at`.

### The `task` Tool

Built by `_build_task_tool()` and registered as a LangChain `StructuredTool` with `name="task"`.

**Input schema** (`TaskToolSchema`):

| Field | Description |
| --- | --- |
| `description` | Detailed task description including all necessary context and expected output format. |
| `subagent_type` | Name of the sub-agent to invoke; must match one of the registered sub-agent names. |

The tool description is built from `TASK_TOOL_DESCRIPTION`, which embeds the list of available agents via the `{available_agents}` placeholder. It includes usage guidelines (parallelize independent tasks, always summarize results to the user, treat agents as stateless) and worked examples.

Both a sync (`task`) and async (`atask`) implementation are registered on the same `StructuredTool`. LangGraph selects the appropriate variant based on the execution context.

### Async Tools

`AsyncSubAgentMiddleware` registers five tools:

| Tool | Schema | Purpose |
| --- | --- | --- |
| `start_async_task` | `StartAsyncTaskSchema` | Launch a background run; returns a `task_id` immediately. |
| `check_async_task` | `CheckAsyncTaskSchema` | Fetch current status and result for a task. |
| `update_async_task` | `UpdateAsyncTaskSchema` | Send follow-up instructions; starts a new run on the same thread. |
| `cancel_async_task` | `CancelAsyncTaskSchema` | Stop a running task. |
| `list_async_tasks` | `ListAsyncTasksSchema` | List all tracked tasks; filterable by `status`. |

### `SubAgentMiddleware`

Defined in `libs/deepagents/deepagents/middleware/subagents.py`.

Constructor parameters:

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `backend` | `BackendProtocol | BackendFactory` | — | Required. |
| `subagents` | `Sequence[SubAgent | CompiledSubAgent]` | — | Required. At least one entry. |
| `system_prompt` | `str | None` | `TASK_SYSTEM_PROMPT` | Appended to the main agent's system prompt. Pass `None` to suppress. |
| `task_description` | `str | None` | `None` | Custom `task` tool description. Supports `{available_agents}` placeholder. |

On construction, `SubAgentMiddleware`:
1. Validates that every `SubAgent` entry has `model` and `tools`.
2. Compiles each `SubAgent` into a `create_agent(...)` runnable.
3. Passes `CompiledSubAgent` runnables through unchanged.
4. Calls `_build_task_tool()` to produce the `task` `StructuredTool`.
5. Appends the available-agent list to `system_prompt`.

`wrap_model_call` / `awrap_model_call` append the system prompt to every model request via `append_to_system_message()`.

### Built-in General-Purpose Sub-agent

`GENERAL_PURPOSE_SUBAGENT` is a pre-defined `SubAgent` spec with `name="general-purpose"` included automatically by `create_deep_agent`. It has access to all the same tools as the main agent and is used when no specialised sub-agent matches the task.

### CLI Sub-agent Loading

The CLI loads user-defined sub-agents from the filesystem at startup via `list_subagents()` in `libs/cli/deepagents_cli/subagents.py`.

Sub-agents are defined as markdown files with YAML frontmatter:

```
.deepagents/agents/{agent_name}/AGENTS.md
```

Example file:

```markdown
---
name: researcher
description: Research topics on the web before writing content
model: anthropic:claude-haiku-4-5-20251001
---

You are a research assistant with access to web search.
```

Required frontmatter fields: `name`, `description`. Optional: `model` (overrides the default). The markdown body becomes `system_prompt`.

**Source precedence**: project-level agents (`.deepagents/agents/`) override user-level agents (`~/.deepagents/agents/`) when names collide.

## Architecture

### Sync / Inline Execution Flow

```
Parent agent calls task(description, subagent_type)
  → _validate_and_prepare_state()
      - copies parent state, strips _EXCLUDED_STATE_KEYS
        (messages, todos, structured_response, skills_metadata, memory_contents)
      - wraps description in HumanMessage as the conversation start
  → subagent_graph.invoke(subagent_state)     # blocks until complete
  → _return_command_with_state_update()
      - extracts messages[-1].text; strips trailing whitespace
      - returns Command(update={non-excluded state keys,
                                messages: [ToolMessage(result, tool_call_id)]})
Parent receives ToolMessage with the sub-agent's final report
```

The async path (`atask`) is structurally identical but calls `subagent.ainvoke()`.

### Async / Remote Execution Flow

```
Parent agent calls start_async_task(description, subagent_type)
  → SDK creates a new thread on the remote Agent Protocol server
  → SDK creates a run with description as the initial HumanMessage
  → AsyncTask stored in state (task_id, thread_id, run_id, status="running")
  → Returns task_id immediately; parent continues other work

Later, on user request:
  check_async_task(task_id)
  → fetches live run status from remote server
  → status "success": returns final message content
  → status "running": reports status; instructs agent to wait for next user turn
  → never polls in a loop
```

### Context Isolation

Each inline sub-agent invocation:

- Receives a **fresh state** derived from the parent but with `_EXCLUDED_STATE_KEYS` stripped. This prevents parent message history, todo list, skills metadata, and memory contents from leaking into the child.
- Gets a single `HumanMessage` containing the task description as its entire conversation history.
- Runs its own complete graph execution — no shared state with the parent during execution.
- On completion, only non-excluded state keys are merged back into parent state.

This means a general-purpose sub-agent will load its own skills via `SkillsMiddleware` rather than inheriting whatever skill metadata the parent accumulated.

### Result Flow Back to Parent

`_return_command_with_state_update()`:

1. Validates the result contains a `messages` key (required for both `CompiledSubAgent` and `SubAgent`).
2. Passes through any non-excluded state keys as atomic updates to parent state (e.g., files written by the sub-agent can surface in the parent's workspace state).
3. Converts `messages[-1].text` into a `ToolMessage` bound to the originating `tool_call_id`.
4. Returns a LangGraph `Command` that applies both updates atomically.

## Source Files

| File | Purpose |
| --- | --- |
| `libs/deepagents/deepagents/middleware/subagents.py` | Core types (`SubAgent`, `CompiledSubAgent`, `TaskToolSchema`), `_build_task_tool()`, `SubAgentMiddleware` |
| `libs/deepagents/deepagents/middleware/async_subagents.py` | `AsyncSubAgent`, `AsyncTask`, all async tool builders, `AsyncSubAgentMiddleware` |
| `libs/cli/deepagents_cli/subagents.py` | CLI filesystem loader: `SubagentMetadata`, `list_subagents()`, YAML frontmatter parsing |
| `libs/cli/deepagents_cli/agent.py` | CLI agent factory; wires sub-agent specs into `create_deep_agent` |

## See Also

- [Memory System](memory-system.md)
- [Skills System](skills-system.md)
- [Graph Factory](graph-factory.md)
- [CLI Runtime](cli-runtime.md)
- [Backend System](backend-system.md)
- [Filesystem First Agent Configuration](../concepts/filesystem-first-agent-configuration.md)
- [Remote Subagent and Sandbox Flow](../syntheses/remote-subagent-and-sandbox-flow.md)
- [Batteries Included Agent Architecture](../concepts/batteries-included-agent-architecture.md)
- [Sdk To Cli Composition](../syntheses/sdk-to-cli-composition.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
