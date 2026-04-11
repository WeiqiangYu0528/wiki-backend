# Memory System

## Overview

`MemoryMiddleware` loads `AGENTS.md` files from the filesystem and injects their content as persistent memory into the agent's system prompt. Unlike skills (which are demand-loaded workflows), memory is always present for the duration of an agent run once configured.

This is the primary mechanism for per-project context: each project can ship an `AGENTS.md` file containing build commands, code conventions, architecture notes, or any other information the agent should always have available — without requiring those instructions to appear in the conversation transcript.

The middleware implements the [agents.md](https://agents.md/) specification.

## Key Types / Key Concepts

### `MemoryMiddleware`

Defined in `libs/deepagents/deepagents/middleware/memory.py`.

Constructor parameters:

| Parameter | Type | Notes |
| --- | --- | --- |
| `backend` | `BackendProtocol | BackendFactory` | Required. Used to read files from the filesystem (or remote backend). A factory function is supported for `StateBackend`. |
| `sources` | `list[str]` | Required. Ordered list of paths to `AGENTS.md` files. Paths are loaded in order; later entries appear after earlier ones in the injected prompt. Tilde (`~`) expansion and relative paths are resolved by the backend. |

### `MemoryState` (AgentState extension)

`MemoryMiddleware` declares a `state_schema = MemoryState` with a single additional field:

```python
memory_contents: NotRequired[Annotated[dict[str, str], PrivateStateAttr]]
```

`memory_contents` maps each source path to its loaded file content. The `PrivateStateAttr` annotation marks it as internal state — it is not included in the final agent state returned to the caller, and it is automatically excluded from sub-agent state so child agents load their own memory independently.

### How AGENTS.md Files Are Discovered

Sources are **explicit paths** passed to `MemoryMiddleware` at construction time. There is no automatic directory walk. Typical usage in the CLI configures two sources:

1. **User-level**: `~/.deepagents/AGENTS.md` — personal preferences and tool credentials that apply across all projects.
2. **Project-level**: `./.deepagents/AGENTS.md` — project-specific context committed alongside the codebase.

The CLI's `create_agent_from_config()` wires these paths based on the resolved user and project config directories. Additional sources can be added for monorepo scenarios (e.g., a workspace-level file).

Missing files are silently skipped (`file_not_found` errors are ignored). Any other backend error raises `ValueError`.

### Memory Format Conventions

`AGENTS.md` files are standard Markdown with no required structure. Common sections include:

- **Project overview**: purpose, tech stack, key dependencies
- **Build and test commands**: exact commands to run tests, lint, build
- **Code style guidelines**: naming conventions, formatting rules
- **Architecture notes**: important patterns, boundaries, gotchas
- **Tool usage hints**: how to use project-specific tools or workflows

The agent is instructed to update these files via `edit_file` when it learns new preferences or receives corrections from the user.

### Memory Injection Format

Loaded content is formatted by `_format_agent_memory()` and wrapped in the `MEMORY_SYSTEM_PROMPT` template:

```
<agent_memory>
{path1}
{content1}

{path2}
{content2}
</agent_memory>

<memory_guidelines>
  ... instructions on when and how to update memory ...
</memory_guidelines>
```

Each source is rendered as its path followed by its content, in declaration order. Sources with no content (empty file or not found) are omitted. If no sources have content, the block reads `(No memory loaded)`.

The `<memory_guidelines>` section instructs the agent to:
- Write back to memory immediately when learning new user preferences, corrections, or required context for tool use.
- Ask the user rather than assuming when context is missing.
- Never store credentials or API keys in memory files.

## Architecture

### Discovery → Loading → Injection Flow

```
Agent run starts
  → MemoryMiddleware.before_agent() (or abefore_agent())
      - skips if memory_contents already in state (idempotent)
      - calls backend.download_files(sources)   # batch read
      - ignores file_not_found; raises on other errors
      - stores {path: content} dict in state as memory_contents
                                (PrivateStateAttr — not exposed externally)

Each model call
  → MemoryMiddleware.wrap_model_call() (or awrap_model_call())
      - calls modify_request(request)
          - reads memory_contents from request.state
          - formats via _format_agent_memory()
          - appends formatted block to system message via append_to_system_message()
      - forwards modified request to model handler
```

Memory is loaded once at `before_agent` and re-injected on every model call within the run. The load is skipped on subsequent turns because `memory_contents` is already in state.

### Multiple Sources and Ordering

When multiple sources are configured:

1. Sources are fetched in a single `download_files()` batch call (or `adownload_files()` for async).
2. Content is assembled in the order sources were declared in the constructor.
3. Each source's path is shown as a header above its content, so the agent knows where each piece of memory came from.
4. Later sources appear after earlier ones — project-level memory appears after user-level memory when the conventional two-source pattern is used.

There is no merging or deduplication of content across sources. All content from all sources is concatenated in order.

### Live Updates

When the agent writes to an `AGENTS.md` file via `edit_file`, the change is not reflected in the current turn's system prompt (memory was already loaded at `before_agent`). The updated content will be present on the next agent run, since `before_agent` only skips the load when `memory_contents` is already in state — a fresh run starts with an empty state.

## Source Files

| File | Purpose |
| --- | --- |
| `libs/deepagents/deepagents/middleware/memory.py` | `MemoryState`, `MemoryMiddleware`, `_format_agent_memory()`, `MEMORY_SYSTEM_PROMPT` |
| `libs/cli/deepagents_cli/local_context.py` | CLI middleware that injects git state and project structure; wired alongside `MemoryMiddleware` in the CLI agent factory |

## See Also

- [Skills System](skills-system.md)
- [Subagent System](subagent-system.md)
- [CLI Runtime](cli-runtime.md)
- [Filesystem First Agent Configuration](../concepts/filesystem-first-agent-configuration.md)
- [Agent Customization Surface](../syntheses/agent-customization-surface.md)
- [Batteries Included Agent Architecture](../concepts/batteries-included-agent-architecture.md)
- [Sdk To Cli Composition](../syntheses/sdk-to-cli-composition.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
