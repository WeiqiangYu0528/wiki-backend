# Multi-Channel Session Routing

## Overview

OpenClaw's routing model maps inbound traffic — which can arrive from Discord, Telegram, iMessage, WhatsApp, Slack, or any plugin-registered channel — to a specific agent and a specific session. Without routing, a single gateway serving multiple channels would either merge all conversations into one transcript or require one gateway per channel. Instead, the routing system applies a priority-ordered set of binding rules that produce a deterministic `(agentId, sessionKey)` pair for every inbound message, regardless of which channel it arrived on.

The routing model is how multi-agent, multi-channel deployment becomes possible without a separate process per agent or channel. One gateway can host multiple named agents (e.g., `main`, `coder`, `bot-for-team-a`), each receiving only the traffic their bindings claim, with session isolation enforced by the session key's structure.

## Mechanism

### Route Resolution

Every inbound message passes through `resolveAgentRoute()` in `src/routing/resolve-route.ts`. The function receives:

```ts
{
  cfg: OpenClawConfig,    // full config with bindings
  channel: string,        // normalized channel ID
  accountId?: string,     // channel account (e.g., bot account ID)
  peer?: RoutePeer,       // { kind: ChatType, id: string }
  parentPeer?: RoutePeer, // thread parent, for inheritance
  guildId?: string,       // Discord server ID
  teamId?: string,        // Slack/Teams workspace ID
  memberRoleIds?: string[], // Discord role IDs
}
```

It walks bindings in descending specificity order:

1. `binding.peer` — exact peer ID match
2. `binding.peer.parent` — parent peer (thread inherits parent's binding)
3. `binding.peer.wildcard` — wildcard peer in the binding
4. `binding.guild+roles` — Discord guild with required role membership
5. `binding.guild` — Discord guild only
6. `binding.team` — Slack/Teams workspace
7. `binding.account` — channel account ID
8. `binding.channel` — channel ID only
9. `default` — `resolveDefaultAgentId(cfg)`

The first matching rule wins. `matchedBy` in the result carries the match reason for debug logging.

### Session Key Construction

After routing selects an `agentId`, `buildAgentSessionKey()` encodes the isolation dimensions into a string:

```
agent:<agentId>:<channel>:<peerKind>:<peerId>    ← per-peer scope
agent:<agentId>:main                              ← collapsed DM scope
agent:<agentId>:cron:<jobId>:run:<runId>          ← cron scope
agent:<agentId>:acp:<...>                         ← ACP scope
```

The `dmScope` parameter on `buildAgentSessionKey()` controls how DM threads collapse:
- `"main"` — all DMs share one transcript (simplest, used for personal assistants)
- `"per-peer"` — each user gets their own session
- `"per-channel-peer"` — per (channel, user) pair
- `"per-account-channel-peer"` — most granular: per (account, channel, user) triple

### Last-Route Tracking

`lastRoutePolicy` in `ResolvedAgentRoute` tells the runtime which key to update when a new interaction arrives:
- `"main"` — update the main session key's last-route pointer (used when `sessionKey === mainSessionKey`)
- `"session"` — update the per-peer session key (used when the session is scoped to a specific peer)

This enables session resume: the next inbound message from a peer finds the most recent session without a full database scan.

### Bindings Configuration

Bindings in `openclaw.yml` look like:

```yaml
agents:
  bindings:
    - match:
        channel: discord
        guildId: "1234567890"
        roles: ["admin"]
      agentId: admin-bot
    - match:
        channel: telegram
        peer:
          kind: direct
          id: "9876543210"
      agentId: personal-assistant
    - match:
        channel: slack
        accountId: myworkspace
      agentId: work-bot
```

`listRouteBindings(cfg)` in `src/config/bindings.ts` reads these into `AgentRouteBinding[]`.

### Multi-Agent Routing

Multiple agents in config means routing decisions diverge by conversation context. The `resolveDefaultAgentId(cfg)` fallback uses the first agent marked `default: true`, or the first agent entry, or `"main"`. Agents that share a `channel + accountId` binding but differ by `peer` or `guildId` get separate session keys and separate transcripts.

## Operational Implications

- Changing a binding after conversations have started redirects future messages to the new agent without migrating old transcripts.
- `sessionKey === mainSessionKey` collapse is a lossy operation: per-peer isolation cannot be restored without a gateway restart + config change.
- Role-based routing (`binding.guild+roles`) re-evaluates on every message, so users who gain or lose roles see their routing change immediately.
- The `parentPeer` field enables threads (Discord, Slack) to inherit the binding of their parent conversation, preventing thread messages from routing to the default agent.

## Involved Entities

- [Routing System](../entities/routing-system.md) — implements `resolveAgentRoute()` and session key construction
- [Channel System](../entities/channel-system.md) — provides normalized channel IDs and `RoutePeer`
- [Session System](../entities/session-system.md) — owns the session keys produced by routing
- [Agent Runtime](../entities/agent-runtime.md) — receives the `ResolvedAgentRoute` to configure agent execution

## Source Evidence

| File | Contribution |
|------|-------------|
| `src/routing/resolve-route.ts` | `resolveAgentRoute()`, `ResolveAgentRouteInput`, `ResolvedAgentRoute` |
| `src/routing/session-key.ts` | `buildAgentSessionKey()`, `buildAgentMainSessionKey()` |
| `src/routing/bindings.ts` | `listBindings()`, `listBoundAccountIds()` |
| `src/sessions/session-key-utils.ts` | `parseAgentSessionKey()`, `isCronSessionKey()`, `getSubagentDepth()` |
| `src/config/bindings.ts` | `listRouteBindings()` — reads bindings from config |
| `src/channels/chat-type.ts` | `ChatType` union discriminator |

## See Also

- [Routing System](../entities/routing-system.md)
- [Session System](../entities/session-system.md)
- [Channel System](../entities/channel-system.md)
- [Channel Binding and Session Identity Flow](../syntheses/channel-binding-and-session-identity-flow.md)
- [Inbound Message to Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md)
