# Prompt Assembly System

## Overview

Prompt assembly is the subsystem that turns Hermes's identity, memory, skills, project context, and surface hints into the system prompt seen by the model. Its main job is not "building one long string." Its job is deciding which context should stay stable for an entire session and which context should stay ephemeral at API-call time.

That split matters because Hermes tries to keep the stored system prompt stable across turns. Stable prompt state is easier to cache, easier to reason about, and less likely to drift when plugins, shells, or memory providers add turn-specific context.

The clean mental model is:

- prompt assembly owns the stable prompt layers and their order
- the agent loop owns when that prompt is built, reused, or invalidated
- shells can supply overlays, but they do not become prompt owners

## What Prompt Assembly Owns

Prompt assembly owns the contents of Hermes's stable system prompt. In practice that means:

- choosing the identity layer, including `SOUL.md` fallback behavior
- adding tool-aware guidance blocks when the relevant tools are available
- freezing built-in memory and user-profile snapshots into the prompt
- building the compact skills index
- loading project context files from disk with explicit priority rules
- adding stable session metadata such as start time, optional session ID, model, provider, and platform hint
- sanitizing and truncating file-based prompt input before it is injected

It does not own every piece of context the model sees. It does not decide when to rebuild the prompt, when to compress history, or how plugins inject per-turn recall. Those decisions belong to [`AIAgent`](agent-loop-runtime.md) in `run_agent.py`.

## Stable Vs Ephemeral Prompt Layers

The most important boundary in this subsystem is the one between stable layers and ephemeral overlays.

| Layer type | Typical contents | Where it comes from | Why it lives there |
| --- | --- | --- | --- |
| Stable system prompt | identity, tool guidance, frozen memory, skills index, project context, timestamp, platform hint | `run_agent.py` + `agent/prompt_builder.py` | Reused across turns and stored in SQLite so the prefix stays predictable and cacheable |
| Ephemeral system overlay | `ephemeral_system_prompt`, shell-specific formatting nudges | `AIAgent` runtime args | Changes too often to belong in the stored prompt |
| Ephemeral user-message overlay | plugin `pre_llm_call` context, external memory-provider recall | plugin hooks and `MemoryManager` | Keeps turn-specific context available without mutating the stable prefix |
| Ephemeral prefill messages | provider- or workflow-specific seeded messages | runtime config and call-site setup | Useful for one call or one turn, but not part of Hermes's persistent identity |

Hermes treats the stable prompt as session state. It treats the ephemeral layers as call-time state.

## How The Stable Prompt Is Assembled

`AIAgent._build_system_prompt()` in `run_agent.py` is the runtime entry point, but most of the assembly logic lives in `agent/prompt_builder.py`. The layers are appended in a deliberate order:

1. **Identity first.** Hermes loads `SOUL.md` from `HERMES_HOME` through `load_soul_md()`. If no `SOUL.md` exists, it falls back to `DEFAULT_AGENT_IDENTITY`.
2. **Tool-aware guidance next.** Memory, session-search, and skill guidance only appear when those tools are actually available. Model-family-specific execution guidance can also be added here.
3. **Optional stable system message.** A caller can provide `system_message`, and Hermes treats it as part of the stored prompt snapshot rather than a transient overlay.
4. **Frozen memory blocks.** Built-in memory and `USER.md` profile data are formatted once and appended as prompt background.
5. **External memory-provider system block.** Providers can add stable system-prompt material through `MemoryManager.build_system_prompt()`.
6. **Skills index.** `build_skills_system_prompt()` adds a compact index of available skills, filtered by tools, toolsets, and platform.
7. **Filesystem context.** `build_context_files_prompt()` loads project instruction files from disk using priority rules described below.
8. **Stable metadata.** Hermes appends the conversation start time, optional session ID, selected model, provider, and finally a platform hint such as CLI or messaging-surface guidance.

This order gives Hermes a stable teaching shape. Identity and core behavior come first. Background memory and skills come next. Project-specific instructions follow. Session metadata and surface hints come last because they frame the conversation instead of defining the agent's core persona.

## Filesystem And Runtime Sources

Prompt assembly draws from both the filesystem and the live runtime, but it does not treat them the same way.

### Filesystem sources

The filesystem sources are the durable instruction layers:

- `SOUL.md` in `HERMES_HOME` for agent identity
- `.hermes.md` or `HERMES.md` for Hermes-native project context
- `AGENTS.md`
- `CLAUDE.md`
- `.cursorrules` and `.cursor/rules/*.mdc`

`build_context_files_prompt()` uses first-match-wins ordering for project context:

1. `.hermes.md` or `HERMES.md` walking upward toward the git root
2. `AGENTS.md` in the current working directory
3. `CLAUDE.md` in the current working directory
4. Cursor rule files in the current working directory

That rule is important. Hermes does not try to merge every instruction file it can find. It chooses one project-context family so the prompt does not accumulate conflicting copies of local policy.

`SOUL.md` is independent of that project-context search. It normally occupies the identity slot. When Hermes has already loaded it there, `build_context_files_prompt(skip_soul=True)` prevents the same content from being injected a second time as generic project context.

### Runtime sources

The runtime sources are the layers that come from the current session or calling surface:

- the optional `system_message`
- frozen memory snapshots from the current memory store
- external memory-provider prompt blocks
- the skill index filtered by currently visible tools and toolsets
- session ID, model, provider, and platform values
- `TERMINAL_CWD`, which lets gateway sessions resolve context files from the user's real working directory instead of the gateway process directory

This distinction is useful when reading the code. Filesystem sources usually explain *what instructions Hermes follows*. Runtime sources usually explain *which version of those instructions applies in this session*.

## Why Some Context Stays Outside The Stored System Prompt

Hermes is deliberately conservative about what enters the stored system prompt.

The agent loop caches the built prompt on `self._cached_system_prompt`, stores that snapshot in SQLite, and reuses the exact stored prompt when a later turn continues the same session. That is not just an optimization. It preserves prompt-cache stability, especially for Anthropic-style caching where the system prompt is one of the cache breakpoints.

`agent/prompt_caching.py` applies cache markers to:

- the system prompt
- the last three non-system messages

That strategy only helps if the system prompt stays stable. If plugins, gateway state, or recall text rewrote the system prompt on every turn, the expensive prefix would churn and cache reuse would collapse.

That is why several context sources are injected outside the stored prompt:

- `ephemeral_system_prompt`
- plugin `pre_llm_call` context
- external memory-provider prefetch results
- prefill messages

`run_agent.py` injects plugin context and external recall into the current user message instead of the system prompt. It appends `ephemeral_system_prompt` only at API-call time. Both choices protect the stable prefix while still giving the model turn-specific context.

The same logic explains frozen memory snapshots. Mid-session memory writes can update disk state, but Hermes does not keep mutating the already-built prompt after every write. The prompt is rebuilt on a new session or after invalidation events such as context compression.

## Cache-Stability Goals

The prompt system is optimized around a few clear goals:

- keep the session's main instruction prefix identical across turns whenever possible
- avoid re-reading and reformatting stable context on every model call
- preserve provider-side prompt caching benefits
- make stored sessions reproducible enough that continued turns behave like true continuations instead of fresh prompt rebuilds
- let high-churn context arrive at runtime without poisoning the stable prefix

This is also why the subsystem contains its own micro-caching for the skills layer. `build_skills_system_prompt()` keeps an in-process LRU cache and a disk snapshot so Hermes does not have to rescan every skill file just to rebuild the same stable skills index.

## Shell Boundary: Who Owns What

Shells are allowed to contribute context, but they are not allowed to redefine prompt ownership.

| Owner | Owns | Does not own |
| --- | --- | --- |
| Prompt assembly | stable prompt layers, ordering, context-file priority, sanitization, truncation, skill-index construction | transport-specific delivery, per-turn plugin context, approval UX, conversation-loop timing |
| Agent loop | when the prompt is built, reused, stored, invalidated, or combined with ephemeral overlays | filesystem discovery rules or stable-layer ordering |
| Shells such as CLI or gateway | providing `system_message`, `ephemeral_system_prompt`, `platform`, `session_id`, and working-directory hints | redefining the stable prompt contract or bypassing prompt assembly's ordering rules |

The key boundary is simple: shells may supply overlays, but Hermes keeps ownership of the actual system prompt contract inside the runtime. That prevents each surface from growing its own prompt dialect.

## Guardrails On File-Based Prompt Input

File-based prompt content is treated as useful but untrusted input.

`prompt_builder.py` scans `SOUL.md` and project context files for obvious prompt-injection patterns, strips YAML frontmatter from `.hermes.md`, and truncates oversized content with a head-and-tail strategy. The goal is not full security isolation. The goal is to keep disk-sourced prompt material bounded, readable, and less likely to smuggle low-quality instructions into the stable prompt.

## Source Files

| File | Why it matters |
| --- | --- |
| `hermes-agent/agent/prompt_builder.py` | Defines identity loading, context-file discovery, file sanitization, truncation, skill-index building, and most stable prompt-layer helpers. |
| `hermes-agent/run_agent.py` | Calls `_build_system_prompt()`, caches the result per session, stores it in SQLite, and injects ephemeral overlays at API-call time. |
| `hermes-agent/agent/prompt_caching.py` | Implements the Anthropic cache-marker strategy that depends on a stable system prompt prefix. |
| `hermes-agent/website/docs/developer-guide/prompt-assembly.md` | Maintainer-facing explanation of the stable-vs-ephemeral split and the intended layer order. |

## See Also

- [Architecture Overview](../summaries/architecture-overview.md)
- [Agent Loop Runtime](agent-loop-runtime.md)
- [Memory and Learning Loop](memory-and-learning-loop.md)
- [Prompt Layering and Cache Stability](../concepts/prompt-layering-and-cache-stability.md)
- [CLI to Agent Loop Composition](../syntheses/cli-to-agent-loop-composition.md)
