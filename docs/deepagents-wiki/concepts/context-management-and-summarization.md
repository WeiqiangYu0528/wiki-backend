# Context Management and Summarization

## Overview

Long-running agent sessions accumulate conversation history that eventually exceeds the context window of any language model. Without intervention, this causes hard failures (`ContextOverflowError`) or severe quality degradation as the model loses sight of earlier work.

The summarization system in deepagents solves this automatically. `SummarizationMiddleware` monitors token usage before every model call. When usage crosses a configurable threshold, it generates an LLM summary of the oldest messages, persists the raw history to a backend file, and replaces the bulky history with a compact summary message — all transparently, without interrupting the agent loop.

This keeps long sessions viable indefinitely while preserving a retrievable audit trail of everything that was discarded from the live context.

## Mechanism

### Trigger check (before every model call)

`SummarizationMiddleware.wrap_model_call()` (and its async counterpart `awrap_model_call()`) intercepts every request before it reaches the LLM. The steps are:

1. **Reconstruct effective messages.** If a prior summarization event exists in state (`_summarization_event`), the middleware replaces the raw message list with `[summary_message, ...messages[cutoff_index:]]` so the model always sees a logically consistent history.

2. **Truncate large tool arguments (optional pre-pass).** Before full summarization, the middleware can shorten oversized `write_file` / `edit_file` argument strings in older messages. This fires at a lower threshold than full compaction and is controlled by `truncate_args_settings`.

3. **Evaluate the summarization threshold.** `_should_summarize()` counts tokens across the effective message list plus system prompt and tools. Three threshold formats are supported:
   - `("tokens", N)` — trigger when total tokens exceed `N`.
   - `("messages", N)` — trigger when the message count exceeds `N`.
   - `("fraction", f)` — trigger when usage exceeds `f * max_input_tokens` from the model profile.

4. **Fallback on `ContextOverflowError`.** If the threshold is not yet met but the model call fails with `ContextOverflowError`, summarization runs immediately as an emergency fallback.

5. **Partition messages.** `_determine_cutoff_index()` picks where to split: everything before the cutoff is summarized; everything from the cutoff onward is preserved. The `keep` parameter controls the retention window (by message count, token count, or fraction of the context window).

6. **Offload to backend.** The messages being summarized are written to `/conversation_history/{thread_id}.md` in the configured backend. Each summarization event appends a new timestamped markdown section to that file. Offload failure is non-fatal — summarization still proceeds, but `file_path` in the event is `None`.

7. **Generate summary.** `_create_summary()` calls the configured model with the `DEFAULT_SUMMARY_PROMPT` to produce a condensed narrative.

8. **Build the summary message.** A `HumanMessage` is constructed with metadata `{"lc_source": "summarization"}`. When `file_path` is available, the message body references the offloaded file so the agent can retrieve details if needed:

   ```
   You are in the middle of a conversation that has been summarized.
   The full conversation history has been saved to {file_path} should you need to refer back to it for details.
   A condensed summary follows:
   <summary>{summary}</summary>
   ```

9. **Emit a `SummarizationEvent` state update.** The middleware returns an `ExtendedModelResponse` carrying a `Command` that writes `_summarization_event` into `SummarizationState`. This event records `cutoff_index`, `summary_message`, and `file_path`. Subsequent calls reconstruct the effective message list from this event rather than re-summarizing from scratch.

### On-demand compaction (`SummarizationToolMiddleware`)

`SummarizationToolMiddleware` wraps a `SummarizationMiddleware` instance and exposes a `compact_conversation` tool the agent (or a HITL approval flow) can invoke explicitly. It reuses the same summarization engine. The `REQUIRE_COMPACT_TOOL_APPROVAL` flag in `agent.py` gates this tool behind HITL approval by default.

### Model-aware defaults

`compute_summarization_defaults()` inspects the model's `profile.max_input_tokens`. When a profile is present it uses fraction-based settings:

```python
{"trigger": ("fraction", 0.85), "keep": ("fraction", 0.10)}
```

Without a profile it falls back to conservative fixed values:

```python
{"trigger": ("tokens", 170000), "keep": ("messages", 6)}
```

The convenience factory `create_summarization_middleware(model, backend)` — used inside `create_deep_agent()` — calls `compute_summarization_defaults()` and instantiates the middleware automatically.

## Involved Entities

- [Graph Factory](../entities/graph-factory.md) — `create_deep_agent()` calls `create_summarization_middleware()` and inserts the result into the middleware stack for both the main agent and each declarative subagent.
- [CLI Runtime](../entities/cli-runtime.md) — The CLI exposes a `/offload` command backed by `offload.py`, which manually triggers the same summarization workflow on demand.

## Source Evidence

**`libs/deepagents/deepagents/middleware/summarization.py`**

`SummarizationState` extends `AgentState` with a private field:
```python
class SummarizationState(AgentState):
    _summarization_event: Annotated[NotRequired[SummarizationEvent | None], PrivateStateAttr]
```

`SummarizationEvent` TypedDict:
```python
class SummarizationEvent(TypedDict):
    cutoff_index: int
    summary_message: HumanMessage
    file_path: str | None
```

Default fraction-based trigger/keep when model profile is known:
```python
{"trigger": ("fraction", 0.85), "keep": ("fraction", 0.10)}
```

`_DeepAgentsSummarizationMiddleware` constructor (all configurable parameters):
```python
def __init__(
    self,
    model: str | BaseChatModel,
    *,
    backend: BACKEND_TYPES,
    trigger: ContextSize | list[ContextSize] | None = None,
    keep: ContextSize = ("messages", _DEFAULT_MESSAGES_TO_KEEP),
    token_counter: TokenCounter = count_tokens_approximately,
    summary_prompt: str = DEFAULT_SUMMARY_PROMPT,
    trim_tokens_to_summarize: int | None = _DEFAULT_TRIM_TOKEN_LIMIT,
    history_path_prefix: str = "/conversation_history",
    truncate_args_settings: TruncateArgsSettings | None = None,
)
```

Emergency fallback in `wrap_model_call()`:
```python
if not should_summarize:
    try:
        return handler(request.override(messages=truncated_messages))
    except ContextOverflowError:
        pass  # Fallback to summarization on context overflow
```

State cutoff index computation for chained summarization events:
```python
return prior_cutoff + effective_cutoff - 1
```

**`libs/cli/deepagents_cli/offload.py`**

The `/offload` command stores evicted history at:
```python
path = f"/conversation_history/{thread_id}.md"
```

## See Also

- [Human-in-the-Loop Approval](human-in-the-loop-approval.md)
- [Local vs Remote Execution](local-vs-remote-execution.md)
- [Batteries-Included Agent Architecture](batteries-included-agent-architecture.md)
