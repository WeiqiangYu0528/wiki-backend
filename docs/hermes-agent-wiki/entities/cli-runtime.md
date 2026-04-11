# CLI Runtime

## Overview

The CLI is Hermes's local shell and its main process entrypoint. That sounds simple, but `hermes_cli/main.py` does more than launch a chat loop. It decides which profile home is active, loads environment state before most of the repo imports, sets up logging, builds the command tree, routes into setup and control-plane commands, and only then hands interactive chat off to the terminal shell in `cli.py`.

That is why this page should be read as an entrypoint page, not a command catalog. The important question is not only "what commands does `hermes` support?" but "what work must happen before a local terminal session can safely become a shared Hermes runtime?"

The short mental model is:

- `hermes_cli/main.py` owns process startup and command dispatch
- `cli.py` owns the local terminal shell and runtime assembly for chat
- [`AIAgent`](agent-loop-runtime.md) owns the actual model-and-tool turn loop once the shell is ready

If you keep those three layers separate, the CLI stops looking like a giant monolith and starts looking like a deliberately staged handoff.

## What The CLI Runtime Owns

The CLI runtime owns everything needed to turn `hermes ...` into a valid local Hermes process.

It owns:

- early profile and home-directory selection before module imports cache paths
- `.env` loading, centralized file logging, and top-level argparse dispatch
- local-only safety checks such as "this command requires a TTY"
- first-run setup detection and the jump into `hermes setup`
- session resume shortcuts, source tagging, and worktree setup for local runs
- assembly of the terminal shell's config, toolsets, preloaded skills, callbacks, and session identity
- launch of non-chat control surfaces such as setup, config, tools, skills, gateway, cron, ACP, profiles, sessions, and logs

It does not own the provider call loop, tool-call ordering, prompt construction inside a turn, context compression, or fallback recovery after the model is already running. Those belong to [`AIAgent`](agent-loop-runtime.md) and the runtime subsystems around it.

## Startup Sequence

The startup path is intentionally front-loaded. Hermes wants profile-scoped filesystem state to be correct before the rest of the codebase can even import.

1. **Profile override runs before normal imports.** `_apply_profile_override()` scans `sys.argv` for `--profile` or `-p`, falls back to `~/.hermes/active_profile`, resolves the profile path, and sets `HERMES_HOME`. This happens before most Hermes imports because many modules cache profile-aware paths at import time.
2. **Profile-scoped environment is loaded.** `load_hermes_dotenv()` reads the active profile's `.env` first, then uses the repo `.env` only as a development fallback.
3. **File logging is initialized early.** `setup_logging(mode="cli")` runs before command dispatch so chat, setup, gateway control commands, and errors all share the same log pipeline.
4. **The command tree is built.** `main()` constructs the argparse tree for chat, setup, gateway, cron, config, sessions, ACP, profiles, and the rest of the CLI surfaces. It also discovers plugin-defined CLI commands and adds them to the parser.
5. **Arguments are normalized and parsed.** `_coalesce_session_name_args()` fixes unquoted multi-word session names for `--resume` and `--continue`, then argparse resolves the target command.
6. **The CLI chooses its surface.** No subcommand means "enter chat." Top-level `--resume` and `--continue` are also treated as chat shortcuts. Other parsed commands dispatch into setup, gateway management, cron, logs, profiles, and similar surfaces.
7. **Interactive chat gets one more preflight.** `cmd_chat()` resolves "continue latest" into a concrete session ID, checks whether any inference provider is configured, offers to run setup on first use, starts update and bundled-skill background checks, and then hands control to `cli.main()`.

This sequence matters because a local shell mistake at the start, especially the wrong `HERMES_HOME`, would poison config, logs, sessions, and tool visibility for the entire process.

## How The CLI Assembles A Chat Runtime

Once `cmd_chat()` decides the user really wants a terminal conversation, the CLI starts building the local shell that will eventually host `AIAgent`.

### Config And Profile Assembly

The first assembly step is filesystem identity. `hermes_cli/main.py` has already selected the active profile, so `cli.py` can safely load `config.yaml`, `.env`, and other profile-scoped files through helpers that assume `HERMES_HOME` is stable.

Inside `HermesCLI.__init__()`, the shell derives:

- the default model and requested provider from config
- display settings such as streaming, inline diffs, and status-bar behavior
- fallback-provider configuration
- agent settings such as max turns, reasoning effort, and ephemeral prefill messages
- session identity, including resume-vs-new-session behavior
- a `SessionDB` handle for local session continuity

This is a good example of the CLI's boundary. The shell decides what local state a run should start with, but it still has not started the model loop.

### Provider And Runtime Assembly

Provider setup is split on purpose.

`hermes_cli/main.py` does a coarse first-run check through `_has_any_provider_configured()`. That function answers a simple question: "is Hermes configured enough that entering chat makes sense?" It looks at env vars, `.env`, persisted config, OAuth auth state, and provider-specific credential stores.

The real runtime resolution happens later in `cli.py`. `HermesCLI._ensure_runtime_credentials()` calls `runtime_provider.resolve_runtime_provider()` and turns the requested provider into a concrete runtime bundle:

- resolved provider name
- API mode
- base URL
- API key or external-process credential path
- optional credential-pool information
- ACP command and args when the provider needs them

That deferred resolution is deliberate. It lets the shell pick up token refreshes, key rotation, or provider changes without requiring a full CLI restart.

### Tool, Skill, And Session Assembly

Before `AIAgent` exists, the CLI still has to decide what local capability surface the session should start with.

`cli.main()` resolves toolsets from the platform defaults in `hermes_cli.tools_config._get_platform_tools()`. That means the CLI starts from the configured tool policy for the `cli` platform, including MCP-expanded toolsets, and only then applies user overrides from `--toolsets`.

Preloaded skills are handled in a similarly shell-owned way. `build_preloaded_skills_prompt()` turns `--skills` into prompt text before the agent is created, and `cli.py` appends that text to the shell's ephemeral system prompt rather than mutating persisted session history.

The shell also chooses the local session context:

- resume an existing SQLite-backed session
- create a new session ID
- optionally create an isolated git worktree
- optionally tag the session source through `HERMES_SESSION_SOURCE`
- optionally enable YOLO mode for local approval behavior

All of that is still preparation. It changes the conditions under which the loop will run, but not the loop itself.

## Setup Flow Lives In The CLI

`hermes setup` is part of the CLI runtime because setup is fundamentally about preparing local state, not about running a conversation.

`cmd_setup()` enforces an interactive terminal and calls `run_setup_wizard()` in `hermes_cli/setup.py`. From there the setup flow branches in a few important ways.

| Setup path | What it does | Why it belongs to the CLI |
| --- | --- | --- |
| Section-specific setup | `hermes setup model`, `terminal`, `gateway`, `tools`, or `agent` runs one bounded configuration flow | These commands edit profile-scoped config and secrets, not conversation state |
| First-time quick setup | Chooses provider and model, applies default agent and terminal settings, optionally configures messaging, then offers to launch chat | The goal is to make the local install usable before the user ever reaches `AIAgent` |
| Full setup | Walks model/provider, terminal backend, agent settings, gateway settings, and tool configuration in order | This is effectively the CLI's "prepare the runtime root" workflow |
| Returning-user quick setup | Detects missing or outdated config and only fills the gaps | The shell owns upgrade and migration ergonomics for local installs |

The setup wizard also handles migration-era concerns such as OpenClaw import, non-interactive environment guidance, and the final "launch chat now?" handoff. That reinforces the main boundary: setup prepares the filesystem, credentials, and config surface that later runs will consume.

## Shared Command Surface, Local Presentation

The CLI is also the place where Hermes defines a shared slash-command vocabulary.

`hermes_cli/commands.py` exposes `COMMAND_REGISTRY`, and the module explicitly treats that registry as the single source of truth for:

- CLI help
- autocomplete
- gateway command dispatch
- Telegram and Slack command mappings
- plugin-added commands

That is an important architectural choice. The CLI owns the local presentation of commands, but command identity itself is shared across shells. In other words, the terminal shell is not inventing its own private command language. It is one consumer of a broader command registry.

## Where CLI Ownership Stops And `AIAgent` Ownership Begins

The handoff becomes concrete inside `HermesCLI._init_agent()`.

After the shell resolves credentials, restores or opens the session, validates resumed history, and finalizes toolsets and callbacks, `_init_agent()` instantiates `AIAgent` with:

- resolved provider runtime details
- enabled toolsets
- the session ID and `SessionDB`
- fallback-provider configuration
- local callbacks for clarify, reasoning, streaming, and tool progress
- the shell-owned ephemeral system prompt and prefill messages

That constructor call is the ownership boundary.

| Owner | Owns | Stops before |
| --- | --- | --- |
| `hermes_cli/main.py` | profile selection, env loading, logging, argparse routing, first-run setup checks, command dispatch | terminal UX, per-session runtime wiring, model execution |
| `cli.py` / `HermesCLI` | terminal UI, session resume, worktree setup, provider resolution, toolset selection, skill preloading, callback wiring, `AIAgent` construction | prompt assembly during the turn, provider call loop, tool execution loop, compression, fallback |
| [`AIAgent`](agent-loop-runtime.md) | model calls, tool-call loop, prompt build/rebuild, retries, fallback, compression, per-turn persistence | shell-specific transport, terminal rendering, top-level command parsing |

The practical rule is simple: once the shell calls `run_conversation()`, the CLI stops deciding how the turn executes. It can render progress, collect clarify answers, or show tool output, but it does not own the loop's internal sequencing anymore.

## Source Files

| File | Why it matters for this page |
| --- | --- |
| `hermes-agent/hermes_cli/main.py` | Top-level `hermes` entrypoint: early profile override, `.env` loading, logging, argparse dispatch, first-run setup checks, and chat handoff. |
| `hermes-agent/cli.py` | Local terminal shell: session setup, worktree isolation, provider resolution, toolset and skill assembly, resume handling, and `AIAgent` instantiation. |
| `hermes-agent/hermes_cli/setup.py` | Interactive setup wizard, first-time quick setup, returning-user repair flows, and section-specific configuration commands. |
| `hermes-agent/hermes_cli/commands.py` | Shared slash-command registry used by the CLI, gateway help, autocomplete, and plugin command registration. |
| `hermes-agent/hermes_cli/runtime_provider.py` | Shared provider resolver that turns config and credentials into the concrete runtime bundle used by CLI, gateway, cron, and helpers. |
| `hermes-agent/hermes_cli/config.py` | Profile-scoped config and env helpers used by startup, setup, and runtime assembly. |

## See Also

- [Architecture Overview](../summaries/architecture-overview.md)
- [Config and Profile System](config-and-profile-system.md)
- [Agent Loop Runtime](agent-loop-runtime.md)
- [Provider Runtime](provider-runtime.md)
- [Session Storage](session-storage.md)
- [CLI To Agent Loop Composition](../syntheses/cli-to-agent-loop-composition.md)
