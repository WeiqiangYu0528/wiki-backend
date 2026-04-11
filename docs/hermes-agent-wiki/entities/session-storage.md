# Session Storage

## Overview

Session storage is the continuity layer behind Hermes conversations. It is where a turn stops being a transient exchange and becomes something the runtime can restore, search, compress, resume, and extend later.

That matters before and after every turn. Before a model call, Hermes may need to recover prior messages, restore the last stable system prompt snapshot, or resume an old session by title. After the turn, it needs to persist the new transcript, update usage counters, preserve tool-call structure, and keep enough lineage to continue after compression without pretending the old context never existed.

The page therefore covers more than "Hermes uses SQLite". The real question is how persistence shapes runtime behavior. `hermes_state.py` owns the durable session database and replay/search behavior. `gateway/session.py` sits next to it as the shell-facing layer that maps live session lanes to persisted transcripts. Together they give Hermes long-lived conversational continuity across the CLI, the gateway, and restart boundaries.

## What Session Storage Owns

Session storage owns the durable record of a conversation and the helpers Hermes needs to work with that record later.

It owns:

- session rows in `SessionDB`, including source, user, model, system prompt snapshot, title, token and billing counters, timestamps, and lineage via `parent_session_id`
- message rows, including role, content, tool-call structure, tool result identity, finish reason, and assistant reasoning fields
- the FTS5 search index and triggers that keep search current as messages change
- replay helpers that convert stored rows back into provider-facing conversation format
- session title lookup and lineage-aware title continuation such as `resolve_session_by_title()` and `get_next_title_in_lineage()`
- transcript rewrite behavior used by flows such as retry, undo, and compression

It does not own everything with the word "session" in it. The gateway also has a session layer, but that layer is about routing identity and reset policy, not about how messages are stored internally. That boundary is important enough to make explicit later in this page.

## Key Types And Storage Anchors

| Anchor | Kind | What it stores or decides | Why it matters |
| --- | --- | --- | --- |
| `SessionDB` in `hermes_state.py` | SQLite owner | Canonical session rows, message rows, search index, migrations, and write behavior | This is the durable continuity core. |
| `sessions` table | Metadata table | Source, user, model, `system_prompt`, `parent_session_id`, timestamps, counters, billing fields, and title | The row explains what a session is and how it relates to later continuations. |
| `messages` table | Transcript table | Ordered messages, tool-call structure, finish reason, and reasoning payloads | This is what Hermes replays into later turns. |
| `messages_fts` plus triggers | Search index | FTS5 index synchronized on insert, update, and delete | Search stays live as part of normal runtime behavior. |
| `SessionStore` in `gateway/session.py` | Shell-facing bridge | Session-key mapping, reset behavior, transcript load/rewrite, and legacy JSONL compatibility | This is how the gateway reaches persisted history without owning database internals. |
| `build_session_key()` and `SessionSource` | Routing identity | Platform, chat, thread, and sometimes user-derived live lane identity | These choose the conversation lane, but they do not define SQLite storage layout. |

## What The Database Actually Stores

The SQLite database at `~/.hermes/state.db` is not just a message log. It stores enough structure for Hermes to restore behavior, not only text.

The `sessions` table stores the durable frame around a conversation:

- where the session came from, such as `cli`, `telegram`, or `discord`
- which user and model were involved
- the last assembled `system_prompt` snapshot
- token, reasoning, cache, and billing counters
- timestamps, end state, and a human-facing title
- `parent_session_id`, which links a continuation session back to the session it grew from

The `messages` table stores the turn-by-turn body:

- `role` and `content`
- `tool_calls`, `tool_call_id`, and `tool_name`
- `finish_reason`
- assistant reasoning fields such as `reasoning`, `reasoning_details`, and `codex_reasoning_items`

That last group matters because Hermes does not only replay plain chat text. When a later turn is restored, the runtime may need the tool-call structure and reasoning metadata to keep provider-specific replay coherent.

## How Storage Shapes Runtime Before A Turn

Storage changes what Hermes can do before the model is called.

First, it lets shells restore the conversation instead of starting blind. `SessionStore.load_transcript()` pulls history from SQLite through `get_messages_as_conversation()`, and for older sessions it can fall back to the longer legacy JSONL transcript so migration does not silently truncate context. That is the continuity path the [Gateway Runtime](gateway-runtime.md) uses when it prepares a new inbound message for the [Agent Loop Runtime](agent-loop-runtime.md).

Second, it lets the agent reuse the previously stored system prompt snapshot. The agent loop does not always rebuild the full prompt from scratch. If the session row already has `system_prompt`, that stored snapshot can be reused to preserve cache stability and avoid unnecessary prompt churn.

Third, storage gives Hermes ways to resume an existing conversation intentionally. Session titles, lineage-aware title lookup, and session switching let shells reopen or continue older conversations by identity rather than by keeping a process alive forever.

This is why session storage is not an after-the-fact logging feature. It actively shapes how much prior context the runtime sees when a turn begins.

## How Storage Shapes Runtime After A Turn

The storage layer also changes what Hermes can safely do once a turn finishes.

New messages are appended through `append_message()`. That does more than write text. It preserves tool-call payloads, increments message and tool counters, and keeps later replay structurally correct. Token and billing totals are updated on the session row, and `update_system_prompt()` can refresh the stored prompt snapshot when the prompt changes.

Some flows rewrite history instead of only appending to it. `rewrite_transcript()` is used by retry, undo, and compression paths when Hermes needs the durable transcript to match the runtime's new version of the conversation. In those cases, persistence is part of state correction, not just archival.

The end result is that the next turn sees a transcript Hermes can trust. Without that, retries, resumed sessions, and gateway restarts would all drift away from what the model actually saw earlier.

## Replay, Restore, And Search

Replay and search are where the value of structured storage becomes easiest to see.

### Replay and restore

`get_messages_as_conversation()` restores messages in the OpenAI-style conversation format the runtime expects internally. It rebuilds:

- roles and content
- tool-call lists and tool-call IDs
- tool names for tool-result messages
- assistant reasoning payloads when the provider supports replaying them

That is why the session database stores more than human-readable text. Replay needs the machine-readable structure too.

### Full-text search

Hermes also treats old sessions as something it can query. `messages_fts` is an FTS5 virtual table kept in sync by triggers on the `messages` table, so search stays current during normal writes.

`search_messages()` adds a few practical behaviors on top:

- sanitizes user-entered FTS queries so malformed search text does not crash SQLite matching
- joins search hits back to session metadata such as source and model
- returns snippets and nearby surrounding messages so matches are readable in context

This matters at runtime because tools such as `session_search` are not scraping logs offline. They are querying a live search surface that was designed into the persistence layer.

## Compression, Lineage, And Post-Compression Continuation

Compression is where session storage stops looking like a normal chat history table and starts looking like a lineage system.

Hermes does not have to pretend that a compressed conversation is still one unchanged transcript. When the agent loop compresses context, it can create a continuation session whose `parent_session_id` points at the earlier session. The child session becomes the live place where the conversation continues after summarization, while the parent session remains as the durable pre-compression record.

That design has three important effects.

First, it preserves provenance. A reader or tool can still see that the active conversation came from an earlier, fuller transcript.

Second, it keeps titles and resume behavior sensible. Title resolution prefers the latest session in a lineage, so continuing a named conversation after compression still feels like continuing the same conversation from the shell's point of view.

Third, it lets compression change storage shape without breaking continuity. The runtime can summarize the middle of a long transcript, start the next phase of the conversation in a child session, and still keep the old session available for audit or search.

This is the real reason `parent_session_id` matters. It is not just a database foreign key. It is how Hermes says, "this conversation continued after its old context was compacted."

## End-To-End Continuity Mechanism

The easiest way to see the whole subsystem is to follow one concrete shell-facing path from message arrival to later continuation.

Consider a Slack DM that later turns into a thread:

1. A new inbound DM arrives with a `SessionSource` that identifies Slack, the DM chat ID, and the user.
   `build_session_key()` turns that into the live lane key for this conversation. That key answers the shell question first: "which running conversation lane should receive this message?"

2. `SessionStore.get_or_create_session()` maps that lane key to a durable `session_id`.
   If the lane is new, it creates a new session entry and a new SQLite session row. If the lane already exists, it reuses the existing `session_id`.

3. Before the next model call, `SessionStore.load_transcript(session_id)` restores the durable history for that lane.
   That restore path pulls OpenAI-style conversation messages from SQLite through `get_messages_as_conversation()`, and it can prefer the longer legacy JSONL transcript when an older session has not been fully migrated yet.

4. The agent loop runs with that restored history and the stored session prompt snapshot.
   At this point the shell has already done its job. It chose the lane and recovered the matching transcript. The agent loop now sees a coherent prior conversation instead of a blank session.

5. After the turn, Hermes persists the new state for the same `session_id`.
   New messages are appended, counters are updated, and if the effective system prompt changed, the session row's `system_prompt` snapshot can be refreshed too.

6. Later, the bot's reply spawns a Slack thread and the user answers inside that thread.
   Now the inbound `SessionSource` includes the same DM chat plus a `thread_id`, so `build_session_key()` chooses a different live lane. That is a routing decision, not yet a storage decision.

7. `SessionStore` creates a new session for that thread lane, but it does not leave the thread empty.
   The gateway code explicitly seeds the new DM thread session with the parent DM transcript by loading the parent history and rewriting it into the new session. The lane changed because the shell now treats the thread as a separate live conversation space. The continuity did not reset, because durable transcript history was copied forward.

8. If that threaded conversation is later compressed, Hermes can create a continuation session whose `parent_session_id` points at the pre-compression session.
   The live lane still points at one active `session_id`, but storage now also records lineage across compression boundaries.

This is the full continuity mechanism in one path: shell lane selection chooses where a live message goes, transcript restore decides what history that lane sees, persistence records the new turn, and lineage keeps later continuations connected even when the storage shape changes.

## Shell-Facing Session Use Versus Persistence Internals

The word "session" refers to two neighboring but different responsibilities.

| Layer | Owns | Does not own |
| --- | --- | --- |
| Gateway routing layer in `gateway/session.py` | `SessionSource`, `build_session_key()`, reset policy, active session entry, and session-key to session-ID mapping | SQLite schema, FTS internals, message row format, lineage queries, and storage migrations |
| Persistence layer in `hermes_state.py` | Durable session rows, message rows, search index, replay format, title lookup, counters, and lineage | Platform routing identity, authorization, live inbound message policy, and delivery semantics |

The gateway needs a stable answer to "which live conversation lane does this inbound message belong to?" That is what `build_session_key()` and `SessionStore.get_or_create_session()` answer.

The storage layer answers different questions:

- what transcript belongs to this session ID
- how should the transcript be replayed into the next model call
- how can the transcript be searched later
- how does a continuation relate to its parent after compression

Keeping that boundary clear prevents page overlap with [Gateway Runtime](gateway-runtime.md). The gateway chooses the lane and prepares context. Session storage makes that lane durable and recoverable.

## Operational Takeaway

The practical test for this subsystem is not "did SQLite save something?" The practical test is whether Hermes preserves conversational continuity across shell events that change the live session shape.

In operational terms, continuity can fail in three different places:

- lane selection fails: the gateway maps a message to the wrong `session_key`, so the user lands in the wrong live conversation
- transcript restore fails: the lane is correct, but `load_transcript()` restores partial or stale history, so the next turn starts with the wrong memory
- lineage fails: compression or session switching creates a new durable session without a clear relationship to the old one, so resume, search, and later explanation become misleading

That is the sharper reason this page matters. Session storage is the contract that keeps those three layers aligned:

- shell-facing lane identity
- durable transcript replay
- post-compression continuation lineage

When those stay aligned, Hermes feels like one continuous conversation even across restarts, thread splits, retries, and compression. When they drift apart, the user experiences Hermes as forgetful, duplicated, or suddenly "in the wrong chat" even if the model itself is working correctly.

## Source Files

| File | Why it matters for this page |
| --- | --- |
| `hermes-agent/hermes_state.py` | Defines `SessionDB`, the SQLite schema, FTS triggers, title helpers, replay helpers, lineage fields, and write-contention behavior. |
| `hermes-agent/gateway/session.py` | Defines `SessionSource`, `build_session_key()`, `SessionStore`, transcript load/rewrite behavior, reset flow, and the shell-facing bridge into persisted sessions. |
| `hermes-agent/website/docs/developer-guide/session-storage.md` | Maintainer-oriented reference for the same schema, migrations, FTS behavior, and lineage design. |

## See Also

- [Agent Loop Runtime](agent-loop-runtime.md)
- [Gateway Runtime](gateway-runtime.md)
- [Prompt Assembly System](prompt-assembly-system.md)
- [Memory and Learning Loop](memory-and-learning-loop.md)
- [Multi-Surface Session Continuity](../concepts/multi-surface-session-continuity.md)
- [Compression, Memory, And Session Search Loop](../syntheses/compression-memory-and-session-search-loop.md)
