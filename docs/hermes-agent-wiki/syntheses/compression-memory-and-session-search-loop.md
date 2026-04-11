# Compression, Memory, And Session Search Loop

## Overview

Hermes keeps long sessions usable by separating three jobs that look similar but are not the same: compression keeps the active window small enough to continue, memory preserves durable facts, and session search recovers older transcripts when the user asks about prior work.

These mechanisms cooperate, but they do not collapse into one another. Compression is not learning, memory is not transcript replay, and session search is not another memory provider. This page follows the loop in order: what gets prepared before compression, what happens when a long turn is compacted or forked, and how later recall returns.

## Systems Involved

The loop sits between the [Prompt Assembly System](../entities/prompt-assembly-system.md), [Memory and Learning Loop](../entities/memory-and-learning-loop.md), and [Session Storage](../entities/session-storage.md). The [Agent Loop Runtime](../entities/agent-loop-runtime.md) decides when the hooks fire, while `context_compressor.py`, `memory_manager.py`, `session_search_tool.py`, and `hermes_state.py` provide the concrete mechanisms.

The main pieces are `agent/context_compressor.py` for summarization, `agent/memory_manager.py` for provider orchestration, `tools/session_search_tool.py` for transcript recall, `hermes_state.py` for persistence and FTS5, and `run_agent.py` for runtime wiring.

The boundary is simple: compression keeps the current turn viable, memory preserves durable knowledge, and session search recovers prior transcripts later.

## Interaction Model

The loop is easiest to understand as a sequence around one conversation.

### 1. The session starts with stable prompt context

Before any compression is needed, Hermes assembles a stable system prompt. That prompt can include frozen built-in memory, user profile material, and any provider system block.

### 2. The conversation grows until compression becomes necessary

`ContextCompressor` watches token usage and rough preflight estimates. When the active context crosses its threshold, Hermes prepares the turn before it starts dropping old messages.

### 3. Before compression, Hermes gives memory a last chance to persist durable facts

When compression is about to happen, `run_agent.py` can call a memory flush path so the model gets one last chance to save durable facts such as user preferences, recurring corrections, or stable workflow knowledge.

Then `MemoryManager.on_pre_compress(...)` lets active providers inspect the messages that are about to be compacted.

### 4. Compression summarizes the middle and preserves the useful edges

`ContextCompressor` does not summarize everything equally. It follows a specific policy:

- prune old tool outputs cheaply before the model is asked to summarize
- protect the opening messages
- protect the most recent tail of the conversation by token budget
- summarize the middle with a structured auxiliary-model pass
- update the previous summary iteratively on later compactions

The output is a compressed session history that keeps the conversation headed in the right direction without retaining every intermediate token.

### 5. Continuation and fork preserve lineage instead of erasing the old session

After compression, Hermes may continue the conversation in a child session or fork the session into a new branch. `SessionDB` stores that relationship with `parent_session_id`.

This is how Hermes says that the active conversation continued from an earlier one rather than replacing it. The parent remains searchable and auditable, while the child becomes the new live lane.

- compression may change the shape of the live context
- it does not delete the earlier session's provenance
- forks and continuations stay connected to the transcript that produced them

### 6. Later recall returns through memory or session search, depending on the question

When the user asks for durable facts or wants the model to remember a stable preference, memory is the right path. When the user asks about something that happened in a prior conversation, `session_search` is the right path.

Those two recall channels are complementary:

- memory is for durable facts, preferences, and provider-backed knowledge
- session search is for transcript-level recall of previous work

`session_search` does not re-implement memory. It searches SQLite session history with FTS5, loads matching transcripts, and summarizes the relevant sessions with an auxiliary model.

That is the post-recall boundary: the summary re-enters the live turn as context, but the transcript stays in session storage.

## Compression, Memory, And Session Search

| Mechanism | Owns | Input | Output | What it is not |
| --- | --- | --- | --- | --- |
| Compression | Active-window management | The current conversation buffer | A smaller live context plus a compressed summary | Learning, storage, or transcript search |
| Memory | Durable facts and provider-backed recall | User preferences, stable knowledge, completed-turn signals | Updated memory state and optional recall blocks | Transcript replay |
| Session search | Cross-session transcript recall | Stored sessions and search terms | Focused summaries of earlier conversations | A memory provider or a summary of the current turn |

This table is the core mental model for the page. The three systems cooperate, but each one answers a different question.

## What Happens Before And After Compression

### Before compression

Before the compressor runs, Hermes preserves knowledge in two places: the memory layer, through a flush or provider pre-compress hook, and the session transcript, through lineage-aware storage.

### During continuation or fork

Once compression has produced a smaller session, Hermes can continue in place or create a child session. The child inherits the conversation lineage through `parent_session_id`, and the storage layer keeps both sides available.

### After compression, during later recall

When a later turn needs to recover earlier work, Hermes chooses the recall path based on intent: use memory for durable facts and `session_search` for prior conversation evidence.

## Why Compression Is Not Learning

Compression and learning solve different problems. Compression fits a conversation into the model's context window; learning writes memory, syncs a provider, or updates a skill after the turn. Hermes keeps those jobs distinct so later turns can tell whether a fact belongs in memory or only in the compressed transcript.

## Key Interfaces

| Boundary | What crosses it | Who owns the next step |
| --- | --- | --- |
| Prompt assembly -> live turn | Stable memory blocks and system prompt baseline | The agent loop decides when the turn is built and reused |
| Agent loop -> memory manager | Pre-compress signal, turn completion, memory-query request | Memory providers decide whether to persist or prefetch recall |
| Agent loop -> compressor | Current message buffer and token pressure | The compressor decides what to prune, summarize, and preserve |
| Session storage -> later recall | Persisted messages, session metadata, lineage | `session_search` turns stored transcripts into focused summaries |

These handoffs keep the loop understandable. Each subsystem gets one responsibility and one kind of data to own.

## Source Evidence

This synthesis is grounded in these implementation files and docs:

- `hermes-agent/agent/context_compressor.py` for compression thresholds, pruning, tail protection, and structured summarization
- `hermes-agent/agent/memory_manager.py` for provider orchestration, pre-compress hooks, sync hooks, and the one-external-provider rule
- `hermes-agent/tools/session_search_tool.py` for FTS5 transcript search and auxiliary summarization of prior sessions
- `hermes-agent/hermes_state.py` for durable session rows, message rows, FTS5 triggers, and lineage via `parent_session_id`
- `hermes-agent/run_agent.py` for the runtime wiring that calls memory and compression hooks in the live turn
- `hermes-agent/website/docs/developer-guide/context-compression-and-caching.md` for the maintainer-facing explanation of the compression behavior

## See Also

- [Memory and Learning Loop](../entities/memory-and-learning-loop.md)
- [Session Storage](../entities/session-storage.md)
- [Prompt Assembly System](../entities/prompt-assembly-system.md)
- [Agent Loop Runtime](../entities/agent-loop-runtime.md)
- [Cross-Session Recall And Memory Provider Pluggability](../concepts/cross-session-recall-and-memory-provider-pluggability.md)
