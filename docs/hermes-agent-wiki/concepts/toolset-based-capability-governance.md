# Toolset-Based Capability Governance

## Overview

Toolsets are the capability-governance layer between raw tool discovery and what the model is actually allowed to see. Hermes may discover many tools at startup, but a session does not automatically expose all of them. The active surface chooses a preset, Hermes resolves it into concrete tool names, and readiness checks decide which tools are usable.

That is why Hermes uses toolsets instead of publishing every discovered tool directly. Toolsets let the same registry support broad CLI sessions, platform-specific gateway presets, narrow cron runs, editor-focused ACP sessions, and locked-down research or benchmark environments without changing tool code.

This page traces that chain from discovery to model-visible schema, then shows how skill visibility reuses the same capability picture.

## Systems Involved

The control layer lives primarily in [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md), with surface presets defined in `model_tools.py` and `toolsets.py`. The [Skills System](../entities/skills-system.md) sits alongside it and reads the same resolved capability state when deciding whether a skill should appear as a fallback or requirement-driven procedure.

The main pieces are `toolsets.py` for named bundles and compositions, `model_tools.py` for resolution and schema patching, `tools/registry.py` for readiness filtering and dispatch, `agent/prompt_builder.py` for skill visibility, and surface configuration in `run_agent.py`, `gateway/run.py`, `cron/scheduler.py`, `acp_adapter/session.py`, and research configs.

The boundary is simple: toolsets decide capability exposure, while the registry and runtime decide whether a capability is actually available.

## Mechanism

### 1. Hermes discovers tools before it chooses a surface

Tool modules self-register with the central registry when they are imported. `model_tools._discover_tools()` imports the built-in tool modules, then Hermes discovers MCP and plugin tools as additional sources.

Discovery tells Hermes what exists. It does not yet tell the model what may be used.

### 2. The active surface selects a toolset preset

Every runtime surface chooses a toolset policy before the turn starts. That policy may come from a CLI config flag, a gateway platform preset, a cron-safe environment, an ACP adapter session, or a benchmark/research environment.

The important distinction is between the surface and the tools:

- the surface decides the preset
- the preset decides which toolsets are enabled or disabled
- the toolsets decide which registered tools are eligible for exposure

`model_tools.get_tool_definitions(enabled_toolsets, disabled_toolsets, quiet_mode)` is the main entry point for that policy.

### 3. Toolset resolution expands bundles into concrete tool names

`toolsets.py` defines named bundles such as `web`, `file`, `terminal`, `browser`, `memory`, `session_search`, `hermes-acp`, `hermes-cli`, and platform-specific messaging sets. Toolsets may include other toolsets, so a preset can compose a larger surface from smaller bundles.

Resolution happens before readiness filtering:

1. if `enabled_toolsets` is set, Hermes resolves only those toolsets
2. if `disabled_toolsets` is set, Hermes starts from the full set and subtracts the disabled ones
3. if neither is set, Hermes resolves the full available catalog

Plugin-provided toolsets are resolved through the same path. There is no separate bypass for plugins or MCP tools once they are registered.

### 4. Readiness checks remove tools that exist but are not usable

After toolset resolution, `model_tools.get_tool_definitions(...)` hands the candidate tool names to the registry. The registry runs each tool's `check_fn` and drops tools whose prerequisites are missing or whose check raises.

That means a tool can be:

- discovered in code
- included in a toolset preset
- still absent from the final schema because the runtime is not ready

This is where capability governance becomes real. Hermes only promises the subset that is both allowed by the surface and available in the current runtime.

### 5. Hermes rewrites dependent schemas to match the surviving surface

Hermes does not stop at filtering the tool list. It also patches schemas that mention other tools by name so they do not advertise capabilities that were filtered out.

Two examples in `model_tools.py` show the pattern:

- `execute_code` rebuilds its sandbox schema so it only lists tools that actually survived filtering
- `browser_navigate` removes the static `web_search` and `web_extract` cross-reference when those tools are not available

This matters because the model responds to schema text, not developer intent. If a filtered-out tool is still mentioned in a description, the model may hallucinate a call to something that does not exist.

### Raw discovery, toolset exposure, and skill fallback

| Layer | What it decides | What it does not decide | Why it matters |
| --- | --- | --- | --- |
| Raw tool discovery | What code or plugin modules exist and can register a tool | Which tools a session may see | Discovery is wider than exposure. |
| Toolset exposure | Which registered tools a surface is allowed to present to the model | Whether the tool is actually healthy or approved | This is the governance boundary. |
| Skill fallback visibility | Which skills should be shown or hidden based on resolved tools/toolsets | Tool execution or registry dispatch | Skills adapt to capability, but do not replace it. |

## How Skills Fit Into The Same Picture

Skills are not tools, but they use the same capability picture when deciding what to show.

`agent/prompt_builder.py` reads skill frontmatter conditions and compares them against the resolved tool and toolset set. The rules are intentionally asymmetric:

- `fallback_for_toolsets` and `fallback_for_tools` hide a skill when the preferred tool or toolset is already present
- `requires_toolsets` and `requires_tools` hide a skill when the necessary capability is missing

That means skills can behave like capability fallback rather than just static documentation. If Hermes already has the right toolset, the skill can stay out of the prompt index. If the capability is missing, the skill can appear as the procedural fallback the model should use instead.

This reads the same resolved capability state, so the model does not see a fallback skill when the direct capability is already present.

## Surface Presets And Their Invariants

Different Hermes surfaces choose different presets, but they all flow through the same machinery.

- CLI sessions typically enable a broad interactive surface through `run_agent.py` and `cli.py`
- gateway sessions choose platform-specific toolsets from `gateway/run.py`
- cron jobs disable interactive or messaging surfaces and keep automation narrow
- ACP sessions use an editor-focused preset such as `hermes-acp`
- research and benchmark environments choose explicit minimal sets such as web/file/terminal combinations

The runtime invariant is not "every surface gets the same tools." The invariant is "every surface uses the same rules to decide which tools count as available."

That gives Hermes a few useful properties:

- one registry, many surfaces
- one readiness model, many presets
- one schema builder, many visibility rules
- no accidental exposure of tools that exist in code but are not safe or relevant on a given surface

It also keeps edge cases coherent. A gateway session can expose messaging and `send_message` while an ACP session does not. A cron job can omit interactive tools while still using the same registry. A research environment can stay locked to the benchmark's tool budget.

## Why Toolsets Exist Instead Of Direct Exposure

Toolsets are a governance layer because direct exposure would make every runtime surface too coarse.

Without toolsets, Hermes would have to choose between two bad options:

- expose everything discovered, which leaks irrelevant or unsafe capabilities into surfaces that should be constrained
- hard-code separate tool lists into every runtime, which duplicates policy and drifts over time

Toolsets avoid both failures. They let Hermes define capability families once, compose them into surface presets, and rely on readiness checks plus schema patching to keep the visible surface honest.

That is why toolset resolution stays close to the registry. The registry owns what exists and what is healthy. Toolsets own what a surface should expose. Skills read that result and adapt their own visibility.

## Source Evidence

This page is grounded in these implementation files and docs:

- `hermes-agent/model_tools.py` for discovery, `get_tool_definitions()`, schema filtering, and dynamic schema patching
- `hermes-agent/toolsets.py` for named toolsets, composition, plugin toolset resolution, and surface presets
- `hermes-agent/tools/registry.py` and [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md) for `check_fn` filtering and final dispatch
- `hermes-agent/agent/prompt_builder.py` for skill fallback and requirement-based visibility
- `hermes-agent/website/docs/developer-guide/tools-runtime.md` for the maintainer-facing description of the same toolset pipeline
- `hermes-agent/run_agent.py`, `hermes-agent/gateway/run.py`, `hermes-agent/cron/scheduler.py`, and `hermes-agent/acp_adapter/session.py` for surface-specific presets
- `hermes-agent/environments/*` for research and benchmark configurations that narrow the tool surface

## See Also

- [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md)
- [Skills System](../entities/skills-system.md)
- [CLI Runtime](../entities/cli-runtime.md)
- [Gateway Runtime](../entities/gateway-runtime.md)
- [ACP Adapter](../entities/acp-adapter.md)
- [Cron System](../entities/cron-system.md)
