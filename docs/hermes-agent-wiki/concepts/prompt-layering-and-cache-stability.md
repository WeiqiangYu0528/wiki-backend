# Prompt Layering and Cache Stability

## Overview

Hermes does not treat "the prompt" as one thing. It separates a stable session prefix from per-turn overlays. That design is doing three jobs at once:

- keeping the agent's identity and long-lived guidance stable across a session
- preserving provider-side prompt caching, especially for Anthropic-style cached prefixes
- letting transient context arrive at call time without rewriting the stored system prompt

The core idea is simple: if something should define the agent for the whole session, Hermes freezes it into the stable system prompt. If something only matters for this call or turn, Hermes injects it later.

## The Pattern in One Table

The cleanest way to understand the pattern is to separate what Hermes wants to persist and cache from what it wants to inject transiently.

| Layer type | Typical contents | When it changes | Why Hermes keeps it there |
| --- | --- | --- | --- |
| Stable system prefix | identity, tool guidance, optional stable system message, frozen memory snapshots, static provider prompt block, skills index, context files, timestamp, session metadata, platform hint | once per session, then on explicit rebuild points such as compression | keeps identity stable, keeps stored sessions reproducible, preserves cached-prefix reuse |
| Ephemeral system overlay | `ephemeral_system_prompt`, shell-specific nudges, runtime-only warnings | per call or per turn | useful runtime steering that should not mutate stored prompt state |
| Ephemeral user-message overlay | memory-provider recall, plugin `pre_llm_call` context | per turn | adds dynamic context without poisoning the stable system prefix |
| Ephemeral prefill messages | seeded assistant or user messages for one workflow or one provider behavior | per call | supports specialized call behavior without turning temporary scaffolding into session identity |

Stable prompt state is treated as session state, while overlays are treated as call-time state.

## How the Mechanism Works

### 1. Hermes builds the stable prompt once

`AIAgent._build_system_prompt()` in `run_agent.py` is the runtime entry point. It is explicitly documented and implemented as a session-scoped build step. The result is cached on `self._cached_system_prompt`, stored in SQLite, and reused on later turns in the same session.

The stable prompt is assembled in a deliberate order:

1. agent identity from `SOUL.md` when present, otherwise `DEFAULT_AGENT_IDENTITY`
2. tool-aware behavior guidance such as memory, session-search, and skill-management instructions
3. optional model-family execution guidance when the active model needs it
4. optional stable `system_message`
5. frozen built-in memory and user-profile snapshots
6. external memory-provider static prompt block
7. compact skills index
8. project context files
9. stable metadata such as timestamp, session ID, model, provider, and platform hint

Identity comes first because Hermes wants the top of the prefix to define the agent, not the current task.

### 2. Hermes stores and reuses the exact prompt snapshot

On the first turn of a new session, Hermes builds the stable prompt and writes that snapshot into session storage. On a continued session, `run_agent.py` tries to reuse the already stored prompt instead of rebuilding from the current filesystem state.

If Hermes rebuilt the prompt on every turn, provider-side prefix caching would churn and session continuity would become fuzzy, because changing files on disk could silently change the active system prompt mid-session.

The code comments in `run_agent.py` make that intent explicit: reusing the exact stored prompt helps the Anthropic cache prefix match and keeps continuation behavior stable.

### 3. Transient context is injected later

After the stable prompt is chosen, Hermes still has to handle the context that only matters right now. It does that at API-call time rather than by mutating the stored prefix.

The runtime adds transient context in three main ways:

- `ephemeral_system_prompt` is appended to the effective system message only for the outgoing API call
- plugin `pre_llm_call` context and memory-provider `prefetch_all()` recall are injected into the current turn's user message
- `prefill_messages` are inserted after the system prompt but before conversation history

These additions do not rewrite `self._cached_system_prompt`, and they are not meant to become the durable definition of the session.

### 4. Prompt caching depends on that boundary

`agent/prompt_caching.py` applies Anthropic cache-control markers using a `system_and_3` strategy:

- the system prompt
- the last three non-system messages

That strategy only helps if the system prompt is genuinely stable. If runtime overlays were merged into the stored system prompt on every call, the first cache breakpoint would keep changing and the expensive cached prefix would stop being reusable.

Prompt layering is the precondition for the caching strategy to work.

## What Belongs in the Stable Prefix

Hermes tends to put something in the stable prefix when it:

- should define the agent for the whole session
- should survive multiple turns without changing
- is safe to store in session history as part of the prompt snapshot
- would make the session harder to reason about if it changed mid-session

That is why identity, durable tool guidance, frozen memory snapshots, the skills index, project context files, and stable metadata live in the stable prefix.

## What Stays Ephemeral

Hermes keeps something out of the stable prefix when it is high-churn, turn-specific, or better understood as current-call input than as session identity.

That includes memory-provider recall, plugin-contributed per-turn context, ephemeral system hints from the active surface, and prefill messages used to shape one call path.

This also explains why Hermes injects provider recall into the user message instead of the system prompt. The content is useful, but it is not supposed to redefine the session's stable behavior contract.

## Identity Stability, Cache Stability, and Transient Injection

These three ideas are related, but they are not the same thing.

- Identity stability means the agent's core persona and behavioral framing should not drift every turn.
- Cache stability means the expensive prompt prefix should stay byte-stable enough for provider-side caching to help.
- Transient injection means Hermes can still add the context needed for this turn without redefining the stable prompt.

The design works because Hermes keeps them aligned: stable identity enables cacheable prefixes, and transient context is routed so it does not break either one unless Hermes explicitly rebuilds the prompt.

## Invariants and Tradeoffs

This pattern gives Hermes several strong guarantees.

### Invariants

- A continued session reuses the same stored stable system prompt unless Hermes explicitly rebuilds it.
- Per-turn recall and plugin overlays do not mutate the durable prompt snapshot.
- Anthropic prompt caching can treat the system prompt as a reliable breakpoint because Hermes protects it from turn-by-turn churn.
- Shells can add overlays, but they do not become owners of prompt ordering or stable prompt structure.

### Tradeoffs

- Mid-session memory writes do not instantly rewrite the stable prompt. They affect future rebuilds or future sessions more naturally than the current prefix.
- Changes to `SOUL.md` or project context files during a live session do not automatically become active in that session's stored prompt.
- Runtime overlays are powerful, but because they are ephemeral they are not the canonical long-term record of session identity.

## Why This Matters Across the Runtime

This concept sits at the boundary between several subsystems. [Prompt Assembly System](../entities/prompt-assembly-system.md) defines the stable layers and their order. [`AIAgent`](../entities/agent-loop-runtime.md) decides when the prompt is built, reused, or rebuilt. [Memory and Learning Loop](../entities/memory-and-learning-loop.md) decides which memory stays stable and which recall arrives per turn. [Provider Runtime](../entities/provider-runtime.md) matters because caching behavior is provider-sensitive.

## Source Evidence

The implementation evidence for this pattern is unusually direct:

- `run_agent.py` documents `_build_system_prompt()` as a session-cached build step, stores the result in SQLite, and reuses the stored prompt on continuation turns.
- `run_agent.py` also appends `ephemeral_system_prompt` only at API-call time and injects plugin context plus memory-provider recall into the current user message instead of mutating the cached system prompt.
- `agent/prompt_builder.py` defines the stable layers: identity loading, tool guidance, skills index construction, and project context discovery.
- `agent/prompt_caching.py` encodes the Anthropic `system_and_3` strategy, which only pays off when the system prefix stays stable.
- `website/docs/developer-guide/prompt-assembly.md` describes the same cached-versus-ephemeral split from the project’s own maintainer-facing perspective.

Taken together, those sources show that Hermes is intentionally designed around a stable prompt prefix plus ephemeral overlays, not around rebuilding one giant prompt blob every turn.

## See Also

- [Prompt Assembly System](../entities/prompt-assembly-system.md)
- [Agent Loop Runtime](../entities/agent-loop-runtime.md)
- [Memory and Learning Loop](../entities/memory-and-learning-loop.md)
- [Provider Runtime](../entities/provider-runtime.md)
- [CLI to Agent Loop Composition](../syntheses/cli-to-agent-loop-composition.md)
- [Self-Improving Agent Architecture](self-improving-agent-architecture.md)
