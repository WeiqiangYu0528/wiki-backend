# Tool Registry and Dispatch

## Overview

This page explains how Hermes turns "tools" into a governed capability surface for the model. The important idea is that the tool runtime does more than store handler functions. It decides which capabilities get registered, which ones are discovered at startup, which ones are visible in a given session, and how a tool call is finally executed.

That makes this subsystem a control layer, not just a registry. A reader who understands it can answer three practical questions:

- how a tool becomes visible to the model
- why a tool may disappear even though code exists for it
- where execution changes from normal dispatch into approval-sensitive or agent-owned paths

## What The Tool Runtime Actually Owns

The tool runtime owns the model-visible capability surface for Hermes.

It owns:

- module-time registration through `registry.register(...)`
- startup discovery of built-in tools, MCP tools, and plugin tools
- toolset resolution and enabled/disabled filtering in `model_tools.get_tool_definitions(...)`
- readiness filtering through per-tool `check_fn` callbacks
- normal execution dispatch through `model_tools.handle_function_call(...)` and `ToolRegistry.dispatch(...)`
- terminal-command guard evaluation before shell execution

It does not own:

- the agent loop's internal stateful tools such as `todo`, `memory`, `session_search`, and `delegate_task`
- the user-facing approval UX for each surface
- the surrounding shell behavior that decides which toolsets to enable for a CLI, gateway, editor, or ACP session

That boundary matters. Hermes keeps the policy logic close to the tool runtime, but leaves surface-specific transport and presentation to the caller.

## Key Types And Registry Anchors

| Anchor | Why it matters |
| --- | --- |
| `ToolEntry` in `hermes-agent/tools/registry.py` | Stores the canonical metadata for one registered capability: name, toolset, schema, handler, readiness check, async flag, and UI metadata. |
| `ToolRegistry.register()` | The write path into the registry. Tool modules call this at import time, so registration is driven by discovery order rather than a central switch statement. |
| `ToolRegistry.get_definitions()` | Converts requested tool names into OpenAI-style schemas, while dropping any tool whose `check_fn` fails or raises. |
| `ToolRegistry.dispatch()` | Resolves a tool name to its handler, bridges async tools through `_run_async()`, and returns structured JSON errors instead of throwing. |
| `_discover_tools()` in `hermes-agent/model_tools.py` | Imports Hermes' built-in tool modules so their registration side effects run. |
| `get_tool_definitions()` in `hermes-agent/model_tools.py` | Expands toolsets into tool names, applies enabled/disabled filtering, then asks the registry for the final visible schemas. |
| `handle_function_call()` in `hermes-agent/model_tools.py` | The normal runtime entry point for a model-emitted tool call. It adds plugin hooks and forwards most calls into `ToolRegistry.dispatch()`. |
| `DANGEROUS_PATTERNS` and `check_all_command_guards()` in `hermes-agent/tools/approval.py` | Define the command-policy boundary used by the terminal tool before execution. |
| `terminal_tool()` in `hermes-agent/tools/terminal_tool.py` | The concrete high-risk handler that applies approval checks before running shell commands. |

Representative registry surface:

```python
class ToolRegistry:
    def register(...): ...
    def get_definitions(self, tool_names: Set[str], quiet: bool = False) -> List[dict]: ...
    def dispatch(self, name: str, args: dict, **kwargs) -> str: ...
```

## How Hermes Builds The Model-Visible Tool Surface

Hermes builds tool visibility in a strict order. Reading the system in this order is the easiest way to understand why a capability is present, absent, or filtered.

### 1. Registration happens inside tool modules

Each tool module imports the singleton registry and calls `registry.register(...)` at module scope. The terminal tool is representative: it defines `TERMINAL_SCHEMA`, wraps `terminal_tool()` in `_handle_terminal(...)`, then registers the `terminal` capability into toolset `terminal`.

This means a tool is not "known to Hermes" just because a file exists. Hermes only knows about a capability after the module has been imported and its registration side effect has run.

### 2. `model_tools.py` discovers built-in modules

When `hermes-agent/model_tools.py` is imported, `_discover_tools()` imports the built-in tool modules in a fixed list. That import pass is what populates the registry for core tools.

After the built-in pass, `model_tools.py` performs two more discovery stages:

- `discover_mcp_tools()` registers tools exposed by configured MCP servers
- `discover_plugins()` loads plugin-defined tools

Those dynamic sources matter because they expand the capability surface after the built-in import list has finished. Hermes therefore treats "tool discovery" as broader than "import files under `tools/`". Just as importantly, those tools do not get a bypass. Once registered, MCP and plugin tools still have to survive the same toolset resolution and readiness filtering as built-in tools.

### 3. Toolsets decide which registered tools are even eligible

Registration alone does not make a tool visible. The next gate is toolset resolution in `get_tool_definitions(...)`.

That function starts from the caller's requested surface:

- if `enabled_toolsets` is provided, Hermes expands only those toolsets
- if `disabled_toolsets` is provided, Hermes starts from all known toolsets and subtracts the disabled ones
- if neither is provided, Hermes resolves all known toolsets

This is a governance mechanism, not a cosmetic filter. Toolsets define which classes of capability a surface is allowed to expose at all. A narrow preset such as an editor-facing or ACP-facing session can deliberately omit terminal, browser, or other risky surfaces before readiness checks even run.

### 4. Readiness checks decide which eligible tools are actually usable

Once `get_tool_definitions(...)` has a candidate set of tool names, it calls `registry.get_definitions(...)`. That is where Hermes executes each tool's optional `check_fn`.

If the check returns false, or if it raises, the tool is removed from the schema list. Typical reasons include:

- missing environment variables or API keys
- missing binaries or browser dependencies
- unavailable external services
- toolset-level prerequisites that are not currently satisfied

This is also governance. Readiness checks stop Hermes from advertising capabilities that the current runtime cannot safely or correctly serve.

### 5. Hermes patches the final visible schemas to match reality

After filtering, `get_tool_definitions(...)` computes the actual surviving tool names and uses that list to repair schemas that reference other tools. Two concrete examples live in the source:

- `execute_code` rebuilds its sandbox schema so it only mentions tools that survived filtering
- `browser_navigate` removes static cross-references to web tools when `web_search` and `web_extract` are not available

This final step is easy to miss, but it is part of capability governance too. Hermes does not just filter the list; it also tries to keep descriptions and nested schemas consistent with the filtered surface so the model does not hallucinate unavailable tools.

### Build path summary

The model-visible tool surface is built in this order:

1. tool modules register themselves with `ToolRegistry`
2. `model_tools.py` discovers built-in, MCP, and plugin tools
3. `get_tool_definitions(...)` resolves the caller's allowed toolsets
4. `registry.get_definitions(...)` removes tools that fail readiness checks
5. `model_tools.py` patches dependent schemas to match the surviving set
6. the final filtered schema list is sent to the model

## Normal Dispatch Path

Once the model has received that filtered schema list, normal execution follows a separate path.

1. The model emits a tool call by function name and arguments.
2. Hermes routes the call into `model_tools.handle_function_call(...)`.
3. `handle_function_call(...)` coerces arguments to schema-declared types and runs plugin `pre_tool_call` hooks when available.
4. For ordinary tools, it forwards the call into `registry.dispatch(...)`.
5. `ToolRegistry.dispatch()` looks up the `ToolEntry`, calls the handler, and uses `_run_async()` when the handler was registered as async.
6. Plugin `post_tool_call` hooks run after the handler returns.
7. Hermes passes the tool result back into the conversation as the tool output.

Two runtime behaviors are worth calling out:

- `registry.dispatch()` returns JSON error strings for unknown tools or handler exceptions, rather than crashing the turn
- `handle_function_call(...)` wraps the whole operation in a second error boundary, so the model still receives a structured failure even if something outside the handler breaks

This is the normal dispatch path: schema visibility is already settled, and the runtime is now executing one allowed tool call.

## Agent-Level Special Cases

Not every model-visible tool is executed through normal registry dispatch.

`model_tools.py` defines an `_AGENT_LOOP_TOOLS` set for tools that are advertised to the model but must be intercepted by the agent loop because they operate on agent-owned state or orchestration:

- `todo`
- `memory`
- `session_search`
- `delegate_task`

These tools still appear in the tool surface because the model needs to know they exist. But if `handle_function_call(...)` receives one of them directly, it returns an error saying the tool must be handled by the agent loop.

That split is intentional:

- registration and schema exposure still happen in the tool runtime
- actual execution is intercepted by the higher-level `AIAgent` loop

So Hermes has two execution categories, not one:

- normal tools that dispatch through the registry
- agent-level tools whose schemas are registered normally but whose execution is intercepted before registry dispatch

## Approval-Sensitive Terminal Execution

The terminal tool is still a normal registered tool, but its handler crosses into a stricter policy boundary before command execution.

Inside `terminal_tool()`, Hermes calls `_check_all_guards(...)` before running the command. That function delegates into `tools/approval.py`, where Hermes combines:

- pattern-based dangerous-command detection from `DANGEROUS_PATTERNS`
- additional security findings such as Tirith warnings or blocks
- per-session and permanent approval state
- smart-approval or manual-approval decisions

This is the key boundary to remember:

- the policy trigger lives in the tool runtime
- the approval transport lives in the calling surface

In other words, `tools/approval.py` decides when a command needs approval and what approval state means. But the way Hermes asks the user is surface-specific:

- CLI surfaces register callbacks for interactive approval prompts
- gateway surfaces register notify callbacks and later resolve the queued approval through `/approve` or `/deny`
- editor or ACP-style surfaces can bridge the same policy decision through their own permission UI

That separation is architectural, not cosmetic. Hermes keeps one command-policy engine so every surface uses the same dangerous-command rules, while still letting each surface deliver approvals in its own transport model.

## Ownership Boundaries

| Subsystem | Owns | Deliberately does not own |
| --- | --- | --- |
| `tools/registry.py` | Canonical tool metadata, schema retrieval, dispatch by name | Startup discovery, surface presets, agent-loop interception |
| `model_tools.py` | Discovery, toolset resolution, filtered schema exposure, normal function-call entry point | Terminal policy definitions, agent-local state handling |
| Agent loop (`AIAgent` and surrounding runtime) | Interception of agent-level tools such as `todo` and `memory` | General-purpose registry dispatch for ordinary tools |
| `tools/approval.py` | Dangerous-command policy, approval state, CLI/gateway approval orchestration primitives | Deciding which toolsets a surface exposes |
| Calling surfaces such as CLI, gateway, ACP | Approval transport, user interaction, per-surface enable/disable choices | Shared dangerous-command detection rules |

If a reader is trying to debug "why didn't the model see this tool?", they should start with discovery, toolsets, and readiness checks. If they are debugging "why didn't this visible tool execute?", they should follow the dispatch path or the agent-level interception path. If they are debugging "why did the command require approval here but not there?", they should separate the shared policy logic from the surface-specific approval transport.

## Source Files

| File | Why it is an anchor |
| --- | --- |
| `hermes-agent/tools/registry.py` | Defines `ToolEntry`, `ToolRegistry`, and the core registration/schema/dispatch API. |
| `hermes-agent/model_tools.py` | Imports tool modules, discovers MCP and plugin tools, resolves toolsets, patches filtered schemas, and dispatches ordinary tool calls. |
| `hermes-agent/tools/approval.py` | Centralizes dangerous-command detection, approval state, gateway queues, and approval decisions. |
| `hermes-agent/tools/terminal_tool.py` | Shows how a registered tool uses the approval runtime before shell execution. |
| `hermes-agent/website/docs/developer-guide/tools-runtime.md` | Mirrors the intended maintainer mental model for registration, filtering, dispatch, and approval-sensitive execution. |

## See Also

- [Agent Loop Runtime](agent-loop-runtime.md)
- [Terminal and Execution Environments](terminal-and-execution-environments.md)
- [Toolset-Based Capability Governance](../concepts/toolset-based-capability-governance.md)
- [Tool Call Execution and Approval Pipeline](../syntheses/tool-call-execution-and-approval-pipeline.md)
