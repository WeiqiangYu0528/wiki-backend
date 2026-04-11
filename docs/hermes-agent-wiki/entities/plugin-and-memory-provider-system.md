# Plugin and Memory Provider System

## Overview

Hermes has two extension systems because it has two different extension problems.

The first problem is broad extensibility. Hermes needs a way for users or packages to add tools, register hooks, and sometimes extend the CLI without patching core files. That is the job of the general plugin system in `hermes_cli/plugins.py`.

The second problem is persistent recall. Hermes also needs a controlled way to attach one external memory backend to the agent loop so cross-session memory and provider-specific recall can participate in turns without turning the whole runtime into an unbounded plugin soup. That is why Hermes has a separate memory-provider family in `plugins/memory/` and `agent/memory_provider.py`.

The easiest mental model is:

- general plugins are broad process extensions
- memory providers are a narrow, agent-memory backend slot

They look similar because both load Python code and both can expose tools. But they are not the same layer, and Hermes treats them differently on purpose.

## Key Interfaces / Key Concepts

| Anchor | Why it matters |
| --- | --- |
| `PluginManager`, `PluginContext`, and `PluginManifest` in `hermes-agent/hermes_cli/plugins.py` | Core of the general plugin system: discovery, import, registration, disabled-plugin handling, and hook invocation. |
| `discover_plugins()` in `hermes-agent/hermes_cli/plugins.py` | Idempotent discovery entry point used when the tool surface is built. |
| `invoke_hook()` in `hermes-agent/hermes_cli/plugins.py` | Main runtime handoff from Hermes core into plugin callbacks. |
| `plugins_command()` and helpers in `hermes-agent/hermes_cli/plugins_cmd.py` | User-facing install/update/remove/list flow for Git-installed general plugins. |
| `MemoryProvider` in `hermes-agent/agent/memory_provider.py` | Contract for external memory backends: availability, initialization, prompt contribution, recall, sync, tools, and shutdown. |
| `discover_memory_providers()`, `load_memory_provider()`, and `discover_plugin_cli_commands()` in `hermes-agent/plugins/memory/__init__.py` | Separate discovery path for repo-bundled memory providers and active-provider-only CLI exposure. |
| `MemoryManager` in `hermes-agent/agent/memory_manager.py` | Orchestrates memory-provider lifecycle and enforces the "at most one external provider" rule. |
| memory config `memory.provider` in Hermes config | Activation switch that selects the one external provider Hermes should wire into the agent runtime. |

## Architecture

The cleanest way to understand this subsystem is to separate extension scope from runtime ownership.

### General plugins

General plugins are open-ended extensions loaded into the Hermes process. They may come from three sources:

- user plugins in `~/.hermes/plugins/<name>/`
- project plugins in `./.hermes/plugins/<name>/` when `HERMES_ENABLE_PROJECT_PLUGINS` is enabled
- pip-installed entry points in the `hermes_agent.plugins` group

Directory-based plugins use a `plugin.yaml` manifest plus an `__init__.py` with `register(ctx)`. Once imported, they can use `PluginContext` to register tools, hooks, CLI commands, or message injection behavior.

If a plugin is loaded successfully, it is running arbitrary Python inside the Hermes process.

### Memory providers

Memory providers are deliberately narrower. They are not discovered from user plugin directories or pip entry points. They live under the repo-bundled `plugins/memory/<name>/` tree, implement the `MemoryProvider` contract, and are activated separately through `memory.provider` config.

They are separated because their job is different. A memory provider is not just "another tool bundle." It can:

- contribute memory-specific prompt text
- prefetch recall context before turns
- sync completed turns after responses
- expose provider-owned memory tools
- react to session end, compression, delegation, and built-in memory writes

That is much closer to core agent behavior than a normal plugin hook.

### Boundary table

| System | Owns | Does not own |
| --- | --- | --- |
| General plugins | Broad process extension: tools, hooks, plugin metadata, optional CLI integration, plugin install/remove flows | Memory-provider lifecycle, memory-provider activation policy, built-in memory semantics |
| Memory-provider family | External memory backend selection, provider lifecycle, memory recall/sync hooks, provider-owned memory tools, active-provider CLI gating | General plugin discovery sources, arbitrary hook extension, Git install/update/remove flow |
| Core Hermes runtime | Agent loop, tool registry, prompt assembly, session storage, provider runtime, and the actual places hooks/providers are called | Packaging third-party plugin code or choosing external memory backends for the user |

The boundary to remember is simple: general plugins extend Hermes broadly, memory providers plug into one specific runtime slot.

## Runtime Behavior

### 1. General plugin discovery happens early, alongside tool discovery

The general plugin system enters the runtime through `model_tools.py`. After built-in tools and MCP tools are discovered, Hermes calls `discover_plugins()`. That means plugin-defined tools can be registered before `get_tool_definitions()` builds the model-visible tool surface.

`PluginManager.discover_and_load()` is idempotent. On first run it scans:

1. `~/.hermes/plugins/`
2. `./.hermes/plugins/` if project plugins are explicitly enabled
3. Python entry points in `hermes_agent.plugins`

For directory plugins, `_scan_directory()` reads `plugin.yaml` metadata into a `PluginManifest`. For pip plugins, `_scan_entry_points()` creates lighter manifests from entry-point metadata.

Then the manager applies an important precedence rule: plugins listed in `config.yaml` under `plugins.disabled` are recorded but skipped. Discovery still sees them, but load is suppressed before import.

"Installed" and "enabled" are different states in Hermes. A plugin can exist on disk and still be intentionally excluded from runtime behavior.

### 2. Loading a general plugin means importing code and calling `register(ctx)`

Once a plugin is selected for loading, `_load_plugin()` imports it and looks for `register(ctx)`.

That registration function is the plugin's moment to declare what it contributes. Through `PluginContext` it can:

- register tools into the central tool registry
- register lifecycle hooks
- register CLI command metadata
- inject messages into a running CLI session

This is not a sandboxed extension model. Hermes imports plugin code directly into process memory and trusts that code to behave. The project-plugin opt-in flag exists because loading code from the current repository is a trust decision, not a harmless convenience feature.

The trust order is therefore:

- user and pip plugins are trusted because the user installed them
- project plugins require explicit opt-in because the current repo may not be trustworthy
- disabled plugins lose to config, even if discovered successfully

### 3. Hooks are the main runtime connection point for general plugins

General plugins matter most at runtime through hooks.

`VALID_HOOKS` includes events around tool calls, LLM calls, API requests, and session start/end. The core runtime calls `invoke_hook()` at the appropriate points, and each callback is isolated behind its own `try/except` so one broken plugin does not crash the whole run.

The most important teaching distinction is that hooks usually observe or lightly augment a run, not replace core ownership.

Examples:

- `pre_tool_call` and `post_tool_call` wrap tool execution
- `pre_api_request` and `post_api_request` observe API traffic
- `on_session_start` and `on_session_end` observe session boundaries
- `pre_llm_call` may return ephemeral context that Hermes appends to the current user message

That last case is where the boundary is clearest. Plugin context returned from `pre_llm_call` is injected into the user-message side of the turn, not into the system prompt. The code comments in `run_agent.py` make the reason explicit: Hermes keeps the system prompt stable for prompt-cache reuse. Plugins may contribute ephemeral context, but they do not own the system prompt.

So plugins can influence what the model sees, but they do not become the prompt assembly system.

### 4. Plugin tools join the normal tool surface instead of forming a parallel registry

`PluginContext.register_tool()` delegates to the central tool registry. That means plugin-defined tools are first-class tools from the model's perspective. They are not handled through a special plugin tool runner.

This is a deliberate design choice. Once registered, plugin tools flow through the same toolset filtering and schema-building path as built-in tools. `get_plugin_toolsets()` even reflects plugin-registered toolsets back into the tool configuration UI so plugin capabilities can sit beside built-in ones.

That keeps the capability model coherent. Hermes still has one tool registry and one tool-definition path. Plugins extend it, but they do not fork it.

### 5. General plugin CLI behavior is split between management and extension metadata

There are two distinct CLI stories here, and they are easy to mix up.

First, `hermes_cli/plugins_cmd.py` owns the management CLI for general plugins:

- install from Git
- update
- remove
- list
- enable
- disable

This is the operational surface for fetching plugin code into `~/.hermes/plugins/`, prompting for manifest-declared env vars during install, copying `.example` files, and showing post-install guidance.

Second, `PluginContext.register_cli_command()` lets a loaded plugin declare CLI command metadata inside the plugin manager. That is an extension surface, not the same thing as the management command. In the current code, the most visible fully wired CLI path is the management command plus the separate memory-provider CLI discovery path; plugin CLI registration exists as part of the general plugin contract, but the page should not treat it as the center of the runtime story.

The runtime center for general plugins is still tools and hooks.

### 6. Memory providers are discovered on a separate path for a reason

Memory providers do not flow through `PluginManager`.

Instead, `plugins/memory/__init__.py` scans the repo-bundled provider directories. `discover_memory_providers()` reads metadata and performs a lightweight availability check by loading a provider and calling `is_available()`. `load_memory_provider(name)` then imports the chosen provider on demand.

This separate path exists because the trust model is narrower and the runtime contract is different. A memory provider is not just a plugin that happens to expose memory tools. It implements the `MemoryProvider` ABC, which includes lifecycle methods for initialization, prompt contribution, prefetch, post-turn sync, tool handling, config schema, shutdown, and optional session/compression/delegation hooks.

That is why Hermes gives them their own discovery family.

### 7. Activation happens through config, and only one external provider may win

The main activation switch for memory providers is `memory.provider` in Hermes config.

During agent initialization, `run_agent.py` reads that config value, attempts to `load_memory_provider(...)`, and if the provider is present and available, hands it to `MemoryManager`. `MemoryManager.initialize_all(...)` then starts the provider with runtime context such as session ID, platform, Hermes home, and profile identity.

The important rule is enforced in `MemoryManager.add_provider()`: only one external provider is allowed at a time. If a second external provider is added, Hermes logs a warning and rejects it.

Why the restriction?

- memory providers can add tools to the model-visible surface
- they can inject recall context and prompt blocks
- they can write back after turns and at session boundaries

If Hermes allowed several external memory providers at once, the tool surface would grow, the recall semantics would become ambiguous, and competing backends could write conflicting representations of the same session.

This is one of the biggest design differences from general plugins. General plugins compose broadly; external memory providers are intentionally single-slot.

### 8. Memory providers plug into the agent loop more deeply than general plugins

Once active, the memory-provider family connects to the runtime in several places:

- system-prompt contribution through `MemoryManager.build_system_prompt()`
- pre-turn recall through `prefetch_all()`
- memory-tool schema injection into the tool surface
- post-turn sync through `sync_all()`
- queued prefetch for the next turn
- optional callbacks for session end, compression, delegation, and built-in memory writes

A general plugin hook can observe a turn or inject ephemeral context. A memory provider participates in the memory lifecycle of the run.

At the same time, memory providers still do not own the whole runtime. They do not replace:

- session storage
- main prompt assembly rules
- model/provider selection
- the tool registry as a whole
- the agent loop itself

They are a specialized backend that Hermes calls at defined memory-related points.

### 9. Memory-provider CLI exposure is gated by the active provider

Memory providers have their own CLI story too, and it is more constrained than the general plugin one.

`discover_plugin_cli_commands()` reads `memory.provider` and only imports `cli.py` for the active provider. If no external provider is active, no provider-specific command tree is exposed. If the active provider has no `cli.py`, nothing is added.

That active-provider gating is a useful example of precedence:

- configured provider decides which provider may expose CLI commands
- inactive providers stay out of `hermes --help`
- CLI import is lightweight and does not require loading every provider SDK

This keeps the command surface small and aligned with the single-provider rule.

## Source Files

| File | Why it is an anchor |
| --- | --- |
| `hermes-agent/hermes_cli/plugins.py` | Core general plugin machinery: manifests, loading, disabled-plugin precedence, hook invocation, tool registration, and plugin CLI metadata. |
| `hermes-agent/hermes_cli/plugins_cmd.py` | Management CLI for installing, updating, removing, enabling, and disabling Git-installed general plugins. |
| `hermes-agent/model_tools.py` | Shows where general plugin discovery enters the tool-surface build path. |
| `hermes-agent/run_agent.py` | Shows where plugin hooks are invoked and where the selected memory provider is activated and integrated into the agent loop. |
| `hermes-agent/agent/memory_provider.py` | Defines the external memory-provider contract and explains the intended lifecycle and single-provider model. |
| `hermes-agent/agent/memory_manager.py` | Enforces the one-external-provider rule and coordinates provider initialization, recall, tool routing, sync, and shutdown. |
| `hermes-agent/plugins/memory/__init__.py` | Separate discovery and loading layer for repo-bundled memory providers, including active-provider CLI gating. |
| `hermes-agent/plugins/memory/*` | Concrete memory-provider implementations and provider-specific metadata. |
| `hermes-agent/website/docs/developer-guide/memory-provider-plugin.md` | Maintainer guidance for implementing a memory provider against the runtime contract. |
| `hermes-agent/website/docs/user-guide/features/plugins.md` | User-facing explanation of the general plugin system, discovery sources, and plugin-management commands. |
| `hermes-agent/website/docs/user-guide/features/memory-providers.md` | User-facing explanation of the external memory-provider family and its one-active-provider rule. |

## See Also

- [Memory and Learning Loop](memory-and-learning-loop.md)
- [Tool Registry and Dispatch](tool-registry-and-dispatch.md)
- [Session Storage](session-storage.md)
- [Cross-Session Recall and Memory Provider Pluggability](../concepts/cross-session-recall-and-memory-provider-pluggability.md)
- [Self-Improving Agent Architecture](../concepts/self-improving-agent-architecture.md)
