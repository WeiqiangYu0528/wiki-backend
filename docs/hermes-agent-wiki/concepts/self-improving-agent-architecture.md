# Self-Improving Agent Architecture

## Overview

Hermes is "self-improving" in a narrow, implementation-driven sense: useful outcomes from one run can change what the next run sees. It does not rely on one giant learning bucket. Instead, it keeps several persistence channels with different jobs:

- memory for stable facts and preferences
- session storage and search for transcript history
- skills for reusable procedures
- provider-backed recall for richer external memory
- nudges and review logic for deciding when something should be saved at all

That separation is the design idea. Facts, past transcripts, and reusable workflows age differently, need different retrieval strategies, and should not be written with the same rules. Hermes treats them as one closed loop because they cooperate at runtime, but keeps them separate so learning stays legible and controllable.

## How the Loop Works

### 1. Hermes starts with several durable stores, not one

Before a turn begins, Hermes may already have:

- local persistent memory in `MEMORY.md` and `USER.md`
- an optional external memory provider activated through the memory-provider plugin path
- a SQLite-backed session database containing prior transcripts, titles, summaries, and searchable history
- a local skills catalog under `~/.hermes/skills/`

These stores are related, but not interchangeable. Session history preserves what happened. Memory preserves compact facts. Skills preserve procedures.

### 2. Prompt assembly exposes stable guidance and recall hooks

At session start, the runtime builds a cached system prompt that can include stable memory and skill guidance. The prompt builder also teaches the model to save durable facts with `memory`, use `session_search` for prior transcript context, and save reusable workflows with `skill_manage`.

The runtime does not expect the model to infer this architecture from tool names alone. It tells the model what kind of knowledge belongs where.

### 3. Before and during the turn, Hermes retrieves context through different channels

Hermes then makes current context richer in more than one way:

- built-in memory contributes compact persistent facts directly to the prompt path
- external memory providers can prefetch recall context before the tool loop begins
- `session_search` can query prior sessions when the user refers to earlier work or when cross-session context may matter
- skills can be listed, loaded, and followed when the task matches an existing procedure

This is the first half of the loop: previous work becomes available to the current run, but only through the right surface.

### 4. During execution, the agent can write to the right persistence layer

As the turn unfolds, the model may discover that some result deserves to survive the session. Hermes gives it different write paths for different outcomes:

| Artifact type | Where it lives | What belongs there | What does not |
| --- | --- | --- | --- |
| Stable memory | `MEMORY.md`, `USER.md`, or provider-backed memory | user preferences, environment facts, durable conventions, recurring corrections | task logs, one-off outcomes, long procedures |
| Session history | SQLite session DB and transcript storage | full conversation history, searchable past turns, resume/replay state | distilled facts for every future prompt |
| Skills | `~/.hermes/skills/` and external skill dirs | repeatable workflows, exact steps, pitfalls, verification guidance | user profile facts, raw transcripts |
| Compression summaries | compressed session artifacts | reduced context for long-running sessions | canonical long-term memory or reusable procedures |

The prompt builder makes the distinction explicit: do not save task progress or completed-work logs to memory; use `session_search` for those, and use skills for non-trivial workflows.

### 5. After the turn, Hermes syncs and reviews

Once a response is produced, Hermes updates its learning surfaces in two ways. First, the memory path can synchronize immediately. `run_agent.py` calls `sync_all()` on the memory manager with the completed turn and queues the next provider prefetch.

Second, Hermes can run a background review pass. The runtime tracks two counters:

- turns since memory was last used
- tool-loop iterations since skills were last updated

When those thresholds are crossed, Hermes can fork a quiet review agent after the user-facing response is already delivered. That review agent inspects the completed conversation and may write to shared memory or create or patch a skill.

### 6. Long sessions are compressed, but compression is not the same as learning

When a session grows too large, Hermes compresses older context so the conversation can continue. Compression helps the current session survive context pressure, but it does not replace session search, memory, or skills.

### 7. Future runs start from changed state

The loop closes on the next task:

1. a stored fact may now appear in prompt memory
2. an external provider may recall relevant context during prefetch
3. `session_search` may surface a prior transcript instead of asking the user to repeat it
4. a newly created or patched skill may now be available as a reusable procedure

That is the practical meaning of self-improvement in Hermes. Future runs can be better because previous runs changed durable artifacts the runtime knows how to reload.

## Why Hermes Does Not Collapse Learning Into One Mechanism

Hermes keeps multiple learning artifacts because each one answers a different question:

- "What stable fact should the model keep seeing?" leads to memory.
- "What exactly happened in that old conversation?" leads to session storage and search.
- "What step-by-step workflow worked well enough to reuse?" leads to skills.
- "What richer cross-session context should an external backend recall?" leads to a memory provider.

If these were collapsed into one store, Hermes would lose important guarantees:

- memory would fill with noisy transcripts and temporary task state
- session history would be polluted with normative instructions instead of raw chronology
- skills would become vague summaries instead of executable procedures
- provider-backed recall would become harder to reason about because it would mix fact storage, transcript replay, and procedural assets

"Learning" means routing information into the right persistence layer, not maximizing how much gets saved.

## Boundaries and Invariants

Several boundaries make the system predictable.

- Memory is for durable facts, preferences, and conventions. It is deliberately compact and should reduce future user correction.
- Session storage is the historical record. It supports resume, search, lineage, and replay, but it is not itself the agent's procedural memory.
- Skills are procedural assets. They describe how to do recurring work and can be created or patched through `skill_manage`, but they do not replace memory or transcript search.
- Provider-backed memory extends recall, but it does not erase the distinction between built-in memory, session DB search, and the skill catalog.
- Only one external memory provider is active at a time, which keeps the recall contract narrow even though the broader plugin system is more open-ended.
- Post-task review is best-effort. Hermes can reflect on a finished run and save useful artifacts, but it still writes into the same bounded stores.

These invariants are what make the architecture teachable.

## Source Evidence

- [memory-and-learning-loop.md](../entities/memory-and-learning-loop.md) explains how built-in memory, provider recall, `session_search`, post-turn sync, and session-end hooks fit into the runtime.
- [skills-system.md](../entities/skills-system.md) explains the skills catalog, prompt exposure, direct skill tools, and the difference between procedural knowledge and memory.
- [session-storage.md](../entities/session-storage.md) explains the SQLite session database, transcript persistence, replay, and why session search is a history surface rather than a memory surface.
- [plugin-and-memory-provider-system.md](../entities/plugin-and-memory-provider-system.md) explains why memory providers are a separate family from general plugins and why only one external provider is active at a time.
- `run_agent.py` wires the loop together: it loads memory and providers, tracks `_turns_since_memory` and `_iters_since_skill`, prefetches provider recall, syncs memory after successful turns, and spawns background review for memory and skill harvesting.
- `agent/prompt_builder.py` encodes the policy distinction in the system prompt: save durable facts to memory, use `session_search` for past transcript context, and save proven workflows as skills.
- `tools/skill_manager_tool.py` defines `skill_manage`, the write surface for creating, patching, editing, and deleting skill assets that turn successful procedures into reusable instructions.

## See Also

- [Memory and Learning Loop](../entities/memory-and-learning-loop.md)
- [Skills System](../entities/skills-system.md)
- [Session Storage](../entities/session-storage.md)
- [Plugin and Memory Provider System](../entities/plugin-and-memory-provider-system.md)
- [Cross-Session Recall and Memory Provider Pluggability](cross-session-recall-and-memory-provider-pluggability.md)
- [Compression Memory and Session Search Loop](../syntheses/compression-memory-and-session-search-loop.md)
