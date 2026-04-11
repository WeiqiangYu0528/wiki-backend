# Memory And Learning Loop

## Overview

Hermes treats memory as part of turn execution, not as a side database the agent may or may not consult later.

The clean mental model is simple:

- some memory is stable for the whole session
- some memory is recalled only for the current turn
- some learning happens after the answer, so later turns run differently

That split shows up directly in the runtime wiring. When memory features are enabled, `AIAgent` can load built-in memory during startup, expose memory-related tools in the model-visible tool surface, inject stable memory blocks into the cached system prompt, inject recalled context at API-call time, give the model a last chance to save durable facts before compression, sync completed turns to external providers, and launch a background review pass that writes memory or updates skills after the user-facing answer is already done.

So the loop is not "remember once." It is:

1. load durable context
2. recall what this turn needs
3. act and optionally write memory
4. preserve or extract what should survive
5. feed those changes back into future turns

That is why this page is about runtime behavior, not just "memory features."

## What This Page Owns

This page covers the runtime loop that connects four neighboring mechanisms:

- built-in file-backed memory in `MEMORY.md` and `USER.md`
- one optional external memory provider, managed through `MemoryManager`
- `session_search`, which recalls prior conversations from SQLite session storage
- review and nudge behavior that can save memory or improve skills after a turn

It does not own everything around those mechanisms.

| Subsystem | Owns | Does not own |
| --- | --- | --- |
| Memory and learning loop | when memory enters the turn, how recall is injected, how memory tools are routed, when providers sync, when review runs, and how knowledge is preserved before compression or session end | prompt file discovery, SQLite schema design, shell routing, or the overall provider-call loop |
| [Prompt Assembly System](prompt-assembly-system.md) | stable prompt layers and their ordering | post-turn syncing, background review, session search, or provider shutdown |
| [Session Storage](session-storage.md) | transcript persistence, FTS, replay, and lineage | deciding when to search old sessions or how search results are used in the live turn |
| [Agent Loop Runtime](agent-loop-runtime.md) | the master conversation loop that calls memory hooks at defined points | provider-specific storage logic or memory-backend internals |

## Why Memory Is A Runtime Behavior In Hermes

The source makes this explicit in three ways.

First, the architecture is built around memory as a first-class runtime concern. `BuiltinMemoryProvider` exists to normalize Hermes's file-backed memory to the provider contract, and `MemoryManager` is designed for "built-in plus at most one external provider." In the current `run_agent.py` path, built-in memory still travels through a direct `MemoryStore` path while `MemoryManager` handles the optional external provider and bridge hooks.

Second, memory is wired into the same lifecycle points as prompt reuse, tool execution, compression, and persistence. `run_agent.py` does not wait for a later batch job to handle memory. It calls memory hooks during prompt building, before API calls, during tool execution, before compression, after the final response, and at real session boundaries.

Third, Hermes mixes explicit and automatic learning paths. The model can call tools such as `memory`, provider-specific memory tools, or `session_search` directly. But the runtime also nudges review behavior and can run a background review agent that writes memory or updates skills without interrupting the main user flow.

Taken together, Hermes is saying: durable learning changes how later turns run, so the runtime has to own it.

## The Closed Loop At Runtime

The easiest way to read the subsystem is as an ordered loop around `run_conversation()`.

### 1. Session startup loads durable memory

During agent initialization, Hermes may activate two cooperating memory paths:

- the built-in `MemoryStore`, which reads `MEMORY.md` and `USER.md` from disk when built-in memory is enabled
- an optional external provider selected by `memory.provider` and activated through `MemoryManager`

`MemoryManager.initialize_all()` initializes every registered provider it has been given. In the current runtime, that means the active external provider. The provider abstraction itself is stricter than the current wiring: it is written around built-in-first ordering and rejects a second external provider to avoid overlapping tool schemas and conflicting recall behavior.

At this point Hermes has the long-lived material that should shape the session before the first turn even starts.

### 2. Stable memory becomes part of the cached system prompt

When `AIAgent._build_system_prompt()` assembles the stable prompt, it pulls in:

- frozen built-in memory blocks from `MEMORY.md` and `USER.md`
- any static `system_prompt_block()` text contributed by the active external provider

This is the stable part of the memory loop. It is session-shaped, not turn-shaped. Built-in memory is intentionally frozen at prompt-build time so the stored system prompt stays cacheable and reproducible across turns.

That gives Hermes a durable baseline. The next step is turn-specific recall.

### 3. Turn-time recall arrives separately from the stable prompt

Before each model call, Hermes can add dynamic recall on top of that stable base.

`MemoryManager.prefetch_all()` collects pre-turn recall text from registered providers. `run_agent.py` then wraps that material in a fenced `<memory-context>` block with an explicit system note that it is recalled background, not new user input. That recalled block is injected into the current API-facing user message only. It is not persisted into session history and it does not mutate the stored system prompt.

This boundary matters:

- stable memory belongs to [Prompt Assembly System](prompt-assembly-system.md)
- recalled memory belongs to the live turn

Providers can support both styles. Honcho and Hindsight are concrete examples: they can auto-inject recall in context-oriented modes, or expose tools-oriented modes where the model asks for memory explicitly.

### 4. The model can use explicit recall and write paths during the turn

Hermes does not rely only on automatic recall. It also exposes explicit memory operations during tool execution.

| Path | Owner | What it does |
| --- | --- | --- |
| `memory` tool | agent loop + built-in store | Writes to `MEMORY.md` or `USER.md` through the built-in memory tool |
| provider-specific memory tools | `MemoryManager` + active provider | Routes calls such as `honcho_search`, `hindsight_recall`, `mem0_search`, or `viking_remember` to the selected backend |
| `session_search` | agent loop + session DB | Searches prior sessions in SQLite and returns focused summaries of matching conversations |

`session_search` is an especially important boundary case. It is memory-like recall, but it is not a memory-provider feature. The tool reads from `SessionDB`, uses FTS5 to find relevant older sessions, excludes the current session, loads matching transcripts, and summarizes them with the auxiliary LLM path. That makes it a bridge from durable session history into the live turn, not a provider plugin.

The built-in `memory` tool also has a bridge back out to the external provider layer. After successful built-in writes, `run_agent.py` calls `MemoryManager.on_memory_write()` so the active external provider can mirror durable additions or replacements into its own backend.

By the end of this step, Hermes may have learned something new during the turn itself.

### 5. Post-turn syncing keeps external memory current

Once a turn finishes successfully, Hermes calls:

- `MemoryManager.sync_all(original_user_message, final_response)`
- `MemoryManager.queue_prefetch_all(original_user_message)`

This is the write-back half of the loop. Providers can store the completed turn asynchronously and prepare the next round of recall in the background.

The built-in provider is different here. It does not auto-sync whole turns. Built-in writes happen through the intercepted `memory` tool. External providers, by contrast, commonly use `sync_turn()` to retain the conversation itself.

This means the turn is not only finished. It has already started shaping the next one.

### 6. Compression and session shutdown preserve knowledge before context disappears

Hermes has two separate "do not lose this" paths.

**Before compression**

When context compression starts, `run_agent.py` first calls `flush_memories()`. That method gives the model one extra memory-only API call and tells it to save durable facts, especially user preferences, corrections, and recurring patterns, before old context is summarized away.

After that, Hermes calls `MemoryManager.on_pre_compress(messages)`. Providers can extract their own durable insights from the soon-to-be-compressed messages. ByteRover, for example, implements this hook to contribute information before the old middle of the transcript is discarded.

**At actual session end**

At real session boundaries such as CLI exit, `/reset`, or gateway expiry, `shutdown_memory_provider()` calls `MemoryManager.on_session_end()` and then `shutdown_all()`. This is not a per-turn hook. It exists so providers can perform end-of-session extraction or commit behavior only when a session is actually over. OpenViking uses this path to commit a session and trigger memory extraction on its backend.

### 7. Nudges and background review close the loop into future turns

The loop closes after the answer, not before it.

`run_agent.py` tracks two counters:

- `_turns_since_memory`, compared against `memory.nudge_interval`
- `_iters_since_skill`, compared against `skills.creation_nudge_interval`

Those counters decide when Hermes should review whether the finished conversation contained something worth saving. If the thresholds are hit, `_spawn_background_review()` forks a quiet review agent after the main answer has already been delivered.

That review agent can:

- save durable user facts through the `memory` tool
- update or create skills when the conversation revealed a reusable method

This is what makes the sequence a true closed loop. The review pass can change built-in memory files, external provider state, or the available skill corpus after the turn completes. On later turns, those changes re-enter through the earlier steps:

- updated memory files appear in the next stable prompt build or rebuild
- synced provider state changes what `prefetch()` or provider tools can recall
- updated skills change what the agent can discover and reuse later

The loop therefore ends where it began: with a future turn that starts from a different memory state than the one before.

## Built-In And External Paths In The Loop

The runtime uses two memory paths for different jobs.

### Built-in path

Built-in memory is Hermes's baseline durable path.

In the live agent loop, it is handled directly through `MemoryStore` plus the intercepted `memory` tool. `BuiltinMemoryProvider` is the thin adapter form of that same behavior:

- `initialize()` loads memory files from disk
- `system_prompt_block()` formats frozen `MEMORY.md` and `USER.md` content for the stable prompt
- `prefetch()` returns nothing because built-in memory is not query-based recall
- `sync_turn()` is a no-op because built-in writes happen through the explicit `memory` tool

### External path

External providers extend the loop rather than replacing it.

What matters here is not the provider catalog. What matters is the contract they plug into:

- `system_prompt_block()` adds stable provider guidance
- `prefetch()` and `queue_prefetch()` add turn-time recall
- `sync_turn()` writes the completed turn back
- `get_tool_schemas()` and `handle_tool_call()` expose provider-specific memory tools
- `on_pre_compress()`, `on_session_end()`, and `on_memory_write()` keep learning from disappearing context, true session ends, and built-in memory writes

Hermes keeps one hard rule around this extension point: only one non-builtin provider is active at a time.

## Session Search And Cross-Session Recall

Hermes uses two distinct recall channels across sessions.

### Provider-backed recall

External providers keep their own long-term stores and use `prefetch()` or provider tools to bring old knowledge back into the live turn.

### Session-backed recall

`session_search` queries Hermes's own session database. It searches stored transcripts with FTS5, selects the top matching sessions, rebuilds readable transcripts, and summarizes them with the auxiliary model path. The point is not to dump raw logs back into context. The point is to recover what happened in earlier conversations in a compact, task-focused form.

This split is important for readers:

- providers answer "what durable knowledge should follow me across sessions?"
- `session_search` answers "what happened in past conversations about this topic?"

They are complementary, not duplicates.

## Boundary To Neighbor Pages

This page sits between three adjacent subsystem pages, and the boundary lines matter.

**Relative to [Prompt Assembly System](prompt-assembly-system.md)**

- prompt assembly owns stable memory layers in the cached system prompt
- this page owns when dynamic recall is fetched and injected at call time

**Relative to [Session Storage](session-storage.md)**

- session storage owns transcript persistence, FTS, replay, and lineage
- this page owns when `session_search` is invoked and how that recall participates in the live turn

**Relative to [Agent Loop Runtime](agent-loop-runtime.md)**

- the agent loop owns the overall turn sequence and decides where memory hooks fire
- this page explains what those hooks do once the loop reaches them

Keeping those boundaries clear prevents "memory" from turning into a vague umbrella for every durable context feature in Hermes.

## Source Evidence

| File | Why it matters for this page |
| --- | --- |
| `hermes-agent/run_agent.py` | Wires built-in memory, provider activation, `session_search`, memory flush, tool interception, nudges, and background review into the main runtime loop. |
| `hermes-agent/agent/builtin_memory_provider.py` | Shows the provider-form adapter for Hermes's file-backed memory and makes clear that built-in writes still happen through the intercepted `memory` tool. |
| `hermes-agent/agent/memory_manager.py` | Defines the manager contract for recall, sync, lifecycle, and provider tool routing, including the one-external-provider limit. |
| `hermes-agent/agent/memory_provider.py` | Defines the external-provider lifecycle, including recall, sync, compression, session-end, memory-write, and delegation hooks. |
| `hermes-agent/tools/session_search_tool.py` | Implements cross-session recall from SQLite transcripts through FTS search plus auxiliary summarization. |
| `hermes-agent/plugins/memory/__init__.py` | Shows discovery and activation of repository-bundled memory providers. |
| `hermes-agent/plugins/memory/honcho/__init__.py` | Example of a provider with context, tools, and hybrid recall modes plus background prefetching. |
| `hermes-agent/plugins/memory/hindsight/__init__.py` | Example of a provider that supports automatic recall and explicit reflective search tools. |
| `hermes-agent/plugins/memory/openviking/__init__.py` | Example of a provider that commits sessions on shutdown to trigger backend memory extraction. |
| `hermes-agent/website/docs/developer-guide/architecture.md` | Confirms memory as one of the major runtime subsystems around `AIAgent`. |
| `hermes-agent/website/docs/developer-guide/agent-loop.md` | Maintainer-facing walkthrough of memory flush, intercepted tools, and runtime integration points. |

## See Also

- [Agent Loop Runtime](agent-loop-runtime.md)
- [Prompt Assembly System](prompt-assembly-system.md)
- [Session Storage](session-storage.md)
- [Skills System](skills-system.md)
- [Cross-Session Recall And Memory Provider Pluggability](../concepts/cross-session-recall-and-memory-provider-pluggability.md)
- [Compression, Memory, And Session Search Loop](../syntheses/compression-memory-and-session-search-loop.md)
