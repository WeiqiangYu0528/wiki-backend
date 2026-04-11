# Routing System

## Overview

The routing system decides which agent and session lane should own each inbound interaction. Given a channel identifier, account ID, peer (user/group), guild/team, and optional role membership, it applies a priority-ordered sequence of binding rules from `openclaw.yml` and returns a fully-resolved `ResolvedAgentRoute` containing `agentId`, `accountId`, `sessionKey`, `mainSessionKey`, and a `matchedBy` reason string for debugging. Routing runs before agent execution starts; a misconfigured binding collapses isolation, merging conversations that should stay separate.

## Key Types

```ts
// src/routing/resolve-route.ts
export type ResolveAgentRouteInput = {
  cfg: OpenClawConfig;
  channel: string;
  accountId?: string | null;
  peer?: RoutePeer | null;
  parentPeer?: RoutePeer | null;  // thread parent, for binding inheritance
  guildId?: string | null;
  teamId?: string | null;
  memberRoleIds?: string[];       // Discord role IDs for role-based routing
};

export type ResolvedAgentRoute = {
  agentId: string;
  channel: string;
  accountId: string;
  sessionKey: string;       // internal persistence + concurrency key
  mainSessionKey: string;   // convenience alias; collapses DM threads
  lastRoutePolicy: "main" | "session";
  matchedBy:
    | "binding.peer"
    | "binding.peer.parent"
    | "binding.peer.wildcard"
    | "binding.guild+roles"
    | "binding.guild"
    | "binding.team"
    | "binding.account"
    | "binding.channel"
    | "default";
};
```

`RoutePeer` carries both a `kind` (`ChatType`: `"direct" | "group" | "thread" | ...`) and an `id` (the platform-specific user or channel identifier).

## Architecture

### Binding Priority Order

`resolveAgentRoute()` tries match conditions in descending specificity:

| Priority | Match | Description |
|----------|-------|-------------|
| 1 | `binding.peer` | Exact peer ID match from `bindings` config |
| 2 | `binding.peer.parent` | Parent peer match (thread inherits parent's binding) |
| 3 | `binding.peer.wildcard` | Wildcard peer match in a binding |
| 4 | `binding.guild+roles` | Discord guild + member role IDs |
| 5 | `binding.guild` | Discord guild ID only |
| 6 | `binding.team` | Slack/Teams workspace/team ID |
| 7 | `binding.account` | Channel account ID |
| 8 | `binding.channel` | Channel ID only |
| 9 | `default` | Falls back to `resolveDefaultAgentId(cfg)` |

Bindings are loaded from `listRouteBindings(cfg)` in `src/config/bindings.ts`, which reads the `agents.bindings` array from `openclaw.yml`.

### Session Key Construction

After a binding is matched, the session key is computed in `src/routing/session-key.ts` via `buildAgentSessionKey()`:

```ts
export function buildAgentSessionKey(params: {
  agentId: string;
  channel: string;
  accountId?: string | null;
  peer?: RoutePeer | null;
  dmScope?: "main" | "per-peer" | "per-channel-peer" | "per-account-channel-peer";
  identityLinks?: Record<string, string[]>;
}): string
```

The `dmScope` field controls how direct-message conversations collapse: `"main"` means all DMs from any user share one session key (a single agent transcript), while `"per-peer"` gives each user their own session key. The most granular scope `"per-account-channel-peer"` encodes account, channel, and peer into the key.

Session key format is `agent:<agentId>:<rest>`, where `<rest>` encodes the peer dimensions used for isolation. The `mainSessionKey` is always `agent:<agentId>:main` for the same agent, serving as the routing anchor for last-route tracking.

### Account ID Normalization

`normalizeAccountId()` and `normalizeAgentId()` in `src/routing/account-id.ts` sanitize whitespace and case. `DEFAULT_ACCOUNT_ID = "default"` is used when no account is specified.

### `lastRoutePolicy`

```ts
export function deriveLastRoutePolicy(params: {
  sessionKey: string;
  mainSessionKey: string;
}): "main" | "session" {
  return params.sessionKey === params.mainSessionKey ? "main" : "session";
}
```

When a DM collapses to the main session key (e.g., `dmScope = "main"`), the `lastRoute` update is written against `mainSessionKey`. Otherwise it tracks the exact per-peer key.

## Operational Flow

1. An inbound message arrives on a channel plugin's `startAccount` loop and is passed to the reply dispatch pipeline.
2. The pipeline calls `resolveAgentRoute({ cfg, channel, accountId, peer, guildId, teamId, memberRoleIds })`.
3. The router loads bindings from config and walks the priority table above.
4. On a match, it calls `buildAgentSessionKey()` with the resolved `agentId`, channel, account, and peer.
5. The returned `ResolvedAgentRoute` is used to:
   - Select which agent configuration to use for the reply.
   - Identify the session (and its transcript) where the conversation state lives.
   - Determine whether to update the "last route" pointer on the main or session key.

## Boundaries

- The routing system reads config but never writes it.
- It does not own the session store — it only computes session keys. Session state is managed by the gateway's session infrastructure.
- Channel normalization (alias resolution) is delegated to `src/channels/registry.ts` before routing runs.
- Agent config resolution (workspace dir, model, skills) is delegated to `src/agents/agent-scope.ts` after routing.

## Source Files

| File | Purpose |
|------|---------|
| `src/routing/resolve-route.ts` | `resolveAgentRoute()` main entry point; binding walk and match logic |
| `src/routing/session-key.ts` | `buildAgentSessionKey()`, `buildAgentMainSessionKey()`, key parsing and normalization |
| `src/routing/bindings.ts` | `listBindings()`, `listBoundAccountIds()` — loads route bindings from config |
| `src/routing/account-id.ts` | `normalizeAccountId()`, `DEFAULT_ACCOUNT_ID` |
| `src/routing/default-account-warnings.ts` | Diagnostic warnings when an implicit default account is selected |

## See Also

- [Session System](session-system.md) — session state and lifecycle
- [Channel System](channel-system.md) — provides normalized channel IDs and `RoutePeer`
- [Agent Runtime](agent-runtime.md) — consumes `ResolvedAgentRoute` to start agent execution
- [Multi-Channel Session Routing](../concepts/multi-channel-session-routing.md) — routing concept in depth
- [Channel Binding and Session Identity Flow](../syntheses/channel-binding-and-session-identity-flow.md)
- [Inbound Message to Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md)
