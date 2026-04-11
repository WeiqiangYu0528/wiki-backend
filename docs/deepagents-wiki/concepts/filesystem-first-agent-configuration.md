# Filesystem-First Agent Configuration

## Overview

Deep Agents treats the filesystem as its primary configuration and context surface. Rather than loading configuration from environment variables alone or requiring upfront data injection, agents read, write, and search files the same way a human developer would. This design makes agents portable across local shells, remote sandboxes, and containerized environments without code changes, because the filesystem abstraction is backend-independent.

The key runtime guarantee: every middleware that reads configuration, memory, or skills does so through the backend abstraction layer, so the same agent graph works identically whether the backend is an in-process `StateBackend`, a local `FilesystemBackend`, or a remote sandbox.

## Mechanism

### Built-in Filesystem Tools

`FilesystemMiddleware` (defined in `libs/deepagents/deepagents/middleware/filesystem.py`) injects six core tools into every agent:

| Tool | Input Schema | Purpose |
|---|---|---|
| `ls` | `LsSchema(path: str)` | List directory contents; recommended before any read or edit |
| `read_file` | `ReadFileSchema(file_path, offset, limit)` | Paginated file read; defaults to 100 lines per call |
| `write_file` | `WriteFileSchema(file_path, content)` | Create a new file with text content |
| `edit_file` | `EditFileSchema(file_path, old_string, new_string, replace_all)` | Exact-string replacement; `old_string` must be unique unless `replace_all=True` |
| `glob` | `GlobSchema(pattern, path)` | Find files matching a glob pattern (e.g., `**/*.py`) |
| `grep` | `GrepSchema(pattern, path, glob, output_mode)` | Literal-string search; output modes: `files_with_matches`, `content`, `count` |

A seventh tool, `execute`, is conditionally registered when the backend implements `SandboxBackendProtocol`, allowing arbitrary shell commands.

Tool descriptions are injected into the system prompt to teach the model filesystem discipline: always call `ls` before `read_file` or `edit_file`, use only absolute paths, prefer `edit_file` over full rewrites, and avoid shell `cat`/`find`/`grep` in favor of the dedicated tools.

### FilesystemMiddleware Class and State

`FilesystemMiddleware` extends `AgentMiddleware` and manages a `FilesystemState` class (itself extending `AgentState`) that carries a `files` field:

```python
class FilesystemState(AgentState):
    files: Annotated[NotRequired[dict[str, FileData]], _file_data_reducer]
```

The `_file_data_reducer` merges file updates and supports deletion markers: setting a key to `None` removes the file from LangGraph state without leaving stale entries.

Key constants governing tool behavior:

```python
GLOB_TIMEOUT = 20.0          # seconds before glob aborts
DEFAULT_READ_OFFSET = 0      # start of file
DEFAULT_READ_LIMIT = 100     # lines per read_file call
_EDIT_INLINE_MAX_BYTES = 50_000  # threshold for inline vs. upload-based edit
```

For `edit_file` payloads under 50 KB the middleware runs a server-side Python script inline via `execute()`. Larger payloads fall back to uploading old/new strings as temp files and running a replacement script on the sandbox. This keeps the operation efficient regardless of file size.

### The `.deepagents/` Directory Convention

By convention, project-level agent configuration lives under `.deepagents/` in the working directory:

```
.deepagents/
  agents/          # per-agent system prompts and configs
  skills/          # SKILL.md files for reusable capabilities
  config.toml      # project-level CLI settings (optional)
AGENTS.md          # memory file injected into the agent system prompt
```

The `memory` parameter of `create_deep_agent()` accepts backend-relative paths such as `["/memory/AGENTS.md"]`. Those files are read at agent startup and injected verbatim into the system prompt, making persistent instructions a filesystem artifact rather than a hard-coded string. Display names are derived automatically from paths.

### Local Context Detection via `local_context.py`

`LocalContextMiddleware` (in `libs/cli/deepagents_cli/local_context.py`) runs a bash detection script inside the backend at session startup. The script is assembled from section functions:

- `_section_header()` — prints the current directory, sets `CWD` and `IN_GIT` flags
- `_section_project()` — detects language (`python`, `javascript/typescript`), virtualenv, monorepo markers

Each section checks for tool availability with `command -v` guards before use, so detection silently degrades when tools like `git`, `python3`, or `node` are absent. Independent sections run as parallel background subshells for speed. The assembled result is injected as a `## Local Context` markdown block at the top of the agent system prompt.

The middleware accepts two backend protocols:

- `_ExecutableBackend` — runtime-checkable protocol with a sync `execute(command, *, timeout) -> ExecuteResponse`
- `_AsyncExecutableBackend` — protocol with an async `aexecute(command, *, timeout)`

The detection script has a hard timeout of 30 seconds (`_DETECT_SCRIPT_TIMEOUT = 30`). MCP server metadata is separately formatted by `_build_mcp_context()` and appended to the same section, showing connected server names, transports, and tool lists (capped at 10 tool names per server via `_TOOL_NAME_DISPLAY_LIMIT = 10`).

## Involved Entities

- [`FilesystemMiddleware`](../entities/filesystem-middleware.md) — registers all filesystem tools and manages `FilesystemState`
- [`LocalContextMiddleware`](../entities/local-context-middleware.md) — detects and injects project context at session startup
- [`CompositeBackend`](../entities/composite-backend.md) — routes filesystem operations to the correct backend by path prefix
- [`create_deep_agent()`](../entities/graph-factory.md) — wires `FilesystemMiddleware` into the default middleware stack

## Source Evidence

`libs/deepagents/deepagents/middleware/filesystem.py`, lines 115–178 — `FilesystemState` class and all six tool input schemas (`LsSchema`, `ReadFileSchema`, `WriteFileSchema`, `EditFileSchema`, `GlobSchema`, `GrepSchema`) with their field descriptions.

`libs/deepagents/deepagents/middleware/filesystem.py`, lines 190–298 — full tool description strings (`LIST_FILES_TOOL_DESCRIPTION`, `READ_FILE_TOOL_DESCRIPTION`, `EDIT_FILE_TOOL_DESCRIPTION`, `GLOB_TOOL_DESCRIPTION`, `GREP_TOOL_DESCRIPTION`, `EXECUTE_TOOL_DESCRIPTION`).

`libs/cli/deepagents_cli/local_context.py`, lines 120–150 — `_section_header()` and `_section_project()` bash snippet builders that compose the environment detection script.

`libs/deepagents/deepagents/graph.py`, lines 226–232 — `FilesystemMiddleware(backend=backend)` added as the second item in the default middleware stack inside `create_deep_agent()`.

## See Also

- [Monorepo Package Layering](monorepo-package-layering.md)
- [SDK to CLI Composition](../syntheses/sdk-to-cli-composition.md)
- [Remote Subagent and Sandbox Flow](../syntheses/remote-subagent-and-sandbox-flow.md)
- [Agent Customization Surface](../syntheses/agent-customization-surface.md)
- [Skills System](../entities/skills-system.md)
- [Memory System](../entities/memory-system.md)
