# Hermes Agent Glossary

## Overview

The hardest part of reading Hermes is learning which words are runtime terms, which words are user-facing product language, and which words sound similar but mean different things depending on the subsystem.

This glossary does not try to define every noun in the repo. It focuses on Hermes-specific vocabulary newcomers will keep tripping over while reading the entity and synthesis pages.

The big mental model is simple:

- Hermes has one shared agent runtime.
- Several product surfaces host that runtime: CLI, gateway, cron, ACP, and research or eval shells.
- Tools, skills, memory, plugins, and execution environments extend what the runtime can do, but they are not interchangeable terms.

If you keep those three layers separate, most of the vocabulary stops being slippery.

## The Distinctions That Matter Most

Before the term clusters, it helps to pin down the pairs that are easiest to confuse.

| Confusing pair | What the first term means | What the second term means |
| --- | --- | --- |
| `tool` vs `skill` | A callable capability Hermes can execute, usually implemented in Python and exposed through the tool registry | A reusable instruction bundle that tells the model how to approach a kind of task |
| `memory` vs `skill` | Durable facts, preferences, recalled context, or provider-backed knowledge that change what Hermes remembers | Procedural know-how: reusable "how to do this" guidance that changes how Hermes works |
| `provider` vs `model` | The backend family or endpoint Hermes talks to, such as OpenRouter, Anthropic, or a custom OpenAI-compatible host | The specific model slug routed through that provider |
| `origin` vs `delivery target` | The platform/chat/thread a job or action came from | The place Hermes should send the result now; this may match the origin or be somewhere else |
| `gateway session` vs `CLI session` | A conversation keyed by messaging-platform routing state | A conversation started from the terminal UI and stored in session DB without gateway routing keys |
| `ordinary session` vs `cron session` | A user-driven conversation with history continuity | A fresh isolated scheduled run launched by cron, even if the result is later delivered back to a chat |
| `plugin` vs `memory provider` | The broader extension mechanism for adding behavior or integrations | A specialized plugin family that supplies one external memory backend at a time |

If the rest of the glossary does one job well, it should make those lines feel stable.

## Runtime And Session Terms

### `AIAgent`

This is the shared execution core in `run_agent.py`. When a wiki page says "the agent loop," it usually means the runtime behavior owned here: prompt building, provider calls, tool execution, retries, compression, and persistence.

### `session`

In Hermes, `session` is a storage and continuity term, not just "whatever process is running right now." A session usually means one conversation thread tracked in session storage. The exact meaning depends on the hosting surface.

- A CLI session is the conversation you started from the terminal UI.
- A gateway session is the conversation keyed by platform routing, such as a Telegram DM or a Discord thread.
- A cron session is a fresh scheduled run with its own session ID and isolated execution rules.
- An ACP session is an editor-integrated conversation hosted through the ACP adapter.

These are related through shared storage and runtime machinery, but not literally the same object.

### `gateway session key`

This is the deterministic routing key the gateway uses to map inbound platform messages onto the correct conversation.

### `HERMES_HOME`

This is the profile-scoped home directory where Hermes keeps runtime state such as `config.yaml`, `.env`, `SOUL.md`, memory files, installed skills, and cron state.

## Capability Terms

### `tool`

A tool is a callable operation visible to the model, usually registered through the tool registry in `tools/`. Tools are the execution side of Hermes.

When a page talks about tool governance, it usually means registration, surface exposure through toolsets, or approval checks before execution.

### `toolset`

A toolset is a named bundle of tools exposed together. Hermes uses toolsets to keep surfaces coherent across surfaces.

### `skill`

A skill is not executable code in the same sense as a tool. It is a directory-centered instruction package whose `SKILL.md` teaches the model how to handle a kind of task.

The most important runtime distinction is this: tools are capabilities Hermes can call; skills are procedures that tell the model how to use capabilities well.

### `optional skill`

This means an official skill distributed in `optional-skills/` but not seeded into the working catalog automatically.

## Memory And Learning Terms

### `memory`

In Hermes, `memory` is overloaded. It can mean built-in file-backed memory such as `MEMORY.md` and `USER.md`, recalled context injected for a turn, the `memory` tool, or the broader learning loop that preserves useful knowledge across sessions.

### `prefetch`

This is the provider-backed recall step that happens before a model call. It is turn-specific recall, not stable always-on prompt content.

### `session_search`

This is Hermes's bridge from stored session transcripts back into the live turn. It feels memory-like, but it is not the same thing as an external memory provider.

### `Honcho`

Honcho is not a generic word for memory in Hermes. It is one specific external memory-provider ecosystem that Hermes can integrate with.

### `learning loop`

This is the broader pattern in which Hermes not only answers the current turn, but also preserves useful things for later turns. Memory writes, recall, review passes, and skill creation all feed into this loop.

## Provider And Runtime Routing Terms

### `provider`

A provider is the backend family or endpoint Hermes resolves before a turn starts. Providers own transport rules, credential lookup, and `api_mode` selection.

### `model`

A model is the specific model identifier routed through the chosen provider. The important point is that Hermes does not treat provider and model as the same choice. A model switch may leave the provider unchanged, and a provider switch may force a different transport even if the model name looks similar.

### `api_mode`

This is the transport shape Hermes must use after provider resolution. The common modes are `chat_completions`, `codex_responses`, and `anthropic_messages`.

## Automation And Delivery Terms

### `origin`

Origin means "where this came from." In cron and some messaging-related flows, that usually means the platform, chat, and optional thread or topic that created the job or request.

### `delivery target`

Delivery target means "where the result should go now." It may be the stored origin, a configured home channel, an explicit platform target, or no platform at all if the result is local-only.

Users often assume "send it back there" and "it came from there" are always identical. Hermes keeps them related, but not synonymous.

### `cron job`

A cron job is a stored automation contract: prompt, schedule, optional skills, optional script, and delivery metadata. It is not a long-lived background conversation.

### `cron session`

This is the fresh isolated session Hermes creates when a cron job becomes due. A cron delivery may arrive in an ordinary chat, but the execution itself did not happen inside that ordinary conversation.

## Extension And Integration Terms

### `plugin`

In the broad Hermes sense, a plugin is an extension mechanism that can add behavior, integrations, or provider-style capabilities.

### `memory provider`

A memory provider is a narrower term: one external backend that plugs into the memory and learning loop.

### `ACP`

ACP means Agent Client Protocol. In Hermes, it is the editor-facing transport that lets tools such as VS Code, Zed, or JetBrains talk to Hermes over a structured session bridge.

### `execution environment`

This refers to the backend abstraction used for command execution, such as local, Docker, SSH, Daytona, Singularity, or Modal.

## Reading Advice

If a term feels vague while reading Hermes docs, first ask which layer you are in: shared runtime, hosting surface, or capability layer. Most confusion comes from mixing those layers. "Session" changes between storage, gateway routing, and cron execution. "Memory" changes between prompt assembly, recall, and provider plugins. "Skill" and "tool" often appear together because they cooperate, not because they are the same thing.

## See Also

- [Architecture Overview](architecture-overview.md)
- [Codebase Map](codebase-map.md)
- [Tool Registry and Dispatch](../entities/tool-registry-and-dispatch.md)
- [Skills System](../entities/skills-system.md)
- [Memory and Learning Loop](../entities/memory-and-learning-loop.md)
- [Gateway Runtime](../entities/gateway-runtime.md)
- [Cron System](../entities/cron-system.md)
- [Multi-Surface Session Continuity](../concepts/multi-surface-session-continuity.md)
