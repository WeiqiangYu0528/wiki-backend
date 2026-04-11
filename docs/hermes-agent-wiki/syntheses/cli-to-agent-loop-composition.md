# CLI to Agent Loop Composition

## Overview

This page explains how Hermes turns a local `hermes` invocation into one ordinary `AIAgent` turn. The important story is not "the CLI forwards text to the model." The real story is that the CLI bootstraps profile state, config, provider credentials, tool visibility, skills, memory, callbacks, and session identity first, and only then hands control to the shared runtime.

That separation matters because most CLI bugs are really startup bugs. If the wrong profile home is selected, or if the active `.env` is loaded too late, then every later decision is built on the wrong filesystem root. If the wrong toolset or provider is selected, the agent loop still runs, but it runs with the wrong capabilities. So this page should be read as a handoff map: what the CLI prepares, where the shell stops, and what `AIAgent` takes over.

The core pieces are:

- `hermes_cli/main.py` owns process startup, profile override, dotenv loading, logging, argparse routing, and the first chat preflight
- `cli.py` owns the local terminal shell, including session resume, toolset choice, callbacks, prompt adornments, and worktree/session UX
- `AIAgent` in `run_agent.py` owns the actual model-and-tool loop once the shell has prepared its inputs

## Systems Involved

- [CLI Runtime](../entities/cli-runtime.md)
- [Config and Profile System](../entities/config-and-profile-system.md)
- [Provider Runtime](../entities/provider-runtime.md)
- [Agent Loop Runtime](../entities/agent-loop-runtime.md)
- [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md)
- [Prompt Assembly System](../entities/prompt-assembly-system.md)
- [Session Storage](../entities/session-storage.md)

## Interaction Model

### 1. Hermes chooses the active profile before imports settle

`hermes_cli/main.py` runs `_apply_profile_override()` before most Hermes modules are imported. That is not a cosmetic choice. Profile-aware modules cache paths at import time, so the process has to know the active `HERMES_HOME` early.

The startup precedence is:

1. explicit `--profile` or `-p`
2. sticky `~/.hermes/active_profile`
3. preexisting `HERMES_HOME`
4. default home resolution

Once the active profile is known, the CLI loads the profile-scoped `.env` and only uses the repo `.env` as a development fallback. Logging is also initialized at this stage so later chat, setup, and gateway work share one trace.

### 2. Top-level command routing stays in the CLI

The command parser decides whether Hermes is entering chat, running setup, managing gateway or cron state, or invoking one of the other control-plane surfaces. That split is important: command routing is still a CLI responsibility, not an agent-loop responsibility.

For interactive chat, `cmd_chat()` performs one more gate before handing off to the shell:

- it resolves "continue latest" into a concrete session ID
- it checks whether any inference provider is configured
- it offers setup if the install is not ready for chat
- it starts update and bundled-skill checks
- it then enters `cli.main()`

That means the `hermes` binary can still do a lot of work before the first model call, but none of that work is yet the shared agent loop.

### 3. The shell restores or creates session state

Inside `cli.py`, `HermesCLI.__init__()` turns the selected profile into a concrete chat session. It loads the effective config, derives display and agent settings, creates or reuses `SessionDB`, chooses a session ID, and handles resume-vs-new-session behavior.

This is where session continuity is made concrete:

- resumed sessions load conversation history from SQLite
- new sessions get fresh IDs and fresh state
- optional source tagging and git worktree isolation are applied before the turn begins
- prefill messages are loaded as ephemeral priming, not persisted history

The shell also prepares local UX state such as status-bar settings, busy-input behavior, and whether the session should show the full previous conversation or just a compact resume banner.

## Key Interfaces

The cleanest way to understand Hermes is to separate CLI-only work from shared runtime work.

| Stage | CLI-only ownership | Shared runtime ownership |
| --- | --- | --- |
| Profile and env bootstrap | `_apply_profile_override()`, sticky profile resolution, `load_hermes_dotenv()` | none |
| Command selection | argparse dispatch, setup/chat/gateway routing | none |
| Session selection | resume lookup, new-session creation, `SessionDB` lifecycle | session persistence once `AIAgent` is created |
| Provider choice | first-run readiness checks, local provider gating | `resolve_runtime_provider()` and concrete client construction |
| Tool surface | shell-selected platform toolsets, user overrides, preloaded skills prompt text | tool schema execution and dispatch during the turn |
| Callbacks and UI | clarify, interrupt, thinking, streaming, approval, and status presentation | model call timing, retries, tool ordering, and turn execution |
| Handoff point | `HermesCLI._init_agent()` / `AIAgent(...)` construction | `AIAgent.run_conversation()` |

The ownership line is simple: the CLI prepares the environment and presentation surface; `AIAgent` runs the conversation.

## What The CLI Assembles Before Handoff

### Config, provider, and profile state

By the time `HermesCLI` starts assembling a chat run, the active profile is already fixed. That lets the shell load config and secret values from the right home directory and derive the default model, provider, display settings, reasoning settings, and fallback policy.

Provider selection is intentionally split across layers. The CLI can answer the question "is any provider usable right now?" but the concrete transport bundle is resolved later. That deferred resolution matters because the runtime may need to account for custom endpoints, credential pools, API mode, or provider-specific auth state before the first turn starts.

### Tools and skills

The shell chooses the initial tool surface from the platform defaults for the CLI and then applies user overrides from `--toolsets`. Skills are handled the same way: `build_preloaded_skills_prompt()` turns the requested skills into prompt text, but the text is still shell-owned and ephemeral. It is attached before the agent is created, not written back into session history.

This is one of the most important boundary decisions in Hermes. Toolset selection and skill preloading are CLI concerns because they shape how the local session starts. Tool execution itself belongs to `AIAgent`.

### Memory, session identity, and local prompts

The shell also prepares the pieces that make a turn feel continuous instead of stateless:

- it restores prior messages when a session is resumed
- it keeps a current session ID available for persistence and tracing
- it can pass a session label into the prompt when requested
- it keeps ephemeral prefill messages separate from persisted transcript state

Those choices frame the turn, but they do not become the turn. They are still setup for the shared runtime.

## Session Restore and Interrupts

Hermes treats a session as something the shell can re-enter, not just a one-shot chat stream.

If the user resumes a prior session, `cli.py` loads the stored messages from SQLite before the new turn starts. If the user opens a fresh session, the shell creates a new ID and clears the old local state. The same shell also exposes `/resume`, `/branch`, `/new`, and `/background` style affordances around the main loop so the user can move between sessions without rebuilding the process.

Interrupt handling is also shell-owned. The terminal UI monitors local input while the agent is working, and if the user types a new message, the shell queues or interrupts the active run depending on the configured busy-input mode. Clarify prompts, approval prompts, and secret capture prompts use the same general pattern: the shell pauses the main loop, asks the user locally, and resumes once the answer is available.

This is the practical dividing line:

- the shell decides how the user can interrupt or answer local prompts
- `AIAgent` decides what to do with that answer once it is received

## Handoff To `AIAgent`

The actual boundary is visible in `HermesCLI._init_agent()`. Once the shell has resolved credentials, selected toolsets, loaded resume history, prepared callbacks, and finalized the session context, it instantiates `AIAgent` with the runtime bundle and the local UI hooks.

The constructor receives the things the loop needs but should not own:

- resolved provider runtime details
- session ID and `SessionDB`
- enabled toolsets
- fallback configuration
- shell callbacks for clarify, reasoning, thinking, streaming, and tool progress
- ephemeral system-prompt additions and prefill messages

After that point, the shared runtime owns the turn.

## One Ordinary Turn

An ordinary chat turn looks like this:

1. The user enters a message in the CLI.
2. The shell gathers the current session state, toolset configuration, callbacks, and provider runtime.
3. `AIAgent.run_conversation()` receives the message and starts the turn loop.
4. The runtime restores or rebuilds the cached system prompt, combines it with ephemeral context, and prepares the model-facing messages.
5. The agent calls the model, streams output if configured, and updates usage and session state.
6. If the model emits tool calls, the loop dispatches them, appends tool results, and continues.
7. If the model finishes cleanly, the loop persists the final turn, fires end-of-turn hooks, and returns control to the shell.

That path is the shared runtime path. The CLI can render progress, accept clarify input, show interrupts, and display tool output, but it does not reimplement the model/tool loop itself.

## Source Evidence

The rewrite above is grounded in these source files:

- `hermes-agent/hermes_cli/main.py` shows early profile override, dotenv loading, logging, command dispatch, provider readiness checks, and the chat preflight
- `hermes-agent/cli.py` shows session restore, prompt prefill, toolset selection, callbacks, interrupt handling, and the `AIAgent(...)` handoff
- `hermes-agent/run_agent.py` shows what happens after the handoff: system-prompt assembly, interrupt-aware model calls, tool execution, fallback, and persistence
- `hermes-agent/hermes_cli/config.py` and `hermes-agent/hermes_cli/env_loader.py` show the profile-scoped config and `.env` loading rules
- `hermes-agent/hermes_cli/runtime_provider.py` and `hermes-agent/hermes_cli/auth.py` show how runtime provider resolution is separated from shell startup

## See Also

- [CLI Runtime](../entities/cli-runtime.md)
- [Config and Profile System](../entities/config-and-profile-system.md)
- [Provider Runtime](../entities/provider-runtime.md)
- [Agent Loop Runtime](../entities/agent-loop-runtime.md)
- [Session Storage](../entities/session-storage.md)
- [Prompt Assembly System](../entities/prompt-assembly-system.md)
- [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md)
