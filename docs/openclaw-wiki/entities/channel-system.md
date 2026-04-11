# Channel System

## Overview

The channel system is the boundary layer between external messaging networks and OpenClaw's internal runtime. It normalizes the identity of every supported chat surface into a canonical `ChannelId` string, provides per-channel configuration resolution, controls message ingestion via mention and command gating, and hands normalized inbound events to the routing and session subsystems. The concrete per-network implementations — Discord, Telegram, WhatsApp, iMessage, Slack, and others — live in `src/channels/plugins/` as plugin adapters, but the shared abstractions that make any channel usable without network-specific knowledge live in `src/channels/`.

The cleanest architectural statement is the registry split: `src/channels/registry.ts` handles bundled (built-in) and plugin-registered channels uniformly, while `src/channels/ids.ts` owns the frozen catalog of known channel IDs and their aliases. Routing and gateway code can call `normalizeAnyChannelId()` and `normalizeChannelId()` without knowing whether a channel is bundled or installed externally.

## Key Types

| Type | Source | Role |
|------|--------|------|
| `ChatChannelId` | `src/channels/ids.ts` | Canonical string ID for a known bundled channel |
| `ChannelId` | `src/channels/plugins/types.ts` | Union of built-in and plugin-registered channel IDs |
| `ChannelMeta` | `src/channels/plugins/types.ts` | Metadata for a channel: aliases, markdown capability, etc. |
| `ChannelMatchSource` | `src/channels/channel-config.ts` | How a config entry was matched: `"direct" \| "parent" \| "wildcard"` |
| `ChannelEntryMatch<T>` | `src/channels/channel-config.ts` | Lookup result including matched key and fallback/wildcard sources |

The channel ID catalog is built eagerly at module load time from `listChannelCatalogEntries({ origin: "bundled" })`:

```ts
// src/channels/ids.ts
export const CHAT_CHANNEL_ORDER = Object.freeze(
  BUNDLED_CHAT_CHANNEL_ENTRIES.map((entry) => entry.id),
);
export const CHAT_CHANNEL_ALIASES: Record<string, ChatChannelId> = Object.freeze(
  Object.fromEntries(
    BUNDLED_CHAT_CHANNEL_ENTRIES.flatMap((entry) =>
      entry.aliases.map((alias) => [alias, entry.id] as const),
    ),
  ),
);
```

This produces a frozen, order-sorted list and an alias map usable at zero cost across the codebase.

## Architecture

The registry layer has two levels:

1. **Bundled channels** — resolved via `CHAT_CHANNEL_ALIASES` and `CHAT_CHANNEL_ID_SET` built from the plugin catalog at startup. `normalizeChatChannelId()` is the fast path for these.
2. **Plugin-registered channels** — resolved at call time from `getActivePluginRegistry()?.channels`. `normalizeAnyChannelId()` tries the bundled path first, then falls back to iterating active plugin entries.

```ts
// src/channels/registry.ts
export function normalizeAnyChannelId(raw?: string | null): ChannelId | null {
  // 1. Try bundled channel IDs
  const bundledId = normalizeChatChannelId(raw);
  if (bundledId) return bundledId;
  // 2. Try active plugin registry
  const entry = findRegisteredChannelPluginEntry(normalizeChannelKey(raw) ?? "");
  if (!entry) return null;
  return String(entry.plugin.id ?? "").trim().toLowerCase() as ChannelId || null;
}
```

Per-channel configuration uses a three-way fallback: exact key match → parent key match → wildcard key match:

```ts
// src/channels/channel-config.ts
export type ChannelEntryMatch<T> = {
  entry?: T;          // exact match
  wildcardEntry?: T;  // wildcard fallback
  parentEntry?: T;    // parent (thread) match
  matchSource?: "direct" | "parent" | "wildcard";
};
```

This pattern is used when the gateway or routing layer looks up per-channel policy (model overrides, allow-lists, command availability). The `matchSource` field lets callers know whether they got an exact result or a fallback.

## Runtime Behavior

**Mention gating** (`src/channels/mention-gating.ts`) controls whether the assistant activates on a given message based on whether it was mentioned, replied to, or sent in a direct context. Networks that require an `@mention` to engage the bot use this gate to silence unrelated traffic.

**Command gating** (`src/channels/command-gating.ts`) decides whether a slash command is available in the current channel/chat context. It applies per-channel command policies so that admin commands can be restricted to direct messages or specific channels.

**Inbound debounce** (`src/channels/inbound-debounce-policy.ts`) batches or rate-limits rapid inbound messages to avoid flooding the agent with partial edits or spam from fast-typing users.

**Reply prefix** (`src/channels/reply-prefix.ts`) attaches channel-specific prefix strings to outbound replies, enabling consistent threading on networks that need explicit reply markers.

**Session helpers** (`src/channels/conversation-binding-context.ts`, `src/channels/native-command-session-targets.ts`) translate channel-native peer identifiers into the routing layer's `RoutePeer` shape, which is then consumed by `resolveAgentRoute()` in `src/routing/resolve-route.ts`.

**Account snapshot** fields (`src/channels/account-snapshot-fields.ts`, `src/channels/account-summary.ts`) define the per-account status objects pushed to Control UI clients when channel connection state changes.

## Extension Points

New channel networks are added as channel plugins registered in the plugin catalog. A plugin exposes a `ChannelPlugin` object with:
- `id` — the canonical channel ID string
- `meta.aliases` — aliases that `normalizeAnyChannelId()` accepts
- `meta.markdownCapable` — whether markdown is rendered
- A `gateway.startAccount(ctx)` function that the gateway's `createChannelManager()` calls to run the per-account event loop

Bundled channels auto-populate `CHANNEL_IDS` and `CHAT_CHANNEL_ALIASES` at startup. External plugin channels are resolved dynamically from the active `PluginRegistry`.

## Source Files

| File | Purpose |
|------|---------|
| `src/channels/ids.ts` | Frozen catalog of built-in channel IDs, aliases, and sort order |
| `src/channels/registry.ts` | Runtime lookup: `normalizeChatChannelId`, `normalizeAnyChannelId`, `normalizeChannelId` |
| `src/channels/channel-config.ts` | Three-way config match (direct/parent/wildcard), `ChannelEntryMatch<T>` |
| `src/channels/mention-gating.ts` | Activation policy: whether a message triggers the assistant |
| `src/channels/command-gating.ts` | Per-channel command availability policy |
| `src/channels/inbound-debounce-policy.ts` | Batching policy for rapid inbound messages |
| `src/channels/reply-prefix.ts` | Outbound reply prefix construction |
| `src/channels/chat-meta.ts` | Channel metadata helpers used by the registry |
| `src/channels/chat-type.ts` | `ChatType` discriminator: `"direct" \| "group" \| "thread" \| ...` |
| `src/channels/conversation-binding-context.ts` | Translates native peer IDs to `RoutePeer` |
| `src/channels/account-snapshot-fields.ts` | Per-account status fields for Control UI snapshots |
| `src/channels/plugins/` | Concrete per-network adapters (Discord, Telegram, WhatsApp, etc.) |

## See Also

- [Channel Plugin Adapters](channel-plugin-adapters.md) — concrete per-network adapter implementations
- [Routing System](routing-system.md) — consumes normalized channel IDs and `RoutePeer`
- [Plugin Platform](plugin-platform.md) — plugin registry that channel adapters register into
- [Multi-Channel Session Routing](../concepts/multi-channel-session-routing.md) — routing concept
- [Inbound Message to Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md)
- [Channel Binding and Session Identity Flow](../syntheses/channel-binding-and-session-identity-flow.md)
