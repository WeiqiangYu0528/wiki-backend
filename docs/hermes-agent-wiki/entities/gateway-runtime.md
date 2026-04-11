# Gateway Runtime

## Overview

The gateway is Hermes in its long-running, message-driven form. It is not a second agent runtime next to `AIAgent`. Instead, `gateway/run.py` wraps the same [Agent Loop Runtime](agent-loop-runtime.md) in a shell that can stay online for many chats, many users, and many platforms at once.

That shell exists because messaging platforms add problems the CLI does not have: inbound events arrive asynchronously, user identity must be authorized before any turn starts, one session may already be busy when the next message arrives, and replies may need to go somewhere other than "the place this turn started". The gateway owns those concerns, then hands a prepared turn to `AIAgent`.

This page is about that shell layer. For the actual model loop, tool calling, prompt assembly, and memory/tool execution behavior, continue to [Agent Loop Runtime](agent-loop-runtime.md). For transport-specific event normalization, continue to [Messaging Platform Adapters](messaging-platform-adapters.md). For transcript durability and session history storage, continue to [Session Storage](session-storage.md).

## Why The Gateway Exists

Hermes can run as a local chat loop, but the gateway turns it into a service. The important shift is not "bot adapters" by themselves. The shift is that Hermes now has to manage many conversation lanes concurrently while still preserving the single-turn semantics that `AIAgent` expects.

The gateway therefore owns five shell responsibilities:

1. Normalize raw platform events into a shared `MessageEvent` shape before the agent loop sees them.
2. Build a deterministic session key from platform, chat, thread, and sometimes user identity so each message lands in the right conversation lane.
3. Enforce authorization and pairing rules before a user can reach the runtime.
4. Guard already-running sessions by queueing, interrupting, or bypassing normal flow for specific commands.
5. Route output back to the origin, a home channel, or an explicit target through delivery and hook surfaces.

The session key point is important. `build_session_key()` and `GatewayRunner._session_key_for_source()` define **routing identity**, not the full persistence story. The gateway needs a stable answer to "which live conversation lane is this message for?" before it needs a durable transcript. `SessionStore` bridges the two by mapping that routing key to a session entry and backing storage, but the storage mechanics belong in [Session Storage](session-storage.md), not here.

## Key Types And Ownership Anchors

| Anchor | What it owns | Why it matters here |
| --- | --- | --- |
| `GatewayRunner` in `hermes-agent/gateway/run.py` | The long-running control flow: message intake, authorization, slash-command dispatch, running-agent guards, session setup, and handoff into `_run_agent()` | This is the shell around `AIAgent` and the main owner of gateway policy |
| `build_session_key()` and `SessionSource` in `hermes-agent/gateway/session.py` | Deterministic routing identity derived from platform, chat type, chat ID, thread ID, and optional participant ID | This is how the gateway decides whether two messages belong to the same live lane |
| `SessionStore` in `hermes-agent/gateway/session.py` | Session-key to session-entry mapping, reset policy, and access to backing transcript/session storage | It connects routing identity to persisted conversation state without making persistence the gateway page's main topic |
| `PairingStore` in `hermes-agent/gateway/pairing.py` | Pending pairing codes, approved users, rate limits, lockout, and secure on-disk pairing state | This is the authorization escape hatch for unknown DM users |
| `DeliveryTarget` and `DeliveryRouter` in `hermes-agent/gateway/delivery.py` | Resolution of `origin`, `local`, home-channel, and explicit platform targets | The gateway can reply somewhere other than the incoming chat, especially for cron and background work |
| Platform adapters in `hermes-agent/gateway/platforms/` | Transport credentials, raw-event normalization, adapter-local active-session guard, and outbound sends | Adapters are the transport edge, not the place where agent policy lives |
| Gateway hooks in `gateway/hooks.py` plus `hooks.emit(...)` calls in `gateway/run.py` | Lifecycle extension points such as `gateway:startup`, `session:start`, `agent:start`, `agent:step`, `agent:end`, and `command:*` | Hooks let the shell grow without moving shell policy into `AIAgent` |

## Inbound Message Lifecycle

The easiest way to understand the gateway is to follow one inbound message from adapter edge to agent turn.

1. A platform adapter receives a raw transport event and normalizes it into a `MessageEvent`.
   The adapter layer is where Telegram updates, Discord events, Slack callbacks, webhook payloads, and similar platform-specific inputs become one shared shape. That boundary is covered in [Messaging Platform Adapters](messaging-platform-adapters.md).

2. The base adapter applies the first active-session guard.
   If the session is already active, adapter-side structures such as `_active_sessions` and `_pending_messages` queue the new message and mark an interrupt early. Some commands are allowed to bypass this queueing path so they can reach the runner immediately.

3. `GatewayRunner._handle_message()` resolves the session key for the event source.
   `GatewayRunner._session_key_for_source()` delegates to `SessionStore._generate_session_key()` when possible, and otherwise falls back to `build_session_key()`. The key format encodes platform, chat type, chat identity, and thread context, with optional per-user isolation in groups. The key answers "which live lane is this?" before any transcript lookup happens.

4. The gateway authorizes the sender.
   `_is_user_authorized()` checks special trusted surfaces first (`HOMEASSISTANT`, `WEBHOOK`), then evaluates per-platform allow-all flags, pairing approval state, platform/global allowlists, and finally the global allow-all fallback. If a DM user is unauthorized and pairing is enabled, the gateway can generate a one-time code instead of silently failing.

5. The gateway handles shell-level interruptions before normal turn startup.
   `GatewayRunner` checks for special cases such as pending `/update` prompts, then examines `_running_agents` for the current session key. If a turn is already running, the runner does not blindly start another one.

6. Running-agent rules decide whether the new event interrupts, queues, or bypasses.
   Important bypass-capable commands include:
   - `/status`, which reports live progress instead of waiting
   - `/stop`, which force-cleans the running-session lock if needed
   - `/new` and `/reset`, which must reset the session rather than being replayed as user text later
   - `/queue`, which appends a next-turn message without interrupting the current turn
   - `/approve` and `/deny`, which must reach the approval handler directly because the blocked agent thread is waiting on an approval event, not on normal chat input

7. If the session is idle, the gateway resolves slash commands before invoking the agent loop.
   Built-in commands, quick commands, plugin commands, and skill slash commands are all handled here. Unknown slash commands are rejected instead of being silently forwarded as model input. This is part of the gateway's job as a shell surface, not part of `AIAgent`.

8. The runner places a sentinel in `_running_agents` before any awaited setup work.
   This is a subtle but important guard in `gateway/run.py`: the sentinel claims the session before hooks, context building, vision enrichment, or other async setup steps can yield. Without it, a second inbound message could slip through the "already running" check and start a duplicate turn for the same session.

9. The gateway creates or reuses session state and prepares context for the agent.
   `SessionStore.get_or_create_session()` returns the live session entry. Then `build_session_context()` and `build_session_context_prompt()` assemble shell-specific context such as source metadata, connected platforms, home channels, and session identity. This is preparation for the agent loop, not the agent loop itself.

10. `_run_agent()` constructs and monitors the `AIAgent` turn.
    At this point the gateway crosses into the [Agent Loop Runtime](agent-loop-runtime.md). The gateway still surrounds that turn with shell concerns such as progress callbacks, interrupt monitoring, inactivity timeouts, and post-turn queue draining, but `AIAgent` now owns model calls, tool dispatch, prompt use, and conversation execution.

11. After the turn, the gateway decides what to do with pending input and output.
    If the agent was interrupted, the gateway drops the interrupted response and promotes the queued input into the next turn. If the agent completed normally and a queued follow-up exists, the gateway may deliver the first response and then recursively start the next turn with updated history. This is the control-flow core of [Gateway Message to Agent Reply Flow](../syntheses/gateway-message-to-agent-reply-flow.md).

12. Delivery happens through adapters, but routing policy stays in the gateway.
    Replies usually go back through the source adapter, but background jobs, cron tasks, and explicit `deliver` targets are resolved through `DeliveryRouter`, not by `AIAgent` itself.

## Authorization, Pairing, And Running-Agent Guards

Authorization is layered because the gateway is exposed to message senders, not just to a trusted local terminal.

### Authorization order

`GatewayRunner._is_user_authorized()` evaluates these rules in order:

1. Trust platform-authenticated system surfaces such as Home Assistant and signed webhooks.
2. Honor per-platform allow-all flags like `TELEGRAM_ALLOW_ALL_USERS`.
3. Accept users already paired in `PairingStore`.
4. Check platform-specific and global allowlists.
5. Fall back to `GATEWAY_ALLOW_ALL_USERS`.
6. Deny by default.

That ordering matters. Pairing is not a replacement for explicit allow-all or allowlists; it is a controlled onboarding path for unknown DM users.

### Pairing behavior

`gateway/pairing.py` keeps pairing state outside the live runner so approval survives restarts. `PairingStore` generates eight-character codes with expiry, rate limiting, max-pending limits per platform, and lockout after repeated failed approval attempts. When an unknown DM user messages Hermes, the gateway can send a one-time code and instruct the owner to approve it out of band. Once approved, later messages pass the normal authorization check.

This is also why the page must not collapse pairing into "session storage". Pairing state answers "is this sender allowed to talk to Hermes at all?" Session state answers "which conversation lane and transcript should an already-authorized message use?"

### Two levels of running-agent protection

The gateway uses two related guards because long-running messaging shells have races that the CLI does not:

1. Adapter-level guard.
   The base adapter catches messages that arrive while a session is active, queues them in adapter-local pending state, and records an interrupt signal as early as possible.

2. Gateway-level guard.
   `GatewayRunner._handle_message()` checks `_running_agents` and decides whether the event should interrupt the current turn, queue for later, or bypass the normal interrupt path entirely.

Together these guards prevent duplicate turns for the same session while still letting urgent control messages reach the shell.

### Queueing, interrupts, and bypass-capable commands

Normal text received during an active turn usually interrupts the running agent and is retained as pending input. Photo bursts get special queueing treatment so transport-level batching does not create noisy interrupt churn. `/queue` explicitly appends work for the next turn without interrupting the current one.

Bypass-capable commands are the important exception:

- `/stop` force-stops a hung or blocked session and clears the running-session lock
- `/new` and `/reset` interrupt, clear stale pending input, reset session state, and emit reset hooks
- `/approve` and `/deny` bypass normal interrupt behavior because the waiting thread is blocked on an approval event inside the dangerous-command path described in [Interruption and Human Approval Flow](../concepts/interruption-and-human-approval-flow.md)
- `/status` surfaces progress without disturbing the running turn

Other commands do not all get this treatment. `/model`, for example, is rejected while a turn is running because changing model selection mid-turn would violate shell assumptions. That distinction is the real meaning of "bypass-capable": not "commands are special", but "some commands are shell controls that must preempt the normal message-to-agent path".

## Delivery And Hook Surfaces

The gateway also owns where output goes once a turn or background task completes. `gateway/delivery.py` models delivery as `DeliveryTarget` values and a `DeliveryRouter` that resolves abstract targets into concrete destinations:

- `origin` means reply to the source chat or thread
- `local` means write output to local files
- a bare platform name means that platform's configured home channel
- `platform:chat_id` or `platform:chat_id:thread_id` means an explicit remote destination

That routing logic matters because Hermes is not always replying inline to the same conversation. Cron jobs, background jobs, and cross-platform messages all need shell-owned destination policy. `AIAgent` does not know about home channels or output truncation limits; the gateway shell does.

Hooks are the other extension surface around the shell. `GatewayRunner` emits lifecycle events such as `gateway:startup`, `session:start`, `session:end`, `session:reset`, `agent:start`, `agent:step`, `agent:end`, and `command:*`. This lets Hermes add operational behaviors around messaging without pushing platform policy into the model loop. It also keeps this page's boundary clean relative to [Tool Registry and Dispatch](tool-registry-and-dispatch.md): tool visibility and invocation belong to the agent/runtime capability surface, while hook emission belongs to the messaging shell.

## Ownership Boundaries

The clearest way to avoid page overlap is to separate the three layers that cooperate on every inbound message.

| Layer | Owns | Does not own |
| --- | --- | --- |
| Platform adapters | Transport credentials, raw event parsing, adapter-local active-session state, and actual send operations | Session policy, authorization order, slash-command semantics, and agent execution |
| Gateway control flow | Session-key routing, authorization, pairing, command dispatch, running-agent guards, queue draining, delivery routing, and hook emission | Model reasoning, tool selection, prompt execution, memory/tool internals, and transcript-format policy |
| Agent loop (`AIAgent`) | Prompted conversation execution, model/provider calls, tool dispatch, memory integration, compression, fallback, and final turn result production | Transport normalization, user authorization, cross-platform routing, and shell-specific command policy |

Two boundary notes are worth keeping explicit:

- Session identity belongs here; transcript persistence does not. The gateway must decide the live routing key and session lane up front, but the details of SQLite/JSONL history storage live in [Session Storage](session-storage.md).
- Dangerous command approval crosses the boundary but does not erase it. The gateway transports `/approve` and `/deny` back to the blocked turn, while the blocked turn itself lives inside the agent/tool execution path.

## Source Files

| File | What it contributes |
| --- | --- |
| `hermes-agent/gateway/run.py` | `GatewayRunner`, authorization checks, command dispatch, sentinel/running-agent guards, session setup, `_run_agent()`, and hook emission |
| `hermes-agent/gateway/session.py` | `SessionSource`, `build_session_key()`, session context builders, and `SessionStore` |
| `hermes-agent/gateway/delivery.py` | `DeliveryTarget`, `DeliveryRouter`, and home-channel or explicit-target resolution |
| `hermes-agent/gateway/pairing.py` | `PairingStore`, secure pairing-code lifecycle, approval state, rate limiting, and lockout |
| `hermes-agent/website/docs/developer-guide/gateway-internals.md` | Maintainer-oriented explanation of gateway architecture, guard layers, delivery, hooks, and process behavior |

## See Also

- [Architecture Overview](../summaries/architecture-overview.md)
- [Agent Loop Runtime](agent-loop-runtime.md)
- [Messaging Platform Adapters](messaging-platform-adapters.md)
- [Session Storage](session-storage.md)
- [Tool Registry and Dispatch](tool-registry-and-dispatch.md)
- [Interruption and Human Approval Flow](../concepts/interruption-and-human-approval-flow.md)
- [Gateway Message to Agent Reply Flow](../syntheses/gateway-message-to-agent-reply-flow.md)
