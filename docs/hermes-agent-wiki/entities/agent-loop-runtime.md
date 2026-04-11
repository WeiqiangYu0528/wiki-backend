# Agent Loop Runtime

## Overview

`AIAgent` in `run_agent.py` is the execution core that turns a user turn into a completed assistant turn. Hermes has several shells around it, including the [CLI Runtime](cli-runtime.md), the [Gateway Runtime](gateway-runtime.md), ACP editor sessions, cron entrypoints, and batch flows, but those shells mostly prepare inputs and consume outputs. They do not reimplement the actual model-and-tool loop.

That is why this page is a hub page. If you want to understand where Hermes builds prompts, switches providers, decides to compress history, intercepts agent-local tools, persists session state, or recovers from failures, you usually end up back at `AIAgent.run_conversation()`.

The most useful mental model is this:

- shells own transport, routing, UI, approvals, and session orchestration
- `AIAgent` owns turn execution
- adjacent subsystems plug into specific points inside that turn execution

Read this page as a runtime handbook, not just a class summary. The important question is not only "what does `AIAgent` do?" but "in what order does it do it, and where do other Hermes subsystems enter that order?"

## What `AIAgent` Owns

`AIAgent` owns the invariants of a single conversational turn. Once a shell has chosen the session, gathered history, and instantiated the runtime, `AIAgent` is responsible for keeping the rest of the turn coherent.

In practice that means it owns:

- the canonical internal message history format used across providers
- the turn loop in `run_conversation()`, including repeated model calls after tool results
- system-prompt caching and rebuilds after compression events
- API-mode selection and normalization for chat completions, Codex Responses, and Anthropic Messages
- interrupt-aware model calls, retries, and provider fallback activation
- tool execution, including both normal registry dispatch and agent-intercepted tools
- turn-local callbacks for progress, thinking, reasoning, streaming, and status
- token accounting, compression triggers, and end-of-turn persistence

It does not own everything around the conversation. It does not decide which inbound message to process next, how a Telegram or Discord event gets authorized, how terminal UI widgets render, or how a gateway session is paired and routed. Those belong to outer shells such as [Gateway Runtime](gateway-runtime.md), [CLI Runtime](cli-runtime.md), and [Messaging Platform Adapters](messaging-platform-adapters.md).

## Key Types And Runtime Anchors

The file is large, but a small set of methods and collaborators explain most of the runtime.

| Anchor | Kind | Collaborators | Why it matters |
| --- | --- | --- | --- |
| `IterationBudget` | Type | child agents, budget warnings | Counts loop iterations and lets the runtime decide when to warn or force wrap-up. |
| `AIAgent.__init__()` | Constructor | provider setup, callbacks, memory manager, tool surface | Establishes the runtime's long-lived state: API mode, tool schemas, session DB, memory providers, callbacks, compression settings, and prompt-cache behavior. |
| `AIAgent._build_system_prompt()` | Method | [`agent/prompt_builder.py`](prompt-assembly-system.md), memory stores, skills index | Builds the stable system prompt snapshot that Hermes tries to reuse across turns for cache stability. |
| `AIAgent.run_conversation()` | Method | provider clients, plugin hooks, tool dispatch, persistence | The real runtime entry point. It appends the user turn, runs the model/tool loop, and returns the completed result object. |
| `AIAgent._invoke_tool()` | Method | [`model_tools.py`](tool-registry-and-dispatch.md), memory manager, agent-local tool handlers | Shows the split between registry-dispatched tools and tools the loop intercepts itself. |
| `AIAgent._execute_tool_calls()` | Method | thread pool, approval path, callbacks | Runs single or batched tool calls, preserves ordering, and decides when concurrency is safe. |
| `AIAgent._compress_context()` | Method | [`agent/context_compressor.py`](../concepts/prompt-layering-and-cache-stability.md), memory flush, session DB | Performs compaction, rebuilds the system prompt, and creates a continuation session lineage in SQLite. |
| `AIAgent._try_activate_fallback()` | Method | provider router, credentials, client rebuild | Swaps model, provider, client, and API mode in place when Hermes needs to fail over. |
| `AIAgent.chat()` | Method | `run_conversation()` | Convenience wrapper for surfaces that only need the final text instead of the full result dict. |

Two signatures define the public runtime surface:

```python
class AIAgent:
    def run_conversation(
        self,
        user_message: str,
        system_message: str = None,
        conversation_history: List[Dict[str, Any]] = None,
        task_id: str = None,
        stream_callback: Optional[callable] = None,
        persist_user_message: Optional[str] = None,
    ) -> Dict[str, Any]: ...

    def chat(self, message: str, stream_callback: Optional[callable] = None) -> str: ...
```

The important distinction is that `chat()` is ergonomic, but `run_conversation()` is architectural. All of Hermes's serious runtime behavior lives there.

## Lifecycle Of `run_conversation()`

The loop is easiest to understand as an ordered pipeline.

1. **Restore and sanitize turn state.** The method restores the primary runtime if the previous turn used a fallback provider, sanitizes invalid surrogate characters, stores the streaming callback, creates a fresh task ID when needed, and resets retry counters.

2. **Reset per-turn execution budget.** `run_conversation()` creates a fresh `IterationBudget` for the top-level turn and clears stale budget-pressure text from loaded history so old warnings do not poison future turns.

3. **Load and normalize conversation state.** The incoming history is copied, not mutated in place. If the gateway created a fresh `AIAgent` for this message, the loop can hydrate agent-local TODO state back out of prior tool results.

4. **Append the new user message.** The current user turn becomes the new tail of the internal OpenAI-style history. Hermes keeps this canonical message format even when the active provider is Anthropic or Codex Responses.

5. **Reuse or build the system prompt.** If the session already has a stored system prompt snapshot in SQLite, the loop reuses it. Otherwise it builds one from scratch through `prompt_builder.py`, memory blocks, skills indexing, context files, identity text, date metadata, and platform hints. This is where [Prompt Assembly System](prompt-assembly-system.md) enters the loop.

6. **Run preflight compression if the loaded history is already too large.** Before making any model call, the loop estimates request size including tool schemas. If the session is already over the compressor threshold, `_compress_context()` summarizes older turns, flushes memory, rebuilds the system prompt, and may split the SQLite session into a continuation lineage.

7. **Collect ephemeral per-turn context.** Plugin `pre_llm_call` hooks can add context for this turn, and external memory providers can prefetch recall text. Importantly, this extra context is injected into the API-facing user message, not into the stored system prompt, so Hermes preserves prompt-cache stability across turns. This behavior is central to [Prompt Layering And Cache Stability](../concepts/prompt-layering-and-cache-stability.md).

8. **Enter the tool-capable model loop.** Each loop iteration consumes budget, fires `step_callback` for surfaces that track progress, and builds `api_messages` from the persisted history plus ephemeral overlays:
   - current-turn memory/provider recall
   - plugin-injected user context
   - ephemeral system prompt additions
   - optional prefill messages
   - Anthropic cache-control markers
   - sanitization of tool-call structure for strict providers

9. **Make an interrupt-aware provider call.** The runtime prefers the streaming path even when no UI is visibly streaming, because streaming gives it better health checks and stale-connection detection. Provider-specific formatting and parsing differences are pushed to the edges, but `AIAgent` still owns the decision to call the correct transport and normalize the result back into one internal shape. This is where [Provider Runtime](provider-runtime.md) enters.

10. **Account for usage and handle transport failures.** On success, the loop updates token counts, cost estimates, prompt-cache stats, and session DB counters. On failure, it decides whether to retry, refresh credentials, compress context, treat a disconnect as a context overflow, or activate fallback.

11. **If the model returned tool calls, execute them and continue.** The assistant tool-call message is appended to history, the loop dispatches the tools, appends ordered tool results, optionally refunds cheap `execute_code` iterations, may emit user-facing context-pressure warnings, and may trigger post-tool compression before the next model call.

12. **If the model returned a final answer, close the turn.** The loop appends the final assistant message, strips user-facing `<think>` blocks, persists the session, fires plugin post-turn hooks, syncs external memory providers, schedules best-effort background memory or skill review, and returns the full result dict.

That sequence is why Hermes shells stay consistent. The gateway, CLI, and ACP surfaces can differ a lot in transport and presentation, but once they hand control to `run_conversation()`, they traverse the same runtime machine.

## Where Adjacent Subsystems Enter The Loop

The runtime is not monolithic. It is a coordinator with several collaborators that enter at distinct points.

| Subsystem | Where it enters | What it contributes |
| --- | --- | --- |
| [`agent/prompt_builder.py`](prompt-assembly-system.md) | system-prompt build or rebuild | Identity text, tool-aware guidance, skills snapshot, context-file loading, timestamp lines, and platform hints. |
| [`model_tools.py`](tool-registry-and-dispatch.md) and `tools/registry.py` | tool-surface setup and normal dispatch | The model-visible tool schema set and the default `handle_function_call()` path for ordinary tools. |
| [`agent/context_compressor.py`](../syntheses/compression-memory-and-session-search-loop.md) | preflight compression, post-tool compression, overflow recovery | Prunes old tool results, protects the head and tail of history, generates structured summaries, and repairs tool-call pairings after compaction. |
| `agent.memory_manager` and memory-provider plugins | prompt build, prefetch, tool interception, post-turn sync | Adds memory-provider prompt blocks, per-turn recall context, provider-owned tool calls, and post-response sync/prefetch work. |
| [`hermes_state.py`](session-storage.md) | session start, per-call accounting, end-of-turn persistence, session search | Stores the system prompt snapshot, appends messages, restores replayable history, maintains FTS-backed search, and records compression lineages through `parent_session_id`. |
| plugin hooks | session start, pre-LLM, pre-request, post-turn, session end | Let plugins attach context or observe runtime events without owning the loop itself. |
| shell callbacks | throughout the loop | `tool_progress_callback`, `thinking_callback`, `reasoning_callback`, `clarify_callback`, `step_callback`, `stream_delta_callback`, and `status_callback` let shells render progress without changing loop semantics. |

Two integration details are easy to miss:

First, prompt assembly is intentionally split between stable and ephemeral layers. Stable content goes into the cached system prompt. Ephemeral content, including recall text and plugin turn context, is kept out of that snapshot and injected later. This keeps cache behavior predictable instead of rebuilding the whole prompt every turn.

Second, persistence is not just an end-of-turn afterthought. Session storage shapes the loop in several places: it can provide the prior system prompt for cache reuse, replay messages in provider-compatible form, power `session_search`, and record compression continuations as a parent-child session chain. That is why [Session Storage](session-storage.md) is adjacent to the loop rather than merely downstream from it.

## Special-Case Tool Paths

Most Hermes tools follow the normal route: the model emits a tool call, `AIAgent` hands it to `handle_function_call()`, and the registry locates the concrete implementation. That default path is documented in [Tool Registry And Dispatch](tool-registry-and-dispatch.md).

Some tools do not take that route. `AIAgent` intercepts them before normal registry dispatch because they need direct access to agent-local state, current callbacks, or runtime-only collaborators.

| Tool path | Owner inside the loop | Why it bypasses normal registry dispatch |
| --- | --- | --- |
| `todo` | `self._todo_store` | TODO state is agent-local, may need hydration from session history, and is frequently injected back into compressed context. |
| `session_search` | `self._session_db` | It queries the agent's current session database and needs the active session ID to avoid blind global search. |
| `memory` | built-in memory store plus memory-provider bridge | Built-in memory writes update on-disk memory files and also notify external memory providers when appropriate. |
| memory-provider tools | `self._memory_manager` | Provider plugins can expose extra tools that are not part of the static core registry. |
| `clarify` | `clarify_callback` from the shell | The tool is interactive by definition, so the loop must hand control back to the shell that can actually ask the human. |
| `delegate_task` | parent `AIAgent` | Delegation needs the live parent agent so child agents inherit runtime context, toolsets, and interruption behavior. |

This split matters because it shows that not every "tool" in Hermes is just a registry entry. Some are really loop extensions that happen to be model-visible as tool schemas.

That also explains the shell boundary. A shell owns the human interaction channel needed by `clarify`, but it does not own the logic that decides when `clarify` was called, how that result is inserted into history, or how the loop resumes afterward. The loop owns that.

## Budgets, Fallback, Compression, And Failure Handling

These mechanisms are not side features. They are part of the runtime contract.

**Iteration budgets.** The loop checks budget on every model iteration, not only at the end. Budget pressure is communicated back to the model by appending warnings to tool-result content instead of inserting new standalone messages that could break role alternation or invalidate cache assumptions. If the turn exhausts its budget, `_handle_max_iterations()` produces a forced wrap-up path.

**Fallback activation.** `_try_activate_fallback()` does more than swap a model string. It rebuilds the provider client, updates `provider`, `model`, `base_url`, and `api_mode`, and re-evaluates whether prompt caching should stay enabled. Fallback can trigger after malformed responses, rate limiting, quota issues, or non-recoverable client errors, depending on which recovery paths have already been tried.

**Compression.** The compressor works in phases rather than brute-force truncation:

1. prune old tool-result payloads when they are large and no longer recent
2. protect the conversation head
3. protect the tail by token budget rather than fixed message count
4. summarize the middle into a structured handoff
5. sanitize tool-call pairs so the replayed history still satisfies provider rules

Compression also has side effects outside the message list. Before compaction, the loop flushes memory so durable facts are not lost. After compaction, it invalidates and rebuilds the system prompt, clears file-read dedup state, and may create a new SQLite session whose `parent_session_id` points at the pre-compression session.

**Failure handling.** `run_conversation()` has a deliberately layered recovery model:

- sanitize and retry once for surrogate-character encoding failures
- refresh credentials for provider-specific auth failures when possible
- interpret some 400/413/429/server-disconnect cases as context-overflow signals and compress instead of aborting
- fall back to alternate providers when retries are not likely to help
- preserve message-structure invariants by filling missing tool results on exception paths

The result is that long-running Hermes sessions can degrade gracefully instead of turning a single provider hiccup into a broken conversation transcript.

## Ownership Boundaries

The cleanest way to read Hermes is to separate shell ownership from loop ownership.

| Owner | Owns | Does not own |
| --- | --- | --- |
| Shells such as [CLI Runtime](cli-runtime.md), [Gateway Runtime](gateway-runtime.md), ACP, cron, and batch entrypoints | inbound transport, session selection, authorization, routing, UI rendering, approval UX, platform delivery, callback wiring, working-directory or platform setup | model/tool execution semantics, provider retry policy, compression timing, tool-result ordering, final transcript structure |
| `AIAgent` and `run_conversation()` | turn execution, prompt reuse and rebuild, provider-call loop, tool execution, interrupts, fallback, budget checks, per-turn persistence, end-of-turn sync hooks | gateway pairing, terminal layout, platform delivery semantics, session expiry policy, long-lived message queues |
| Adjacent subsystems such as [Prompt Assembly System](prompt-assembly-system.md), [Tool Registry And Dispatch](tool-registry-and-dispatch.md), [Session Storage](session-storage.md), and [Memory And Learning Loop](memory-and-learning-loop.md) | specialized services that the loop calls at defined points | overall conversational control flow |

The most important boundary to state explicitly is this: shells prepare for the loop, but they do not own the loop.

They choose when to call `run_conversation()`, which history to pass in, which callbacks to attach, and how to present intermediate status. Once the call starts, `AIAgent` owns message ordering, tool execution order, provider normalization, retry behavior, fallback activation, compression, and persistence.

That boundary is what lets Hermes have many shells without fragmenting into many agent runtimes.

## Source Files

| File | Why it matters for this page |
| --- | --- |
| `hermes-agent/run_agent.py` | Defines `IterationBudget`, `AIAgent`, the tool loop, fallback activation, callbacks, compression entrypoints, and end-of-turn persistence. |
| `hermes-agent/website/docs/developer-guide/agent-loop.md` | Maintainer-facing walkthrough of the same loop, including API modes, callbacks, intercepted tools, and compression behavior. |
| `hermes-agent/agent/prompt_builder.py` | Builds the stable system-prompt layers and explains why prompt assembly is partly cache-oriented. |
| `hermes-agent/agent/context_compressor.py` | Implements structured compaction, tail protection, iterative summary updates, and tool-pair repair after compression. |
| `hermes-agent/hermes_state.py` | Provides session creation, prompt snapshot storage, message persistence, FTS-backed search, and parent-child session lineage. |

## See Also

- [Architecture Overview](../summaries/architecture-overview.md)
- [Prompt Assembly System](prompt-assembly-system.md)
- [Provider Runtime](provider-runtime.md)
- [Tool Registry And Dispatch](tool-registry-and-dispatch.md)
- [Session Storage](session-storage.md)
- [Memory And Learning Loop](memory-and-learning-loop.md)
- [Compression, Memory, And Session Search Loop](../syntheses/compression-memory-and-session-search-loop.md)
- [CLI To Agent Loop Composition](../syntheses/cli-to-agent-loop-composition.md)
