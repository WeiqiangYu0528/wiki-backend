# Multi-Surface Session Continuity

## Overview

Hermes can move a conversation across the CLI, gateway, cron, and ACP without pretending those surfaces are literally the same session type. The core idea is simpler: each surface owns its own session identity, but Hermes preserves enough shared history, routing metadata, and lineage that the user experiences one continuous thread.

That is why "session continuity" is not just persistence. It is the combination of three things working together:

1. A surface-specific identity for the live turn.
2. Durable session storage for replay, search, and compression.
3. Shell metadata that tells Hermes where the conversation came from and where replies should go.

When those pieces stay aligned, Hermes can restart, switch surfaces, fork after compression, or deliver a response later without losing the thread.

## Session Meanings By Surface

| Surface | What "session" means here | What it does not mean |
| --- | --- | --- |
| CLI | A local shell session backed by `SessionDB`, with one conversation lane and one current runtime context | It does not mean the shell process itself is the durable conversation record |
| Gateway | A routing lane derived from platform, chat, thread, and optional user identity, mapped to a persisted session entry | It does not mean every incoming chat message gets a brand-new conversation |
| ACP | An editor-bound live session with a working directory, cancel state, and a persisted Hermes session record | It does not mean the editor transport replaces Hermes session storage |
| Cron | A fresh isolated run created for a due job, usually with its own session ID and prompt context | It does not mean the job is continuing an ordinary user chat session |

Each surface still chooses what counts as "the current session" for its own control flow.

## How Continuity Works

The mechanism is the same everywhere, even when the entrypoint changes.

1. Hermes identifies the surface and source.
   The CLI knows it is operating in a local terminal, the gateway knows the platform, chat, thread, and sender, ACP knows the editor workspace, and cron knows the job record and delivery target.

2. Hermes resolves a live session identity.
   The CLI resumes or creates a local session ID, the gateway computes a deterministic session key from the source, ACP binds its editor session to a Hermes session ID and cwd, and cron creates a fresh session for each due job.

3. Hermes loads or creates durable session state.
   `SessionDB` stores the persistent transcript, system prompt snapshot, lineage, and counters.

4. Hermes builds shell metadata for the agent.
   Source description, connected platforms, home channels, cwd, model choice, and other runtime hints become session context or prompt text.

5. Hermes runs the agent loop with the recovered history.
   The turn executes against the restored transcript instead of an empty prompt.

6. Hermes persists the new state after the turn.
   The next run can reuse the updated transcript, counters, prompt snapshot, and lineage.

The invariant is simple: the live surface can change, but the conversation thread remains coherent because the same durable record is being reattached through different surface-specific identities.

## Surface Mechanics

### CLI

The CLI is the simplest case. `cli.py` and `hermes_cli/main.py` assemble the local shell, choose or resume a session, and then hand off to `AIAgent`. Continuity here mostly means "resume the same SQLite-backed session instead of starting from scratch."

The local shell does not own the transcript by itself. It owns the local runtime context, while `SessionDB` owns the durable conversation record.

### Gateway

The gateway is continuity across message platforms. `gateway/session.py` turns platform, chat, thread, and sometimes user identity into a deterministic routing key. That routing key is then mapped to a session entry and transcript through `SessionStore`.

This is why the gateway can keep a Telegram thread, a Slack DM, or a Discord channel aligned with a durable conversation.

The gateway also adds shell-specific metadata such as source description, home channels, pairing state, and reset policy.

### ACP

ACP continuity is editor-bound. `acp_adapter/session.py` keeps a live in-memory `SessionState`, but it also persists the session to the shared `SessionDB`.

ACP sessions also register a task-specific cwd override so terminal and file tools execute relative to the editor workspace rather than the server process directory.

### Cron

Cron is the deliberate exception. Scheduled jobs do not continue an ordinary interactive session. They start in a fresh, isolated run with a fresh session ID, loaded job prompt, job-specific skills, and explicit delivery routing.

That isolation is a feature, not a loss of continuity. Cron gives the job its own short-lived conversation and saves the result separately.

## Boundaries And Implications

The key boundary is between live routing identity and durable session storage.

| Layer | Owns | Does not own |
| --- | --- | --- |
| Surface routing | How a CLI run, gateway message, ACP editor session, or cron job identifies the live turn | The SQLite schema or transcript format |
| Session storage | Durable transcript, system prompt snapshot, lineage, search index, and replay helpers | Platform-specific routing rules or editor cwd state |
| Shell metadata | Source context, home channels, cwd, model choice, reset policy, and delivery hints | The agent loop itself |

That separation gives Hermes a few important guarantees:

- A restart does not lose the conversation, because the transcript lives in `SessionDB`.
- A gateway message is not confused with a different chat, because session keys are derived from source context.
- An ACP session can survive reconnects, because the session record is persisted and the cwd binding is restored.
- A compressed or continued conversation can still point back to its predecessor, because `parent_session_id` records lineage.
- A cron job stays isolated from normal user chats, because scheduled runs create fresh sessions on purpose.

Those guarantees are what make continuity useful. If the storage and routing boundaries were blurred, Hermes would either leak state across surfaces or forget the context that makes a conversation feel continuous.

## Step Order For A Cross-Surface Conversation

You can see the whole pattern in one ordered path.

1. A user starts in one surface.
   They may begin in the CLI, send a message through the gateway, open an ACP editor session, or schedule a cron job.

2. Hermes builds the surface identity.
   The surface decides whether the current turn is a local session, a platform chat lane, an editor session, or a scheduled job.

3. Hermes loads the matching transcript or creates a new one.
   The live turn gets attached to a durable session record through `SessionDB` or a shell-specific session manager.

4. Hermes attaches surface metadata.
   Gateway source information, ACP cwd overrides, CLI session selection, or cron job delivery rules are added to the runtime context.

5. Hermes runs the agent loop.
   The model sees the conversation as one coherent history, even if the surface changed since the previous turn.

6. Hermes persists the result and lineage.
   The next turn can resume from the updated record, or a compressed continuation can fork from the earlier session without erasing history.

7. If the surface changes again, the process repeats.
   The conversation stays readable because the same durable record is reattached through a new live identity.

This is the practical meaning of multi-surface continuity: the surfaces are different, but the thread is the same.

## Source Evidence

The implementation evidence for this pattern comes from:

- `hermes-agent/hermes_state.py` for `SessionDB`, transcript persistence, search, replay, and continuation lineage
- `hermes-agent/gateway/session.py` for `SessionSource`, `build_session_key()`, and session-to-routing mapping
- `hermes-agent/acp_adapter/session.py` for ACP live session state, cwd binding, persistence, restore, and cleanup
- `hermes-agent/website/docs/developer-guide/session-storage.md` for the maintainer-facing description of durable session history and lineage
- `hermes-agent/website/docs/developer-guide/gateway-internals.md` for the gateway-side routing and session-key behavior

## See Also

- [Session Storage](../entities/session-storage.md)
- [Gateway Runtime](../entities/gateway-runtime.md)
- [CLI Runtime](../entities/cli-runtime.md)
- [Cron System](../entities/cron-system.md)
- [ACP Adapter](../entities/acp-adapter.md)
- [Gateway Message to Agent Reply Flow](../syntheses/gateway-message-to-agent-reply-flow.md)
- [ACP Editor Session Bridge](../syntheses/acp-editor-session-bridge.md)
- [Cross-Session Recall and Memory Provider Pluggability](cross-session-recall-and-memory-provider-pluggability.md)
