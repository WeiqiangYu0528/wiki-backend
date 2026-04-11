# CLI Runtime

## Overview

The CLI is a full Textual-based terminal UI agent that wraps the SDK's `create_deep_agent()` function with a rich set of production features: streaming responses, human-in-the-loop (HITL) tool approval, MCP tool loading, web search via Tavily, remote sandbox execution, persistent memory, custom skills, and session history with thread resumption.

The entry point (`main.py`) handles argument parsing, dependency checking, and launch mode selection. The agent construction (`agent.py`) wires `create_deep_agent()` with all CLI-specific middleware. The Textual application (`app.py`) implements the interactive TUI. The configuration layer (`config.py`) resolves settings from environment variables, `.env` files, and `~/.deepagents/config.toml`.

---

## Key Concepts

### CLI Entry Point (`main.py`)

`main.py` is the module-level entry point for the `deepagents` command. It:

1. **Checks dependencies** via `check_cli_dependencies()` — verifies that `requests`, `python-dotenv`, `tavily-python`, and `textual` are installed; exits with an install hint if any are missing.
2. **Checks optional tools** via `check_optional_tools()` — warns when `ripgrep` (`rg`) is not installed, since the grep tool falls back to a slower implementation without it.
3. **Parses arguments** via `parse_args()` — uses `argparse` with subcommands for `help`, `agents`, `skills`, `threads`, and `update`, plus a rich set of flags for the default interactive mode.

Key CLI flags for the default interactive/non-interactive mode:

| Flag | Description |
|---|---|
| `-a` / `--agent NAME` | Agent configuration to use (default: `agent`) |
| `-M` / `--model MODEL` | Model to use (provider auto-detected from name) |
| `--model-params JSON` | Extra model kwargs as a JSON object |
| `-r` / `--resume [ID]` | Resume most-recent thread or a specific thread by ID |
| `-m` / `--message TEXT` | Initial prompt to auto-submit when session starts |
| `-n` / `--non-interactive TEXT` | Run a single task non-interactively and exit |
| `-q` / `--quiet` | Clean stdout-only output for piping (requires `-n` or piped stdin) |
| `--no-stream` | Buffer full response before writing to stdout (requires `-n` or piped stdin) |
| `--stdin` | Explicitly read input from stdin |
| `-y` / `--auto-approve` | Auto-approve all tool calls without HITL prompts |
| `--sandbox TYPE` | Remote sandbox backend (`none`, `agentcore`, `modal`, `daytona`, `runloop`, `langsmith`) |
| `--sandbox-id ID` | Reuse an existing sandbox by ID |
| `--sandbox-setup PATH` | Path to a setup script to run in the sandbox after creation |
| `-S` / `--shell-allow-list LIST` | Comma-separated shell commands to auto-approve, `recommended`, or `all` |
| `--mcp-config PATH` | Explicit MCP servers JSON config (merged on top of auto-discovered configs) |
| `--no-mcp` | Disable all MCP tool loading |
| `--trust-project-mcp` | Trust project-level MCP stdio servers without the approval prompt |
| `--output json` | Emit structured JSON output (for non-interactive scripted use) |

**Subcommands**:

- `deepagents agents list` / `deepagents agents reset` — manage agent configurations
- `deepagents skills create` / `deepagents skills list` — manage skills on the filesystem
- `deepagents threads list` / `deepagents threads delete` — manage session history
- `deepagents update` — check for and install CLI updates

### `agent.py` — Agent Construction and Wiring

`agent.py` contains `create_deep_agent()` call-site logic plus CLI-specific middleware. The key types defined here:

**`ShellAllowListMiddleware`** — an `AgentMiddleware` that validates shell commands against a configured allow-list *without* HITL interrupts. Rejected commands are returned as error `ToolMessage` objects so the LangGraph trace stays as a single continuous run. Used in non-interactive mode to avoid the interrupt/resume cycle that would fragment LangSmith traces.

**`load_async_subagents()`** — reads `[async_subagents]` from `~/.deepagents/config.toml` and returns `AsyncSubAgent` specs for remote LangGraph deployments, each with `name`, `description`, `graph_id`, and optional `url`/`headers`.

**`list_agents()` / `reset_agent()`** — agent management utilities for the `deepagents agents` subcommand.

The agent is assembled by calling `create_deep_agent()` (from `deepagents`) and adding middleware in order:

- `MemoryMiddleware` — loads `AGENTS.md` persistent memory
- `SkillsMiddleware` — loads and injects skills
- `LocalContextMiddleware` — adds local project context (git status, CWD)
- `ConfigurableModelMiddleware` — enables in-session model switching via `/model`
- `ShellAllowListMiddleware` — (non-interactive mode only) validates shell commands

Key imports in `agent.py`:

```python
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, LocalShellBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware import MemoryMiddleware, SkillsMiddleware
```

### `app.py` — Textual `App` Class

`app.py` implements `DeepAgentsApp`, a subclass of `textual.app.App`. It is the main interactive TUI.

**Key class attributes:**

```python
class DeepAgentsApp(App):
    TITLE = "Deep Agents"
    CSS_PATH = "app.tcss"              # Textual CSS for layout
    ENABLE_COMMAND_PALETTE = False     # Custom slash-command system used instead
    SCROLL_SENSITIVITY_Y = 1.0
```

**Key bindings:**

| Key | Action |
|---|---|
| `Escape` | Interrupt current agent run |
| `Ctrl+C` | Quit or interrupt |
| `Ctrl+D` | Quit app |
| `Ctrl+T` / `Shift+Tab` | Toggle auto-approve |

**Widget composition** (from `compose()`):

```
DeepAgentsApp
└─ VerticalScroll#chat
│    ├─ WelcomeBanner#welcome-banner  (thread ID, MCP count, connection state)
│    └─ Container#messages            (message widgets appended here)
└─ Container#bottom-app-container
│    └─ ChatInput#input-area          (prompt input + image tracker)
└─ StatusBar#status-bar              (CWD, git branch, token count, model name)
```

**Message widget types** (from `widgets/messages.py`):

- `UserMessage` — displayed user input
- `AssistantMessage` — streamed model response
- `ToolCallMessage` — tool call with approval controls
- `SkillMessage` — skill invocation indicator
- `ErrorMessage` — error display
- `QueuedUserMessage` — messages waiting while the agent is busy
- `AppMessage` — system/informational messages

**Session state** is tracked in `TextualSessionState`:
- `auto_approve: bool` — whether to skip HITL for tool calls
- `thread_id: str` — UUID7 session identifier; reset by `reset_thread()`

**Deferred actions** (`DeferredAction`) handle model switching, thread switching, and chat output that must wait until the app is idle. The `_defer_action` callback mechanism ensures commands with `BypassTier.IMMEDIATE_UI` can open modal UI immediately while real work queues until the agent finishes.

**Input modes** (from `config.py`):

| Mode | Trigger | Display |
|---|---|---|
| `normal` | Default | (no prefix) |
| `shell` | `!` prefix | `$` glyph |
| `command` | `/` prefix | `/` glyph |

### `config.py` — Configuration Schema and Providers

`config.py` is the central configuration module. It uses a lazy bootstrap pattern: dotenv loading, project detection, and `LANGSMITH_PROJECT` override are deferred until `settings` is first accessed, avoiding disk I/O during `deepagents --help`.

**`Settings` dataclass** — initialized once at startup via `Settings.from_environment()`:

| Field | Description |
|---|---|
| `openai_api_key` | OpenAI API key (or `None`) |
| `anthropic_api_key` | Anthropic API key (or `None`) |
| `google_api_key` | Google API key (or `None`) |
| `nvidia_api_key` | NVIDIA API key (or `None`) |
| `tavily_api_key` | Tavily API key for web search (or `None`) |
| `google_cloud_project` | GCP project ID for VertexAI |
| `deepagents_langchain_project` | LangSmith project for agent traces |
| `user_langchain_project` | Original `LANGSMITH_PROJECT` before CLI override |
| `model_name` | Active model name |
| `model_provider` | Provider identifier (`openai`, `anthropic`, `google_genai`, etc.) |
| `model_context_limit` | Max input tokens from model profile |
| `project_root` | Current git project root, or `None` |
| `shell_allow_list` | Shell commands that don't require approval |
| `extra_skills_dirs` | Additional paths allowed for skill symlink targets |

**`CharsetMode`** — `StrEnum` with values `UNICODE`, `ASCII`, `AUTO` controlling whether the TUI uses Unicode glyphs (`⏺`, `✓`, `…`) or ASCII fallbacks (`(*)`, `[OK]`, `...`).

**`Glyphs` dataclass** — the full set of display characters (`tool_prefix`, `ellipsis`, `checkmark`, `error`, spinner frames, box-drawing chars, etc.) resolved once and cached in `_glyphs_cache`.

### Launch Modes

**Interactive TUI** (default when no `-n` flag and stdin is a TTY):
- Launches `DeepAgentsApp` via Textual's event loop
- Full widget UI with streaming responses, approval widgets, slash commands, and thread history
- Model switching and theme switching available mid-session via `/model` and `/theme`

**Non-interactive / scripted** (triggered by `-n TEXT`, `-q`, `--no-stream`, or piped stdin):
- Runs the agent once against a single prompt and exits
- `ShellAllowListMiddleware` replaces HITL shell approval (no interactive prompts)
- With `-q`: only agent response text goes to stdout
- With `--no-stream`: full response buffered then written at once
- With `--output json`: structured JSON lines to stdout
- Shell access is disabled by default in non-interactive mode unless `--shell-allow-list` is set

---

## Architecture

### TUI Widget Hierarchy

```
DeepAgentsApp (textual.app.App)
├─ VerticalScroll#chat
│   ├─ WelcomeBanner          — thread ID, MCP server count, connection state
│   └─ Container#messages     — scrollable message list
│       ├─ UserMessage        — submitted user messages
│       ├─ AssistantMessage   — streaming model output
│       ├─ ToolCallMessage    — tool call + HITL approval widget
│       ├─ SkillMessage       — skill invocation indicator
│       ├─ ErrorMessage       — error display
│       └─ QueuedUserMessage  — queued input while agent is busy
├─ Container#bottom-app-container
│   └─ ChatInput              — multiline prompt input, image attachment tracker
└─ StatusBar                  — CWD, git branch, token usage, model name, auto-approve indicator
```

Modal overlays (pushed as screens):
- `ApprovalMenu` — HITL tool call approval
- `AskUserMenu` — agent-initiated clarifying questions
- Model picker and thread browser (opened by `BypassTier.IMMEDIATE_UI` commands)

### How the SDK Agent is Embedded in the Textual App

The `DeepAgentsApp` holds a reference to the compiled LangGraph agent (a `Pregel` instance for local mode, or a `RemoteAgent` for server mode). Message processing runs in a Textual `Worker` so the async event loop stays responsive. Streaming tokens from the agent are posted as Textual messages to `AssistantMessage` widgets. Tool calls trigger either `ApprovalMenu` (HITL) or pass through automatically (auto-approve or allow-list mode).

The `TextualUIAdapter` bridges the LangGraph streaming output format to Textual's message-posting API, translating LangChain events into `MessageData` objects stored in `MessageStore`.

For server mode, `DeepAgentsApp` spawns a `ServerProcess` (a local LangGraph server) and connects to it via `RemoteAgent`. The `_is_remote_agent` property gates features like in-session model switching that require a server-backed agent.

### Configuration Resolution

Environment variables and config files are resolved in this precedence order (later entries win):

```
~/.deepagents/.env         (global user dotenv — lowest precedence)
<project>/.env             (project dotenv — higher than global)
Shell environment          (exported env vars — highest dotenv precedence)
~/.deepagents/config.toml  (TOML config file for structured settings)
CLI flags / --model-params (command-line arguments — highest precedence)
```

The `DEEPAGENTS_CLI_` prefix on any environment variable (e.g., `DEEPAGENTS_CLI_ANTHROPIC_API_KEY`) takes precedence over the unprefixed form, allowing CLI credentials to be scoped independently from shell exports. The bootstrap function `_ensure_bootstrap()` in `config.py` handles dotenv loading, LangSmith project override (`LANGSMITH_PROJECT`), and propagation of prefixed LangSmith vars to the canonical names read by the LangSmith SDK.

The config file at `~/.deepagents/config.toml` supports:
- `[ui]` — `theme` name
- `[warnings]` — `suppress` list (e.g., `["ripgrep"]`)
- `[async_subagents.*]` — remote LangGraph subagent definitions
- `[skills]` — `extra_allowed_dirs` for skill symlink path containment

---

## Source Files

- `libs/cli/deepagents_cli/main.py` — entry point, `parse_args()`, `check_cli_dependencies()`, `check_optional_tools()`, launch mode selection
- `libs/cli/deepagents_cli/agent.py` — `ShellAllowListMiddleware`, `load_async_subagents()`, `list_agents()`, `reset_agent()`, agent construction
- `libs/cli/deepagents_cli/app.py` — `DeepAgentsApp`, `TextualSessionState`, `DeepAgentsApp.compose()`, all widget wiring and input handling
- `libs/cli/deepagents_cli/config.py` — `Settings`, `CharsetMode`, `Glyphs`, `_ensure_bootstrap()`, dotenv loading, `MODE_PREFIXES`

---

## See Also

- [Skills System](./skills-system.md) — how skills are discovered and injected; the `/skill:*` slash commands
- [Memory System](./memory-system.md) — `MemoryMiddleware` and `AGENTS.md` persistent memory loaded at agent startup
- [MCP System](./mcp-system.md) — how MCP servers are discovered, loaded, and surfaced via `/mcp`
- [Session Persistence](./session-persistence.md) — thread storage, checkpoint savers, and the `/threads` browser
- [Sandbox Partners](./sandbox-partners.md) — remote sandbox backends wired via `--sandbox`
- [Subagent System](./subagent-system.md) — async subagents configured via `[async_subagents]` in `config.toml`
