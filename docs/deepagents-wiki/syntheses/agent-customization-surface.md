# Agent Customization Surface

## Overview

Deep Agents exposes four distinct customization surfaces: the `create_deep_agent()` parameter list, the CLI config file at `~/.deepagents/config.toml`, filesystem conventions (`.deepagents/` directory, `AGENTS.md`, `SKILL.md` files), and the middleware protocol. Understanding which surface to use for which concern—and how the surfaces compose—is the practical guide to extending agent behavior without rewriting the harness.

## Systems Involved

- [Graph Factory](../entities/graph-factory.md) — `create_deep_agent()` parameter list and middleware assembly
- [CLI Runtime](../entities/cli-runtime.md) — config file loading and CLI-specific middleware
- [Filesystem-First Agent Configuration](../concepts/filesystem-first-agent-configuration.md) — skills, memory, and subagents as files
- [Skills System](../entities/skills-system.md) — `SkillsMiddleware`, `SKILL.md` discovery
- [Memory System](../entities/memory-system.md) — `MemoryMiddleware`, `AGENTS.md` loading

## Interaction Model

### Surface 1 — `create_deep_agent()` Parameters

The full parameter list of `create_deep_agent()` (in `libs/deepagents/deepagents/graph.py`):

| Parameter | Type | Default | Purpose |
|---|---|---|---|
| `model` | `str \| BaseChatModel \| None` | `claude-sonnet-4-6` | Model to use; accepts `"provider:model"` format (e.g., `"openai:gpt-4o"`) |
| `tools` | `Sequence[BaseTool \| Callable \| dict]` | `None` | Additional tools beyond the built-in set |
| `system_prompt` | `str \| SystemMessage \| None` | `None` | Custom instructions prepended before the base prompt |
| `middleware` | `Sequence[AgentMiddleware]` | `()` | Additional middleware inserted after the base stack, before `AnthropicPromptCachingMiddleware` |
| `subagents` | `Sequence[SubAgent \| CompiledSubAgent \| AsyncSubAgent]` | `None` | Subagent specs; `SubAgent` → sync `task` tool; `AsyncSubAgent` → async task tools |
| `skills` | `list[str]` | `None` | Backend-relative paths to skill source directories (e.g., `["/skills/"]`) |
| `memory` | `list[str]` | `None` | Backend-relative paths to `AGENTS.md` memory files injected at startup |
| `response_format` | `ResponseFormat \| type \| dict \| None` | `None` | Structured output schema for the agent's final response |
| `context_schema` | `type[ContextT]` | `None` | Schema for the LangGraph context object |
| `checkpointer` | `Checkpointer \| None` | `None` | LangGraph checkpointer for state persistence between runs |
| `store` | `BaseStore \| None` | `None` | Persistent store (required if backend uses `StoreBackend`) |
| `backend` | `BackendProtocol \| BackendFactory \| None` | `StateBackend()` | File storage and execution backend |
| `interrupt_on` | `dict[str, bool \| InterruptOnConfig] \| None` | `None` | Tool names mapped to HITL interrupt configs; e.g., `{"edit_file": True}` |
| `debug` | `bool` | `False` | Enable LangGraph debug mode |
| `name` | `str \| None` | `None` | Agent name passed to `create_agent` |
| `cache` | `BaseCache \| None` | `None` | LangGraph cache for the agent |

#### Subagent Forms

The `subagents` parameter accepts three forms with different routing:

```python
# Declarative sync subagent — exposed via the `task` tool
spec: SubAgent = {"name": "researcher", "description": "...", "system_prompt": "..."}

# Pre-compiled subagent — also via `task` tool, but with a pre-built runnable
spec: CompiledSubAgent = {"name": "sql", "runnable": compiled_graph}

# Async remote subagent — exposed via start_async_task / check_async_task
spec: AsyncSubAgent = {"name": "worker", "description": "...", "graph_id": "agent"}
```

`AsyncSubAgent` specs are detected by the presence of `graph_id` and routed into `AsyncSubAgentMiddleware` instead of `SubAgentMiddleware`.

A default `general-purpose` `SubAgent` is always added if none is explicitly provided.

#### Default Middleware Stack

```python
[
    TodoListMiddleware(),
    FilesystemMiddleware(backend=backend),
    create_summarization_middleware(model, backend),
    PatchToolCallsMiddleware(),
    # inserted if skills is not None:
    SkillsMiddleware(backend=backend, sources=skills),
    # user-provided middleware goes here
    AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
    # inserted if memory is not None:
    MemoryMiddleware(backend=backend, sources=memory),
]
```

The same stack is applied to each declarative `SubAgent` spec, with the subagent's own `middleware` list appended after `PatchToolCallsMiddleware`.

### Surface 2 — CLI Config File (`~/.deepagents/config.toml`)

The CLI reads configuration from `~/.deepagents/config.toml` (path constant: `DEFAULT_CONFIG_PATH` in `model_config.py`). Key sections:

```toml
# Model selection
[profile.default]
model = "anthropic:claude-sonnet-4-6"

# Theme preference
[ui]
theme = "langchain"

# Shell command allow-list (non-interactive mode)
[shell]
allow = ["ls", "cat", "pytest", "python"]

# Suppress specific startup warnings
[warnings]
suppress = ["ripgrep"]

# Async subagent definitions
[async_subagents.researcher]
description = "Research agent for long-running tasks"
graph_id = "researcher"
url = "https://my-langgraph-deployment.com"

# MCP server configuration
[mcp_servers.my_server]
command = "npx"
args = ["-y", "@my/mcp-server"]
```

Environment variables from `.env` files are loaded before the config in priority order: shell env > project `.env` > `~/.deepagents/.env`.

### Surface 3 — Filesystem Conventions

#### `AGENTS.md` — Memory Injection

Place an `AGENTS.md` file at any path accessible to the backend. Pass the path via `memory=["/AGENTS.md"]` to `create_deep_agent()`. The file is read at startup and injected verbatim into the system prompt. Multiple files are supported; display names are derived from paths.

The CLI's default `LocalContextMiddleware` also looks for `AGENTS.md` in the CWD during environment detection.

#### `.deepagents/skills/` — Skill Discovery

Each skill is a directory containing a `SKILL.md` file with YAML frontmatter:

```markdown
---
name: my-skill
description: What this skill does
---

# Instructions

Detailed instructions for using the skill...
```

Pass skill directories via `skills=[".deepagents/skills/"]`. `SkillsMiddleware` discovers all `SKILL.md` files in the listed directories, parses frontmatter, and injects available skill names and descriptions into the system prompt. Later sources override earlier ones for skills with the same name (last-wins).

#### `.deepagents/agents/` — Project-Local Subagent Configs

The CLI's `agent.py` loads project-local subagent definitions from `.deepagents/agents/`. Each subfolder defines a named subagent with a system prompt file and optional config.

### Surface 4 — Custom Middleware

Any class extending `AgentMiddleware` can be passed in the `middleware` parameter:

```python
class MyMiddleware(AgentMiddleware):
    def wrap_tool_call(self, request, handler):
        # pre-processing
        result = handler(request)
        # post-processing
        return result

    async def awrap_tool_call(self, request, handler):
        result = await handler(request)
        return result
```

The CLI uses this pattern internally with `ShellAllowListMiddleware` (validates shell commands without HITL interrupts) and `ConfigurableModelMiddleware` (enables `/model` switching).

## Key Interfaces

| Interface | Location | Purpose |
|---|---|---|
| `create_deep_agent()` | `libs/deepagents/deepagents/graph.py` | Primary SDK customization entry point |
| `AgentMiddleware` | `langchain.agents.middleware.types` | Base class for all middleware |
| `SubAgent` | `libs/deepagents/deepagents/middleware/subagents.py` | TypedDict for declarative sync subagents |
| `AsyncSubAgent` | `libs/deepagents/deepagents/middleware/async_subagents.py` | TypedDict for remote async subagents |
| `BackendProtocol` | `libs/deepagents/deepagents/backends/protocol.py` | Interface for file storage and execution |
| `InterruptOnConfig` | `langchain.agents.middleware` | Per-tool HITL configuration |
| `DEFAULT_CONFIG_PATH` | `libs/cli/deepagents_cli/model_config.py` | `~/.deepagents/config.toml` path constant |

## See Also

- [Batteries Included Agent Architecture](../concepts/batteries-included-agent-architecture.md)
- [Filesystem-First Agent Configuration](../concepts/filesystem-first-agent-configuration.md)
- [Graph Factory](../entities/graph-factory.md)
- [SDK to CLI Composition](sdk-to-cli-composition.md)
- [Skills System](../entities/skills-system.md)
- [Memory System](../entities/memory-system.md)
- [Remote Subagent and Sandbox Flow](remote-subagent-and-sandbox-flow.md)
