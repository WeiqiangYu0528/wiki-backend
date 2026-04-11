# CLI Textual UI

## Overview

The CLI Textual UI is the interactive terminal interface for deepagents-cli, built on the [Textual](https://github.com/Textualize/textual) framework. The `DeepAgentsApp` class is the root application that composes the full screen layout: a scrollable chat area containing a `WelcomeBanner`, a stream-layout message list, and a bottom `ChatInput` with autocomplete — all framed by a docked `StatusBar`. It renders streaming LLM tokens, tool call results, inline approval menus, and user messages in a single-process async event loop. Focus management, key bindings, and mode switching (normal / shell / command) are handled at the application level, while individual widgets carry their own embedded Textual CSS rules. The app bridges LangGraph's streaming output to Textual's message bus via `TextualUIAdapter`, enabling token-by-token display without blocking the UI.

## Key Types / Key Concepts

```python
class DeepAgentsApp(App):
    """Root Textual application."""
    CSS_PATH = "app.tcss"
    ENABLE_COMMAND_PALETTE = False   # Custom slash-command system used instead
    BINDINGS: ClassVar[list[BindingType]]  # escape, ctrl+c/d/t/o/x, approval keys

class StatusBar(Horizontal):
    """Bottom-docked bar: mode badge, auto-approve pill, cwd, git branch, tokens, model."""
    mode: reactive[str]            # "normal" | "shell" | "command"
    auto_approve: reactive[bool]
    cwd: reactive[str]
    branch: reactive[str]
    tokens: reactive[int]

class ModelLabel(Widget):
    """Right-aligned model name with smart truncation (drops provider prefix when narrow)."""
    provider: reactive[str]
    model: reactive[str]

class WelcomeBanner(Static):
    """Startup banner: ASCII art, version, thread ID, LangSmith link, MCP count, tip."""

class ChatInput(Vertical):
    """Multi-line TextArea with slash-command autocomplete and JSONL history."""

InputMode = Literal["normal", "shell", "command"]

@dataclass(frozen=True, slots=True)
class QueuedMessage:
    text: str
    mode: InputMode

@dataclass(frozen=True, slots=True, kw_only=True)
class DeferredAction:
    kind: DeferredActionKind   # "model_switch" | "thread_switch" | "chat_output"
    execute: Callable[[], Awaitable[None]]
```

Message widget types (from `widgets/messages.py`):
- `UserMessage` / `QueuedUserMessage` — outgoing user turns
- `AssistantMessage` — streaming assistant reply via Textual's `MarkdownStream`
- `ToolCallMessage` — tool invocation with collapsible diff/output
- `AppMessage` — system-level notices (model switch, thread reset)
- `SkillMessage` — skill invocation notice
- `ErrorMessage` — error display with styled text

## Architecture

**Screen layout** (`app.tcss`): The `Screen` uses `layout: vertical` with two CSS layers (`base` and `autocomplete` for z-ordering). The main scrollable area (`#chat`, `height: 1fr`) holds `#welcome-banner` followed by `#messages`, which uses `layout: stream` — Textual's O(1) incremental-placement layout — to avoid full reflow as the conversation grows. Below the scroll sits `#bottom-app-container` housing `ChatInput` (`min-height: 3`, `max-height: 25`). The `StatusBar` is `dock: bottom` and always 1 terminal row tall.

**Startup sequence**: `DeepAgentsApp.on_mount` fires a background Textual worker that starts the LangGraph server process and MCP connections; on success it posts a `ServerReady` message containing the compiled agent graph. While connecting, `WelcomeBanner` shows a "Connecting to local server..." footer. `set_connected(mcp_tool_count)` transitions it to the ready state with a rotating tip.

**Key bindings**:
| Key | Action |
|-----|--------|
| `Escape` | Interrupt current agent run |
| `Ctrl+C` | Quit or interrupt (context-sensitive) |
| `Ctrl+D` | Quit |
| `Shift+Tab` / `Ctrl+T` | Toggle auto-approve mode |
| `Ctrl+O` | Toggle tool output visibility |
| `Ctrl+X` | Open `$EDITOR` for multi-line prompt composition |
| `y/1`, `a/2`, `n/3`, arrow/`j`/`k` | Approval menu navigation |

**Streaming tokens**: `TextualUIAdapter` bridges LangGraph's async streaming loop to Textual's message bus. Each token chunk posts a Textual message that `AssistantMessage` uses to update a `MarkdownStream` widget progressively. The `StatusBar` hides the token counter during streaming (`hide_tokens()`) and restores it via `set_tokens(count, approximate=...)` when the final usage arrives. When generation is interrupted before the model reports usage, the count is shown with a `+` suffix to flag it as approximate.

**Approval flow**: When a tool call requires user approval, an `ApprovalMenu` is inserted inline into the message list. A deferred-approval worker waits up to `_TYPING_IDLE_THRESHOLD_SECONDS` (2 s) of keyboard idle time — or `_DEFERRED_APPROVAL_TIMEOUT_SECONDS` (30 s) absolute — before showing the menu, so mid-sentence keystrokes do not accidentally dismiss it. A placeholder widget is shown while waiting.

**`ChatInput` internals**: Built on Textual's `TextArea`, it uses a `MultiCompletionManager` backed by two controllers: `SlashCommandController` for `/` slash commands and `FuzzyFileController` for `@`-prefixed file references. History persists to `~/.deepagents/history.jsonl`. Paste-burst detection uses inter-keystroke timing (`_PASTE_BURST_CHAR_GAP_SECONDS = 0.03 s`) to distinguish terminal paste events from normal typing. Some terminals send `\` + `Enter` for Shift+Enter; the code detects this within a `_BACKSLASH_ENTER_GAP_SECONDS` (0.15 s) window and converts it to a newline insertion.

**Theme system**: `theme.py` maintains a `ThemeEntry.REGISTRY` of named themes (e.g. `langchain`, `langchain-light`, `textual-ansi`). The active palette is exposed via `get_theme_colors(widget_or_app)` and used by widgets to build Textual `Style` objects with hex color values. The selected theme is persisted to `~/.deepagents/config.toml` via atomic temp-file replacement.

**iTerm2 workaround**: The module disables iTerm2's cursor-guide highlight at import time via OSC 1337 escape sequences written to stderr, and restores it via `atexit`. This prevents a visual artifact where the cursor-line highlight flickers when Textual takes over the alternate screen buffer.

## Source Files

| File | Purpose |
|------|---------|
| `libs/cli/deepagents_cli/app.py` | `DeepAgentsApp` root class, key bindings, startup sequence, streaming integration, deferred actions |
| `libs/cli/deepagents_cli/app.tcss` | Textual CSS: screen layers, chat/message/input areas, approval menus, scrollbar sizing |
| `libs/cli/deepagents_cli/widgets/chat_input.py` | `ChatInput`: multi-line TextArea, autocomplete, JSONL history, paste-burst and Shift+Enter detection |
| `libs/cli/deepagents_cli/widgets/status.py` | `StatusBar` and `ModelLabel`: mode badges, auto-approve pill, cwd, branch, token count |
| `libs/cli/deepagents_cli/widgets/welcome.py` | `WelcomeBanner`: ASCII art, version, thread ID, LangSmith link, tip rotation, connect/fail states |
| `libs/cli/deepagents_cli/widgets/messages.py` | All message widget types: user, assistant (`MarkdownStream`), tool call, error, app notices |
| `libs/cli/deepagents_cli/widgets/approval.py` | Inline tool-approval menu widget and deferred-approval placeholder |
| `libs/cli/deepagents_cli/widgets/autocomplete.py` | `SlashCommandController`, `FuzzyFileController`, `MultiCompletionManager` |
| `libs/cli/deepagents_cli/widgets/history.py` | JSONL-backed prompt history manager |
| `libs/cli/deepagents_cli/textual_adapter.py` | Bridge between LangGraph streaming events and Textual's message bus |
| `libs/cli/deepagents_cli/theme.py` | Theme registry, `ThemeEntry.REGISTRY`, `get_theme_colors()` |

## See Also

- [CLI Runtime](./cli-runtime.md)
- [MCP System](./mcp-system.md)
- [Session Persistence](./session-persistence.md)
