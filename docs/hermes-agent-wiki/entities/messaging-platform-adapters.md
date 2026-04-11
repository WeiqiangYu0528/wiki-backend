# Messaging Platform Adapters

## Overview

Messaging platform adapters are Hermes's transport edge. They are the part of the gateway that knows how to speak Telegram, Discord, Slack, Signal, webhook payloads, Home Assistant events, and the other external surfaces under `gateway/platforms/`.

That edge exists so the rest of the gateway does not need to understand each platform's event format, auth model, media quirks, or send API. An adapter absorbs those platform-local details, turns inbound traffic into one normalized `MessageEvent` shape, and sends outbound replies through the correct platform client. After that handoff, gateway policy takes over.

This page therefore is not a catalog of adapters. It explains the shared adapter contract, the normalization step, the adapter-local active-session guard, and the point where adapter ownership stops and [Gateway Runtime](gateway-runtime.md) ownership begins.

## Why This Layer Exists

Hermes wants one message-driven runtime, not a separate runtime per chat platform. That only works if the transport layer presents a stable shape upward.

The adapter layer provides that stability in four ways:

1. It converts raw platform updates into a shared `MessageEvent` plus `SessionSource`.
2. It hides platform-specific connection and credential details behind one lifecycle contract.
3. It gives the gateway a first-stage active-session guard before control reaches `GatewayRunner`.
4. It owns the actual send operation back to the platform, including retries and media-specific fallbacks.

Everything above that line can reason in terms of sessions, commands, approvals, and agent turns instead of Telegram updates, Discord threads, or Slack event payloads.

## Key Types And Ownership Anchors

| Anchor | What it owns | Why it matters |
| --- | --- | --- |
| `MessageEvent` in `hermes-agent/gateway/platforms/base.py` | Normalized inbound event shape: text, message type, `SessionSource`, raw payload, media paths, reply context, and timestamp | This is the contract every adapter produces before the gateway sees a message |
| `BasePlatformAdapter` in `hermes-agent/gateway/platforms/base.py` | Shared lifecycle, message handler wiring, active-session guard, typing hooks, outbound retry behavior, and `build_source()` helper | This is the common adapter runtime, not just an abstract interface |
| `SessionSource` in `hermes-agent/gateway/session.py` | Platform, chat, user, thread, and topic identity in a transport-neutral form | This is the normalized origin description that feeds session-key routing |
| `gateway/platforms/<platform>.py` modules | Platform-specific connection code, raw event parsing, media download/caching, formatting, and native send operations | This is where Telegram, Discord, Slack, webhook, and other transports differ |
| `gateway/platforms/ADDING_A_PLATFORM.md` | Contributor checklist for new adapters | It shows which behaviors are considered part of the adapter contract, not optional polish |

## The Normalized Adapter Contract

At the transport edge, Hermes expects every adapter to look the same from the gateway's point of view.

### Required lifecycle and send contract

Adapters subclass `BasePlatformAdapter` and implement:

| Method | Adapter responsibility |
| --- | --- |
| `connect()` | Establish transport connection, authenticate, and start listeners |
| `disconnect()` | Tear down listeners, close clients, and stop background work |
| `send()` | Deliver one outbound text response to a platform chat/channel/thread |
| `get_chat_info()` | Return human-readable chat metadata for routing or delivery helpers |

Most adapters also override platform-native media methods such as `send_image()`, `send_document()`, or `send_voice()`. If they do not, the base class falls back to text-oriented behavior. That fallback keeps the contract uniform, even when a platform lacks a richer media API.

### Shared inbound event shape

Every inbound message is normalized into `MessageEvent`. The important fields are:

| Field | Meaning at the gateway boundary |
| --- | --- |
| `text` | The text Hermes should treat as the user-visible prompt or command |
| `message_type` | Normalized content category such as `TEXT`, `PHOTO`, `VOICE`, or `COMMAND` |
| `source` | A `SessionSource` describing platform, chat, user, thread, and optional topic identity |
| `raw_message` | Original platform payload for adapter-local or debugging use |
| `media_urls` / `media_types` | Stable local attachment paths plus normalized media kinds |
| `reply_to_message_id` / `reply_to_text` | Reply context that some adapters can recover from the platform |
| `auto_skill` | Adapter-discovered skill binding, such as topic-bound skills in Telegram |

The contract matters because the gateway runner does not branch on "is this Telegram?" for normal message handling. It branches on normalized event fields instead.

## How Raw Events Become Normalized Events

The easiest way to understand adapter ownership is to follow one inbound event before the gateway sees it.

1. A transport-specific listener receives a raw payload.
   That might be a Telegram update, a Discord message object, a Slack event callback, a webhook POST, or a Home Assistant state-change event.

2. The adapter decides whether the payload should become a Hermes message at all.
   This is where adapters filter self-messages, skip platform echo traffic, require mentions in some channels, or translate platform-native slash-command surfaces into Hermes command text.

3. The adapter builds a normalized `SessionSource`.
   `BasePlatformAdapter.build_source()` converts platform-local identifiers into a common shape: platform, chat ID, chat type, user identity, optional thread ID, and optional chat topic.

4. The adapter prepares the text and attachment payload Hermes will actually consume.
   Representative examples:
   - Telegram derives `chat_type`, optional forum topic metadata, reply context, and topic-bound `auto_skill` before constructing the event.
   - Discord can cache attachment files locally, inject attachment-derived text into the prompt, and preserve thread identity.
   - Slack rewrites Slack slash subcommands into Hermes slash commands so the gateway sees canonical command text instead of Slack-specific syntax.
   - Webhook and Home Assistant adapters synthesize a `SessionSource` and human-readable text from non-chat events so they still fit the same contract.

5. The adapter emits `MessageEvent` and calls `handle_message(event)`.
   That is the key handoff. After that call, the message is no longer a Telegram update or Discord object in architectural terms. It is a normalized gateway event.

This is also where attachment caching belongs. The base adapter provides image, audio, and document cache helpers because many platform URLs are temporary. Hermes wants stable local file paths before the agent loop sees vision, audio, or file inputs.

## Adapter-Local Active-Session Guard

Before `GatewayRunner` sees a message, the base adapter enforces a first-stage concurrency guard.

`BasePlatformAdapter.handle_message()` computes a session key from the normalized `SessionSource` and keeps two adapter-local maps:

| Structure | Purpose |
| --- | --- |
| `_active_sessions` | Marks sessions that already have an in-flight background handler and holds an interrupt event |
| `_pending_messages` | Stores the newest queued follow-up event for that active session |

That guard exists for transport-level timing reasons. A second message can arrive while the first turn is still being prepared or while the agent is blocked inside a long-running tool call. The adapter catches that early, before a duplicate background handler starts.

The base behavior is:

1. If no session is active, mark the session active immediately and spawn `_process_message_background(...)`.
2. If the session is already active and the new event is a normal follow-up, store it in `_pending_messages` and set the interrupt event.
3. If the event is a photo burst, queue and merge it without immediately interrupting, so albums do not create noisy interrupt churn.
4. If the event is one of the control commands that must reach the runner directly, bypass the guard and dispatch inline.

The bypass list is small and deliberate: `/approve`, `/deny`, `/status`, `/stop`, `/new`, and `/reset`. Those commands are shell controls. Queuing them as ordinary user text would either deadlock a blocked approval wait or replay control text back into the agent later.

This guard is important, but it is still not the main session-policy owner. It is a transport-side race barrier. The deeper decisions about whether a queued message should interrupt, reset, approve, or wait belong to the gateway runner.

## Outbound Send Behavior

Adapters also own the final transport send.

The shared pattern is:

1. The gateway or adapter background handler asks the adapter to send text or media.
2. The base class routes text through `_send_with_retry(...)`.
3. The adapter's platform-specific `send()` implementation performs the actual API call.
4. If the first send fails with a transient connection error, the base class retries with backoff.
5. If the failure looks permanent or formatting-specific, the base class can fall back to a simpler plain-text send.
6. Media helpers such as `send_image()`, `send_document()`, `send_voice()`, and `send_video()` either use native platform support or degrade to text when needed.

That is why "outbound delivery" is split across two layers:

- Adapters own the transport operation itself: formatting, chunking, upload API calls, typing indicators, and native attachment sends.
- The gateway owns destination policy: whether the result goes back to the origin, a home channel, or some explicit `DeliveryTarget`.

In other words, adapters decide **how** to send on a platform. The gateway decides **where** the reply should go and **why** it is being sent.

## Where Adapter Ownership Stops

This boundary is the most important part of the page.

Adapters own:

- transport credentials and connection lifecycle
- raw event parsing and filtering
- `SessionSource` construction and `MessageEvent` normalization
- local caching of platform-hosted attachments
- adapter-local active-session tracking and early interrupt signalling
- actual outbound API calls back to the platform

Adapters do not own:

- authorization order or pairing policy
- canonical slash-command semantics
- session reset policy
- running-agent policy beyond the first transport-side guard
- delivery routing to home channels or explicit cross-platform targets
- `AIAgent` execution, tool dispatch, prompt assembly, memory, or persistence

That means the architectural handoff is:

1. Adapter receives raw traffic.
2. Adapter normalizes it and applies the first race-prevention guard.
3. Gateway runner decides what this event means for Hermes control flow.
4. Agent loop runs only if the gateway decides the event should become a turn.

The adapter is therefore the transport edge, not a second gateway runtime hidden inside each platform module.

## Boundary With Gateway Control Flow

The neighboring page boundary should stay explicit:

| Concern | Adapter layer | Gateway layer |
| --- | --- | --- |
| Raw platform payloads | Parses and normalizes them | Does not parse them directly |
| Session identity input | Supplies normalized `SessionSource` | Builds routing key and live session policy from that source |
| Concurrent inbound traffic | Applies the first active-session guard | Decides whether the event interrupts, queues, resets, or bypasses |
| Slash-command text | Can translate platform-local syntax into Hermes command text | Resolves canonical command meaning and dispatches handlers |
| Outbound transmission | Performs actual API sends and media uploads | Chooses target destination and surrounding shell policy |
| Agent execution | Does not own it | Starts and supervises `_run_agent()` / `AIAgent` |

If a reader needs to understand transport-specific message shaping, they should stay on this page. If they need to understand authorization, running-agent locks, pairing, slash-command dispatch, or delivery routing, they should move to [Gateway Runtime](gateway-runtime.md).

## Source Files

| File | What it contributes |
| --- | --- |
| `hermes-agent/gateway/platforms/base.py` | `MessageEvent`, `SendResult`, `BasePlatformAdapter`, media caches, `build_source()`, active-session guard, and shared outbound retry behavior |
| `hermes-agent/gateway/platforms/telegram.py` | Telegram event normalization, topic-aware `SessionSource` building, reply context extraction, and Telegram-native sends |
| `hermes-agent/gateway/platforms/discord.py` | Discord thread-aware normalization, attachment caching/injection, interactive approvals, and Discord-native sends |
| `hermes-agent/gateway/platforms/slack.py` | Slack command normalization, thread/session probing, typing behavior, and Slack-native sends |
| `hermes-agent/gateway/platforms/webhook.py` | Synthetic message generation from HTTP payloads and non-blocking webhook handoff |
| `hermes-agent/gateway/platforms/homeassistant.py` | Event-to-message normalization for state changes instead of chat messages |
| `hermes-agent/gateway/platforms/ADDING_A_PLATFORM.md` | Contributor contract for adding new adapters without breaking gateway assumptions |
| `hermes-agent/website/docs/developer-guide/gateway-internals.md` | Maintainer-oriented description of the two-level guard and adapter/gateway split |

## See Also

- [Gateway Runtime](gateway-runtime.md)
- [Session Storage](session-storage.md)
- [Agent Loop Runtime](agent-loop-runtime.md)
- [Gateway Message to Agent Reply Flow](../syntheses/gateway-message-to-agent-reply-flow.md)
- [Multi-Surface Session Continuity](../concepts/multi-surface-session-continuity.md)
