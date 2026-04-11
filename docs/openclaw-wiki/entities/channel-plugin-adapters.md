# Channel Plugin Adapters

## Overview

Channel plugin adapters are the concrete integration layer connecting OpenClaw to messaging networks. Each adapter is a TypeScript module that implements a set of `Channel*Adapter` interfaces, packages them as a `ChannelPlugin` object, and registers with the plugin registry. Adapters handle the full lifecycle of a channel account: authentication, account startup, inbound message delivery, outbound message dispatch, approval flows, group management, and configuration UI.

The adapter contract (`src/channels/plugins/types.plugin.ts`) separates capability declaration from implementation. An adapter declares which capabilities it supports (messaging, threading, approvals, heartbeat, etc.) via a `ChannelCapabilities` object; the runtime gates feature availability on those declarations. This means OpenClaw's shared session, routing, and permission infrastructure works uniformly across networks as different as iMessage, Discord, and WhatsApp, because the adapter absorbs all network-specific behavior behind a common interface.

## Key Types

The `ChannelPlugin` type assembles all optional adapter interfaces:

```ts
// src/channels/plugins/types.plugin.ts
export type ChannelPlugin = {
  id: ChannelId;
  meta: ChannelMeta;                    // aliases, markdownCapable, etc.
  gateway: ChannelGatewayAdapter;       // startAccount(), per-account event loop
  lifecycle?: ChannelLifecycleAdapter;  // onStart, onStop hooks
  auth?: ChannelAuthAdapter;            // token/credential validation
  outbound?: ChannelOutboundAdapter;    // send messages to the network
  messaging?: ChannelMessagingAdapter;  // receive and parse inbound messages
  threading?: ChannelThreadingAdapter;  // thread creation, reply in thread
  groups?: ChannelGroupAdapter;         // group/server membership
  setup?: ChannelSetupAdapter;          // configuration UI steps
  approval?: ChannelApprovalAdapter;    // exec approval forwarding
  heartbeat?: ChannelHeartbeatAdapter;  // liveness and connectivity polling
  status?: ChannelStatusAdapter;        // health reporting to gateway
  directory?: ChannelDirectoryAdapter;  // contact directory lookup
  secrets?: ChannelSecretsAdapter;      // credential storage helpers
  security?: ChannelSecurityAdapter;    // channel-level security policies
  allowlist?: ChannelAllowlistAdapter;  // sender allowlist enforcement
  pairing?: ChannelPairingAdapter;      // device pairing support
  configuredBinding?: ChannelConfiguredBindingProvider; // ACP-style bindings
  resolver?: ChannelResolverAdapter;    // peer ID resolution
  elevated?: ChannelElevatedAdapter;    // elevated/admin mode
};
```

`ChannelGatewayAdapter` is mandatory and contains `startAccount(ctx)` — the long-running async function the gateway calls to run the per-account event loop.

### Adapter Capabilities

```ts
// src/channels/plugins/types.core.ts
export type ChannelCapabilities = {
  send?: boolean;
  react?: boolean;
  edit?: boolean;
  delete?: boolean;
  thread?: boolean;
  file?: boolean;
  image?: boolean;
  voice?: boolean;
  video?: boolean;
  richText?: boolean;
  [capability: string]: boolean | undefined;
};
```

### Config Schema

Adapters can declare a per-account configuration schema:

```ts
// src/channels/plugins/types.plugin.ts
export type ChannelConfigSchema = {
  schema: Record<string, unknown>;          // JSON Schema for config fields
  uiHints?: Record<string, ChannelConfigUiHint>;  // display metadata
  runtime?: ChannelConfigRuntimeSchema;     // runtime Zod/safeParse validator
};
```

The gateway uses `ChannelConfigUiHint` fields (`label`, `help`, `advanced`, `sensitive`, `placeholder`) to render the Control UI channel setup form.

## Architecture

### Adapter Registration

Channel plugins register in the plugin registry's `channels` array via `api.registerChannel(channelPlugin)`. The gateway's `createChannelManager()` calls `listChannelPlugins()` to enumerate all registered channels and starts a supervised per-account loop for each configured account.

### Account Loop

The `gateway.startAccount(ctx)` function is the heart of every adapter. It receives a `ChannelGatewayContext` with:
- The channel account configuration
- A `send()` function for outbound delivery
- An `onInbound()` callback to push received messages into the reply dispatch pipeline
- Agent routing helpers
- Approval and heartbeat facilities

The gateway wraps each `startAccount()` call with a supervised backoff policy (`CHANNEL_RESTART_POLICY`) that restarts crashed accounts with exponential delay up to a maximum of `MAX_RESTART_ATTEMPTS = 10`.

### Binding and Routing

Adapters that support `configuredBinding` implement `ChannelConfiguredBindingProvider`, which allows ACP-style routing where a particular peer or conversation is bound to a specific agent. The `ChannelConfiguredBindingMatch` result from the adapter is passed to `resolveAgentRoute()` as additional binding context.

### Outbound Dispatch

`ChannelOutboundAdapter` defines how the adapter sends messages:
- `send(ctx, payload)` — send a message to the target peer
- `ChannelOutboundContext` carries thread ID, session metadata, and identity
- `ChannelOutboundPayloadHint` tells the adapter what rich content types the payload contains

### Setup Wizard Integration

Adapters that implement `setup` or ship a `ChannelSetupWizard` / `ChannelSetupWizardAdapter` participate in the CLI's `channels setup <id>` flow. The setup adapter provides ordered steps — account URL input, OAuth flow, token validation, etc.

## Bundled Adapters

The `src/channels/plugins/` directory contains bundled adapters. Each lives in its own subdirectory or file:

| Adapter | Notable Capabilities |
|---------|---------------------|
| Discord | Threads, roles, guild routing, slash commands |
| Telegram | Bot API, inline keyboards, voice notes |
| WhatsApp | Business API, media, group support |
| iMessage / BlueBubbles | Apple-network bridge via BlueBubbles server |
| Slack | OAuth, slash commands, Block Kit |
| Signal | CLI bridge, disappearing messages |
| Matrix | Room-based federation, E2E |
| Mattermost, MS Teams, Feishu | Enterprise messaging channels |

## Source Files

| File | Purpose |
|------|---------|
| `src/channels/plugins/types.plugin.ts` | Full `ChannelPlugin` type; all adapter interfaces |
| `src/channels/plugins/types.core.ts` | `ChannelCapabilities`, `ChannelMeta`, core channel types |
| `src/channels/plugins/types.adapters.ts` | All `Channel*Adapter` interface definitions |
| `src/channels/plugins/catalog.ts` | Bundled channel catalog discovery |
| `src/channels/plugins/bundled.ts` | Bundled adapter module exports |
| `src/channels/plugins/binding-registry.ts` | `ChannelConfiguredBindingProvider` registry |
| `src/channels/plugins/binding-types.ts` | Binding type definitions |
| `src/channels/plugins/approvals.ts` | Approval adapter helpers |
| `src/channels/plugins/actions/` | Shared message action helpers |
| `src/gateway/server-channels.ts` | `createChannelManager()` — account loop supervisor |

## See Also

- [Channel System](channel-system.md) — channel ID normalization and registry
- [Plugin Platform](plugin-platform.md) — adapters register through the plugin registry
- [Routing System](routing-system.md) — adapter-provided binding context feeds route resolution
- [Multi-Channel Session Routing](../concepts/multi-channel-session-routing.md)
- [Inbound Message to Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md)
- [Channel Binding and Session Identity Flow](../syntheses/channel-binding-and-session-identity-flow.md)
