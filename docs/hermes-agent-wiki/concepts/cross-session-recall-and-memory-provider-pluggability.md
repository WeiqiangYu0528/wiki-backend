# Cross-Session Recall and Memory Provider Pluggability

## Overview

Hermes supports cross-session recall by combining three bounded mechanisms: built-in memory, session search, and one active external memory provider. Each one remembers a different kind of thing.

Built-in memory holds durable user and project facts. Session search reaches back into previous transcripts. An external memory provider can add its own long-term store, prompt blocks, recall tools, and sync behavior.

## The Three Recall Paths

| Path | What it remembers | When it enters the turn | Why it exists |
| --- | --- | --- | --- |
| Built-in memory | Stable durable facts in `MEMORY.md` and `USER.md` | At system-prompt build time and through explicit memory writes | To give Hermes a small, always-on baseline of learned context |
| Session search | Prior conversations stored in `SessionDB` | Before a turn, when the runtime asks for relevant past sessions | To recover concrete prior work from transcripts without replaying every old message |
| External memory provider | Provider-specific long-term knowledge or recall store | At startup, pre-turn recall, tool time, post-turn sync, and session end | To let one specialized backend participate in the loop without turning the runtime into a plugin soup |

## How The Mechanism Works

The retrieval path has two phases: before the turn and during the turn.

### Before The Turn

1. Hermes loads built-in memory.
   `MemoryStore` or the built-in memory provider reads `MEMORY.md` and `USER.md` so the agent starts from durable facts rather than a blank slate.

2. Hermes activates at most one external provider.
   `MemoryManager` accepts the built-in provider plus one external provider selected through config. If a second external provider is added, it is rejected. That prevents competing recall systems from exposing overlapping tools or writing contradictory state.

3. Hermes builds the stable system prompt.
   The built-in memory blocks and the external provider's static `system_prompt_block()` are folded into the cached prompt. This is stable content, not turn-specific recall.

4. Hermes prefetches turn-relevant recall.
`MemoryManager.prefetch_all()` asks the active external provider for context. If `session_search` is used, the runtime also queries `SessionDB` for older matching sessions and summarizes the hits into a compact recall block.

### During The Turn

1. The model can ask for memory explicitly.
   The built-in `memory` tool writes durable facts, and provider-specific memory tools can expose backend-specific search or remember operations.

2. The agent loop can query old sessions.
   `session_search` searches transcript history through FTS, loads matching conversations, and summarizes them so the model gets focused recall instead of raw logs.

3. Hermes can mirror built-in writes to the active provider.
   When the built-in memory tool updates `MEMORY.md` or `USER.md`, `MemoryManager.on_memory_write()` gives the active external provider a chance to mirror or observe that change.

4. At the end of the turn, Hermes syncs the provider.
   `MemoryManager.sync_all()` and `queue_prefetch_all()` let the provider store the completed turn and prepare recall for the next one.

That sequence is what makes cross-session recall feel continuous: durable memory shapes the prompt, live recall shapes the current turn, and session history gives Hermes a concrete transcript trail to search.

## Why The System Is Pluggable But Bounded

Hermes is pluggable in the memory layer, but only within a narrow slot.

General plugins can register tools and hooks broadly. Memory providers are different. They plug into the memory lifecycle itself, which means they can affect prompt construction, recall, tool exposure, compression, and session-end behavior.

The bounded design gives Hermes a few constraints that matter:

- built-in memory is always on
- exactly one external provider may be active
- dynamic recall is injected into the turn, not baked into the stored prompt
- session search stays separate from provider recall
- memory providers can extend the loop, but they do not replace the loop

Those constraints keep the runtime understandable. Hermes can swap memory backends, but it still has one memory policy.

## Built-In Memory, Session Search, And Provider Recall

Built-in memory, session search, and provider recall are complementary, not redundant.

### Built-in memory

Built-in memory is the durable baseline. It is file-backed, always present, and session-shaped. It is the place for facts Hermes should carry forward even if no external backend is configured.

### Session search

`session_search` is transcript recall. It does not store memory as a backend would. Instead, it searches `SessionDB`, finds relevant past sessions through FTS, and summarizes the matching transcript fragments for the live turn.

This matters because the search result is not generic memory. It is a recovered account of what happened in earlier conversations. That makes it good for "what did we do last time?" and bad for "what durable fact should always be remembered?".

### External provider recall

The external provider is the pluggable backend slot. It can contribute static prompt text, prefetch context, expose memory tools, sync the current turn, and react to compression or session-end events.

## Retrieval In Practice

The practical retrieval path is easier to understand as a loop around `run_conversation()`.

1. Agent startup loads the active memory stack.
   The built-in provider is always present. The external provider is activated from config if one is selected and available.

2. The system prompt is assembled from stable memory.
   Hermes folds in built-in memory blocks and any provider static text so the model starts with durable context.

3. Pre-turn recall is fetched separately.
   External provider prefetch and `session_search` both contribute turn-specific recall without mutating the stable prompt.

4. The model receives the current user turn plus recalled context.
   That context is fenced or summarized so it stays informational rather than becoming accidental user content.

5. The model can write memory or request more recall during the turn.
   Memory tools and provider tools are available through the normal tool surface.

6. After the turn, Hermes syncs and queues the next recall.
   The provider can store the completed turn, and the next call can start with better recall than the previous one.

This is the key design point: memory affects both the current turn and future turns.

## Invariants And Implications

The most important invariants are simple but strict.

| Invariant | Why it matters |
| --- | --- |
| Built-in memory is always active | Hermes always has a baseline of durable facts even without an external backend |
| Only one external provider can be active | Prevents tool schema bloat and conflicting memory stores |
| Recall is injected at call time | Keeps the system prompt stable and cacheable |
| Session search is separate from provider recall | Prevents transcript replay from masquerading as provider memory |
| Memory providers participate in the loop, but do not own it | Keeps memory extensible without letting it absorb the whole agent runtime |

Session search tells Hermes what happened in earlier sessions. Built-in memory tells Hermes what durable facts it should keep. An external provider tells Hermes what its own backend remembers. Those are related, but they are not the same layer.

## Step Order For A Recall-Aware Turn

You can read the whole pattern as one ordered path:

1. Hermes starts the turn with built-in memory already loaded.
2. If configured, Hermes activates one external memory provider.
3. Hermes assembles the stable system prompt from durable memory blocks.
4. Hermes prefetches turn-relevant recall from the provider and/or `session_search`.
5. Hermes injects that recall into the live turn as background context.
6. The model may call memory tools or session search again during the turn.
7. Hermes writes any durable updates back to built-in memory and the active provider.
8. Hermes queues prefetch for the next turn so the next session starts with better recall.

That loop is what makes memory useful without letting it become uncontrolled transcript replay.

## Source Evidence

The implementation evidence for this pattern comes from:

- `hermes-agent/agent/memory_provider.py` for the external memory-provider contract and its one-provider lifecycle
- `hermes-agent/agent/memory_manager.py` for provider orchestration, recall injection, sync, and the one-external-provider rule
- `hermes-agent/tools/session_search_tool.py` for FTS-backed session recall and transcript summarization
- `hermes-agent/run_agent.py` for prompt assembly, prefetch, tool wiring, memory writes, compression hooks, and post-turn sync
- `hermes-agent/website/docs/developer-guide/agent-loop.md` for the maintainer-facing description of the same runtime contract

## See Also

- [Memory and Learning Loop](../entities/memory-and-learning-loop.md)
- [Session Storage](../entities/session-storage.md)
- [Plugin and Memory Provider System](../entities/plugin-and-memory-provider-system.md)
- [Agent Loop Runtime](../entities/agent-loop-runtime.md)
- [Prompt Assembly System](../entities/prompt-assembly-system.md)
- [Cross-Session Recall and Memory Provider Pluggability](../concepts/cross-session-recall-and-memory-provider-pluggability.md)
- [Compression, Memory, And Session Search Loop](../syntheses/compression-memory-and-session-search-loop.md)
