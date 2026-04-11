# Channel Binding and Session Identity Flow

## Overview

Every inbound message in OpenClaw passes through a four-stage pipeline that converts raw channel metadata into a deterministic session key. That key is the sole identity token for a conversation: it controls which agent processes the message, which transcript file accumulates the history, and which concurrency lock prevents overlapping replies. Understanding how the key is constructed explains why the same user messaging from two different channels gets two separate transcripts, why a Discord thread inherits its parent channel's agent binding, and why changing a binding in `openclaw.yml` immediately redirects future messages without touching old history.

The four stages are: **channel normalization** (convert raw network identifiers into canonical forms), **binding evaluation** (walk a 9-level priority chain to select the matching agent), **session key construction** (encode the isolation dimensions into a structured string), and **session isolation** (the resulting key acts as the persistence and concurrency lane for the conversation).

## Systems Involved

| System | Role in this flow |
|--------|-------------------|
| [Channel System](../entities/channel-system.md) | Normalizes raw channel IDs and peer identifiers; provides `RoutePeer` and `ChatType` |
| [Routing System](../entities/routing-system.md) | Evaluates binding rules, calls `buildAgentSessionKey()`, returns `ResolvedAgentRoute` |
| [Session System](../entities/session-system.md) | Owns the session key schema, lifecycle events, send policy, and transcript storage |
| [Multi-Channel Session Routing](../concepts/multi-channel-session-routing.md) | Concept overview of how multiple channels map to isolated sessions |

## Binding Resolution Chain

### Stage 1 — Channel Normalization

Before routing begins, the channel adapter calls `normalizeAnyChannelId()` in `src/channels/registry.ts`. This function resolves any raw alias (`"imessage"`, `"discord"`, a plugin-registered string) into the canonical lowercase channel ID stored in the frozen `CHAT_CHANNEL_ALIASES` map. The resolved ID is what routing sees as `channel`.

At the same time, the adapter constructs a `RoutePeer` value:

```ts
type RoutePeer = {
  kind: ChatType;  // "direct" | "group" | "thread" | "channel" | ...
  id: string;      // platform-specific user or channel identifier
};
```

`ChatType` is the discriminator that determines, for example, whether a peer represents a one-to-one DM (`"direct"`) or a guild channel (`"channel"`). The peer's `id` is the platform-specific handle, normalized to lowercase before it enters the routing layer.

The full input to the routing function is:

```ts
// src/routing/resolve-route.ts
export type ResolveAgentRouteInput = {
  cfg: OpenClawConfig;
  channel: string;           // normalized channel ID, e.g. "discord", "telegram"
  accountId?: string | null; // bot account on this channel, e.g. bot token identity
  peer?: RoutePeer | null;   // the user or group the message came from
  parentPeer?: RoutePeer | null; // thread parent; enables binding inheritance
  guildId?: string | null;   // Discord server ID
  teamId?: string | null;    // Slack/Teams workspace ID
  memberRoleIds?: string[];  // Discord role IDs for role-based routing
};
```

`accountId` defaults to `"default"` (the `DEFAULT_ACCOUNT_ID` constant) when absent. This matters: a binding that specifies `accountId: mybot` will not match a message that arrives on a different bot account on the same channel.

### Stage 2 — Binding Evaluation

`resolveAgentRoute()` in `src/routing/resolve-route.ts` loads bindings from `listBindings(cfg)` (which reads the `agents.bindings` array from `openclaw.yml`) and walks them in a fixed 9-level priority order. The first matching rule wins.

| Priority | `matchedBy` value | Match condition |
|----------|------------------|-----------------|
| 1 | `binding.peer` | Exact peer `kind` + `id` match |
| 2 | `binding.peer.parent` | Parent peer match (thread inherits parent binding) |
| 3 | `binding.peer.wildcard` | Binding specifies `peer.id: "*"` — matches any peer of that kind |
| 4 | `binding.guild+roles` | Discord `guildId` match AND at least one `memberRoleIds` match |
| 5 | `binding.guild` | Discord `guildId` match only |
| 6 | `binding.team` | Slack/Teams `teamId` match |
| 7 | `binding.account` | `accountId` match (no peer/guild/team constraint) |
| 8 | `binding.channel` | `channel` match only (wildcard account `*`) |
| 9 | `default` | `resolveDefaultAgentId(cfg)` — first agent with `default: true`, or first agent, or `"main"` |

**Thread parent inheritance (priority 2)** is the mechanism that prevents thread replies from falling through to the default agent. When a Discord or Slack thread message arrives, the adapter passes the parent message's peer as `parentPeer`. If the thread peer itself has no binding (priority 1 misses), the router tries the parent peer's exact binding at priority 2 before continuing to wildcard or broader levels.

**Role-based routing (priority 4)** re-evaluates on every message. A user who gains or loses a Discord role will see their routing change on their next message without any gateway restart.

The `matchedBy` field in `ResolvedAgentRoute` carries the winning level as a string, which appears in debug logs and is useful for diagnosing misconfigured bindings.

## Session Key Construction

### `buildAgentSessionKey()` signature

After a binding is matched and an `agentId` is resolved, the router calls:

```ts
// src/routing/resolve-route.ts (delegates to src/routing/session-key.ts)
export function buildAgentSessionKey(params: {
  agentId: string;
  channel: string;
  accountId?: string | null;
  peer?: RoutePeer | null;
  dmScope?: "main" | "per-peer" | "per-channel-peer" | "per-account-channel-peer";
  identityLinks?: Record<string, string[]>;
}): string
```

The `dmScope` parameter is read from `cfg.session.dmScope` (set in `openclaw.yml`) and controls how direct-message conversations collapse. The four options and the session keys they produce:

| `dmScope` | Session key produced | Use case |
|-----------|---------------------|----------|
| `"main"` (default) | `agent:<agentId>:main` | All DMs share one transcript; personal assistant scenario |
| `"per-peer"` | `agent:<agentId>:direct:<peerId>` | Each user gets their own session, channel-agnostic |
| `"per-channel-peer"` | `agent:<agentId>:<channel>:direct:<peerId>` | Per (channel, user) pair |
| `"per-account-channel-peer"` | `agent:<agentId>:<channel>:<accountId>:direct:<peerId>` | Most granular: per (account, channel, user) triple |

For non-DM peers (groups, guild channels, threads), the key always encodes channel and peer regardless of `dmScope`:

```
agent:<agentId>:<channel>:<peerKind>:<peerId>
```

### Session key examples

```
# dmScope="main" — single personal assistant for all DMs
agent:main:main

# dmScope="per-peer" — user 123456789 gets their own lane
agent:main:direct:123456789

# dmScope="per-channel-peer" — same user, different lane per channel
agent:main:discord:direct:123456789
agent:main:telegram:direct:123456789

# dmScope="per-account-channel-peer" — multiple bot accounts on same channel
agent:main:discord:botaccount-a:direct:123456789
agent:main:discord:botaccount-b:direct:123456789

# Non-DM: Discord guild channel (always channel+peer encoded)
agent:main:discord:channel:987654321

# Non-DM: Slack group conversation
agent:main:slack:group:C01234ABCDE

# Thread inheriting parent session key
agent:main:discord:channel:987654321:thread:msg999
```

The `mainSessionKey` is always `agent:<agentId>:main` for the same agent. It serves as the routing anchor for last-route tracking, regardless of which session key the inbound message resolves to.

All keys are lowercased before storage. The `normalizeAgentId()` function ensures agent IDs are safe for use as path components (alphanumeric plus `-` and `_`, max 64 chars).

### `identityLinks` and peer canonicalization

The optional `identityLinks` config field (`cfg.session.identityLinks`) maps canonical peer IDs to lists of aliases. When a peer ID matches an alias, `buildAgentSessionKey()` substitutes the canonical ID before constructing the key. This enables a user who has different IDs on different channels (or who changes their username) to share a single session lane without generating orphaned transcripts.

## Session Isolation Guarantee

**The session key is the sole isolation boundary.** Two conversations that share the same session key share the same transcript, the same concurrency lock, and the same send-policy evaluation. Two conversations with different session keys are completely independent.

Consider a concrete case: user Alice (`peerId: alice-99`) messages the bot on Discord (`channel: discord`) and also on Telegram (`channel: telegram`). With `dmScope="per-channel-peer"`:

- Discord session key: `agent:main:discord:direct:alice-99`
- Telegram session key: `agent:main:telegram:direct:alice-99`

These are different strings, so Alice's Discord conversation has no history overlap with her Telegram conversation. If the operator wants Alice's conversations to merge, they would set `dmScope="per-peer"`, producing `agent:main:direct:alice-99` for both channels.

Now consider two different users, Bob (`peerId: bob-11`) and Carol (`peerId: carol-22`), both messaging on Telegram with `dmScope="per-channel-peer"`:

- Bob: `agent:main:telegram:direct:bob-11`
- Carol: `agent:main:telegram:direct:carol-22`

Again different keys, so their transcripts are fully isolated. Carol cannot see Bob's messages; the agent receives a fresh history when Carol is the active peer.

This isolation is enforced structurally, not by runtime policy checks. No ACL rule or permission check gates access to a transcript — the key that points to the transcript simply differs. A misconfigured binding that collapses two peers to the same key (for example, `dmScope="main"` when per-peer isolation was intended) merges their conversations irreversibly until the configuration is corrected and the gateway is restarted with a new key scheme.

## Session Resume via `lastRoutePolicy`

`ResolvedAgentRoute` includes a `lastRoutePolicy` field:

```ts
// src/routing/resolve-route.ts
export function deriveLastRoutePolicy(params: {
  sessionKey: string;
  mainSessionKey: string;
}): "main" | "session" {
  return params.sessionKey === params.mainSessionKey ? "main" : "session";
}
```

When `sessionKey === mainSessionKey` (the `dmScope="main"` case), `lastRoutePolicy` is `"main"`, and the gateway writes the last-route pointer against `mainSessionKey`. For all other `dmScope` values, `lastRoutePolicy` is `"session"`, and the pointer is written against the per-peer `sessionKey`.

The last-route pointer enables **session resume**: when a new inbound message arrives, the runtime looks up the last-route pointer to find the most recent session key without scanning the full session store. For DM-scoped sessions (`dmScope="per-peer"` or finer), this means Alice's next message always reconnects to Alice's last session lane, even after a gateway restart.

`resolveInboundLastRouteSessionKey()` encapsulates the logic that picks which key to update:

```ts
export function resolveInboundLastRouteSessionKey(params: {
  route: Pick<ResolvedAgentRoute, "lastRoutePolicy" | "mainSessionKey">;
  sessionKey: string;
}): string {
  return params.route.lastRoutePolicy === "main"
    ? params.route.mainSessionKey
    : params.sessionKey;
}
```

## Configuration Examples

### Personal assistant (all DMs share one session)

```yaml
# openclaw.yml
session:
  dmScope: main

agents:
  list:
    - id: main
      default: true
```

All direct messages to any bot account on any channel produce `agent:main:main`. Suitable for a single-user personal assistant where conversation continuity across channels is desired.

### Per-user isolation on Discord

```yaml
session:
  dmScope: per-peer

agents:
  list:
    - id: assistant
      default: true
```

Each Discord user gets their own session: `agent:assistant:direct:<userId>`. A group of users can each have a private conversation with the assistant.

### Multi-agent routing by Discord guild and role

```yaml
agents:
  bindings:
    - match:
        channel: discord
        guildId: "111222333444"
        roles: ["mod-role-id", "admin-role-id"]
      agentId: mod-assistant
    - match:
        channel: discord
        guildId: "111222333444"
      agentId: community-bot
    - match:
        channel: telegram
      agentId: telegram-bot
  list:
    - id: mod-assistant
    - id: community-bot
    - id: telegram-bot
      default: true
```

Moderators and admins in guild `111222333444` are routed to `mod-assistant` (priority 4, `binding.guild+roles`). All other guild members go to `community-bot` (priority 5, `binding.guild`). Telegram traffic goes to `telegram-bot` (priority 8, `binding.channel`).

### Exact peer binding for a private DM agent

```yaml
agents:
  bindings:
    - match:
        channel: telegram
        peer:
          kind: direct
          id: "9876543210"
      agentId: personal-assistant
    - match:
        channel: telegram
      agentId: public-bot
  list:
    - id: personal-assistant
    - id: public-bot
      default: true
```

Telegram user `9876543210` is routed to `personal-assistant` (priority 1, `binding.peer`). Everyone else on Telegram goes to `public-bot` (priority 8, `binding.channel`). The personal assistant session key will be `agent:personal-assistant:telegram:direct:9876543210` (with `dmScope="per-channel-peer"`) or collapse to `agent:personal-assistant:main` if `dmScope="main"`.

### Multi-account channel isolation

```yaml
session:
  dmScope: per-account-channel-peer

agents:
  bindings:
    - match:
        channel: discord
        accountId: bot-account-a
      agentId: agent-a
    - match:
        channel: discord
        accountId: bot-account-b
      agentId: agent-b
```

Two bot accounts on Discord get separate agents and separate session key namespaces: `agent:agent-a:discord:bot-account-a:direct:<userId>` vs. `agent:agent-b:discord:bot-account-b:direct:<userId>`. A user who interacts with both bots has two fully isolated transcripts.

## Source Evidence

| File | Contribution |
|------|-------------|
| `src/routing/resolve-route.ts` | `resolveAgentRoute()`, `ResolveAgentRouteInput`, `ResolvedAgentRoute`, `buildAgentSessionKey()`, `deriveLastRoutePolicy()`, `resolveInboundLastRouteSessionKey()` |
| `src/routing/session-key.ts` | `buildAgentPeerSessionKey()`, `buildAgentMainSessionKey()`, `normalizeAgentId()`, `resolveThreadSessionKeys()` |
| `src/routing/bindings.ts` | `listBindings()` — loads `agents.bindings` from config |
| `src/routing/account-id.ts` | `normalizeAccountId()`, `DEFAULT_ACCOUNT_ID` |
| `src/channels/registry.ts` | `normalizeAnyChannelId()` — resolves channel aliases to canonical IDs |
| `src/channels/chat-type.ts` | `ChatType` discriminator union (`"direct" \| "group" \| "thread" \| ...`) |
| `src/channels/conversation-binding-context.ts` | Translates native peer IDs to `RoutePeer` shape |
| `src/sessions/session-key-utils.ts` | `parseAgentSessionKey()`, key classifier functions |
| `src/sessions/session-lifecycle-events.ts` | Lifecycle event pub/sub triggered after session identity is resolved |
| `src/config/bindings.ts` | `listRouteBindings()` — reads binding array from `openclaw.yml` |

## See Also

- [Multi-Channel Session Routing](../concepts/multi-channel-session-routing.md)
- [Routing System](../entities/routing-system.md)
- [Session System](../entities/session-system.md)
- [Channel System](../entities/channel-system.md)
- [Inbound Message to Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
