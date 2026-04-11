# Inbound Message to Agent Reply Flow

## Overview

Every OpenClaw interaction begins when a channel adapter detects an inbound event — a Discord message, a Telegram update, a WhatsApp notification — and ends when the agent's reply exits through the same (or a related) adapter back to the user. Between those two moments, the message crosses four distinct system boundaries: the channel plugin layer, the routing system, the session system, and the agent runtime. Each boundary transforms the data and hands off ownership to the next subsystem.

The path is not a single function call. The gateway's composition root (`startGatewayServer()` in `server.impl.ts`) wires these subsystems together at startup. After that, inbound messages travel through a pipeline that the gateway supervises but does not directly execute: the channel adapter owns network I/O, the routing system owns binding resolution, the session system owns transcript state, and the agent runtime owns model invocation. Understanding where each system begins and ends is what makes failure diagnosis tractable without source-diving across the entire codebase.

## Systems Involved

| System | Contribution |
|--------|-------------|
| [Channel Plugin Adapters](../entities/channel-plugin-adapters.md) | Receives raw network events; normalizes to `InboundChannelMessage`; calls `onInbound()` |
| [Gateway Control Plane](../entities/gateway-control-plane.md) | Composition root; channel manager supervisor; protocol frame dispatch |
| [Routing System](../entities/routing-system.md) | Resolves `(agentId, sessionKey)` pair from channel/account/peer metadata |
| [Session System](../entities/session-system.md) | Provides transcript context; enforces send policy; emits lifecycle events |
| [Agent Runtime](../entities/agent-runtime.md) | Resolves agent config and skills; streams Anthropic API response; dispatches tool calls |
| [Multi-Channel Session Routing](../concepts/multi-channel-session-routing.md) | Conceptual model for how bindings and session keys achieve conversation isolation |

## Step-by-Step Flow

### 1. Gateway Startup — Supervisor Loop Initialized

`startGatewayServer()` calls `createChannelManager()` (`server-channels.ts`), which enumerates all enabled channel accounts via `listChannelPlugins()` and starts a supervised per-account loop for each. Each loop calls the plugin's `gateway.startAccount(ctx)` with a `ChannelGatewayContext` that includes:
- The account configuration
- A `send()` function for outbound delivery
- An `onInbound()` callback that injects received messages into the reply dispatch pipeline

The gateway wraps every `startAccount()` call with `CHANNEL_RESTART_POLICY` — exponential backoff starting at 5 seconds, capped at 5 minutes, up to `MAX_RESTART_ATTEMPTS = 10`.

### 2. Adapter Receives Network Event

The adapter's `startAccount(ctx)` long-running function polls or streams its upstream network (Discord gateway, Telegram Bot API, etc.). When a message arrives, the adapter:
1. Authenticates and rate-checks the event against its `ChannelSecurityAdapter` and `ChannelAllowlistAdapter` (if implemented).
2. Normalizes the raw network payload into an `InboundChannelMessage`, extracting:
   - `channel` — normalized channel ID (e.g., `"discord"`, `"telegram"`)
   - `accountId` — the bot/account identifier
   - `peer` — a `RoutePeer` with `{ kind: ChatType, id: string }` where `ChatType` is `"direct" | "group" | "thread" | ...`
   - `guildId` / `teamId` — server or workspace ID (Discord, Slack)
   - `memberRoleIds` — role membership snapshot for role-based routing
3. Calls `ctx.onInbound(message)` to hand off to the reply dispatch pipeline.

**System boundary crossed:** The raw network representation is discarded. Only the normalized `InboundChannelMessage` fields cross into the gateway pipeline.

### 3. Route Resolution — `resolveAgentRoute()`

The reply dispatch pipeline immediately calls `resolveAgentRoute()` in `src/routing/resolve-route.ts`:

```ts
resolveAgentRoute({
  cfg,          // full OpenClawConfig with bindings
  channel,      // e.g., "discord"
  accountId,    // e.g., "mybot"
  peer,         // { kind: "direct", id: "123456" }
  parentPeer,   // thread parent, if applicable
  guildId,
  teamId,
  memberRoleIds,
})
```

The router loads bindings from `listRouteBindings(cfg)` (reading `agents.bindings` from `openclaw.yml`) and walks the priority table in descending specificity:

| Priority | Match kind | `matchedBy` value |
|----------|------------|-------------------|
| 1 | Exact peer ID | `"binding.peer"` |
| 2 | Parent peer (thread inherits parent's binding) | `"binding.peer.parent"` |
| 3 | Wildcard peer | `"binding.peer.wildcard"` |
| 4 | Guild + role membership | `"binding.guild+roles"` |
| 5 | Guild ID only | `"binding.guild"` |
| 6 | Team/workspace ID | `"binding.team"` |
| 7 | Channel account ID | `"binding.account"` |
| 8 | Channel ID only | `"binding.channel"` |
| 9 | No match | `"default"` → `resolveDefaultAgentId(cfg)` |

The first match wins. `resolveDefaultAgentId(cfg)` returns the agent with `default: true`, or the first agent in `cfg.agents.list`, or `"main"`.

**System boundary crossed:** Raw channel metadata (`channel`, `accountId`, `peer`, `guildId`) goes in; `ResolvedAgentRoute` comes out.

### 4. Session Key Construction — `buildAgentSessionKey()`

Immediately after route resolution, `buildAgentSessionKey()` in `src/routing/session-key.ts` encodes the isolation dimensions into the session key string:

```
agent:<agentId>:<channel>:<peerKind>:<peerId>    ← per-peer scope
agent:<agentId>:main                              ← collapsed DM scope (dmScope = "main")
```

The `dmScope` field controls conversation collapse:
- `"main"` — all DMs share one transcript (`sessionKey === mainSessionKey`)
- `"per-peer"` — each user gets a distinct session key
- `"per-channel-peer"` — isolated by (channel, user)
- `"per-account-channel-peer"` — most granular: (account, channel, user)

`deriveLastRoutePolicy()` determines whether to update last-route tracking against `mainSessionKey` (`"main"`) or the per-peer session key (`"session"`).

The complete `ResolvedAgentRoute` is now available:
```ts
{
  agentId: "coder",
  channel: "discord",
  accountId: "mybot",
  sessionKey: "agent:coder:discord:direct:123456",
  mainSessionKey: "agent:coder:main",
  lastRoutePolicy: "session",
  matchedBy: "binding.peer",
}
```

### 5. Session Context — Transcript and Send Policy

Before agent execution starts, the session system is consulted:

- **Transcript state**: The gateway's persistence layer loads the existing transcript for `sessionKey`. `src/sessions/transcript-events.ts` provides the event bus that will receive new messages during this run.
- **Send policy**: `normalizeSendPolicy()` in `src/sessions/send-policy.ts` evaluates the `send-policy` configured for this session key. If the result is `"deny"`, the pipeline suppresses outbound delivery even if the agent produces output.
- **Lifecycle event**: `emitSessionLifecycleEvent()` in `src/sessions/session-lifecycle-events.ts` fires with `reason: "start"` (or `"resume"` if the session has prior transcript entries). The gateway's startup code, which subscribed to `onSessionLifecycleEvent()`, forwards this as an `EventFrame` to connected Control UI clients.

**System boundary crossed:** `sessionKey` (a string) goes in; transcript history and `SessionSendPolicyDecision` come out.

### 6. Agent Config Resolution — `resolveSessionAgentIds()`

The agent runtime begins with `resolveSessionAgentIds({ sessionKey, config, agentId })` in `src/agents/agent-scope.ts`, which extracts the `agentId` from the structured session key (e.g., `agent:coder:discord:direct:123456` → `agentId = "coder"`), with an explicit override taking precedence.

Agent directory resolution follows in `src/agents/agent-paths.ts`:
1. `OPENCLAW_AGENT_DIR` environment variable (or legacy `PI_CODING_AGENT_DIR`)
2. `~/.openclaw/state/agents/<agentId>/agent/`

Skills are loaded by `src/agents/skills/local-loader.ts`, filtered by `resolveEffectiveAgentSkillFilter(cfg, agentId)` in `src/agents/skills/agent-filter.ts`. Each skill is a markdown file with YAML frontmatter of type `OpenClawSkillMetadata` — the `always: true` field causes unconditional prompt injection; other skills are injected on model request or user invocation.

**System boundary crossed:** `ResolvedAgentRoute.agentId` goes in; `ResolvedAgentConfig` (workspace, model, skills, tool config) comes out.

### 7. Agent Execution — Tool Loop and Anthropic API

The agent starts a reply loop:
1. The system prompt is assembled from the agent's identity, injected skills, and conversation history.
2. `src/agents/anthropic-transport-stream.ts` opens a streaming request to the Anthropic API.
3. The model response streams back. Text deltas are emitted to `transcript-events.ts`'s event bus and forwarded as `EventFrame` messages to connected gateway clients.
4. If the model emits a tool call, the appropriate tool handler executes:
   - Bash commands route through `execTool` in `src/agents/bash-tools.exec.ts`, which may call `src/agents/bash-tools.exec-approval-request.ts` to pause and request user approval via the `ExecApprovalManager`.
   - Long-running processes use `processTool` in `src/agents/bash-tools.process.ts`.
   - Tool results feed back into the loop as the next user turn.
5. The loop continues until the model emits a final `stop_reason: "end_turn"` with no pending tool calls.

Subagent sessions, if spawned, are tracked by `initSubagentRegistry()` (initialized at gateway startup) with their own nested session keys following the pattern `agent:<agentId>:subagent:<...>`.

### 8. Reply Dispatch — Outbound Through the Channel Adapter

The completed reply exits through the `ChannelOutboundAdapter.send(ctx, payload)` interface, which the adapter registered on its `ChannelPlugin.outbound` field. The gateway calls this only if send policy returned `"allow"`.

`ChannelOutboundContext` carries thread ID, session metadata, and peer identity. `ChannelOutboundPayloadHint` informs the adapter which rich content types (images, files, voice) the payload contains so the adapter can serialize appropriately for its network.

The adapter sends the payload to its upstream network. The loop in `startAccount(ctx)` continues running, ready to receive the next inbound event.

**System boundary crossed:** Structured reply payload goes into the adapter; raw network message exits to the user's device.

## Data at Each Boundary

| Boundary | Data Passed | Direction |
|----------|------------|-----------|
| Network → Adapter | Raw network event (Discord `MessageCreate`, Telegram `Update`, etc.) | Inbound |
| Adapter → Pipeline | `InboundChannelMessage` (`channel`, `accountId`, `peer: RoutePeer`, `guildId`, `teamId`, `memberRoleIds`) | Inbound |
| Pipeline → Routing | `ResolveAgentRouteInput` (same fields plus `cfg`, `parentPeer`) | Inbound |
| Routing → Session | `ResolvedAgentRoute` (`agentId`, `sessionKey`, `mainSessionKey`, `lastRoutePolicy`, `matchedBy`) | Inbound |
| Session → Agent Runtime | `sessionKey` string + loaded transcript history + `SessionSendPolicyDecision` | Inbound |
| Agent Runtime → Anthropic API | Assembled system prompt + messages array + tool definitions | Outbound |
| Anthropic API → Agent Runtime | Streaming `ContentBlockDelta` events, tool call blocks, `stop_reason` | Inbound |
| Agent Runtime → Adapter | Reply payload via `ChannelOutboundAdapter.send(ctx, payload)` | Outbound |
| Adapter → Network | Network-native message (Discord API POST, Telegram `sendMessage`, etc.) | Outbound |

## Failure Points

### Stage 1-2: Channel Adapter / Network Layer
- **Network connectivity loss**: `startAccount()` raises an unhandled error; the gateway supervisor restarts with `CHANNEL_RESTART_POLICY` (backoff 5 s → 5 min, max 10 attempts). After `MAX_RESTART_ATTEMPTS`, the account enters a permanently-failed state visible in the `ChannelRuntimeStore`.
- **Auth token expiry**: The adapter's `ChannelAuthAdapter` may detect an invalid credential; without a refresh path, `startAccount()` exits and the supervisor will retry but fail again.
- **Allowlist rejection**: `ChannelAllowlistAdapter` silently drops messages from non-allowlisted senders; no reply is generated and no error is surfaced to the user.

### Stage 3: Route Resolution
- **No matching binding**: Falls through to `"default"` using `resolveDefaultAgentId(cfg)`. If no agents are configured, this may return `"main"` — a synthetic ID with no associated config — causing agent resolution to fail downstream.
- **Malformed config**: `listRouteBindings(cfg)` reading a corrupt `openclaw.yml` will either throw or produce an empty binding list, routing all traffic to the default agent.
- **Role-based routing staleness**: `memberRoleIds` is a snapshot captured at message receipt time. If the adapter does not refresh role membership on each message, a user who recently gained a role may be misrouted until the adapter's cache expires.

### Stage 4: Session Key Construction
- **`dmScope` misconfiguration**: Setting `dmScope = "main"` irreversibly collapses per-peer isolation. Conversations that were separate under `"per-peer"` will merge into a single transcript; this cannot be undone without a config change and gateway restart.
- **Key collision**: Two different channel/peer combinations that produce the same normalized key (e.g., a peer ID that contains colons) would share a transcript. `normalizeAccountId()` and the key builder guard against some cases but not all.

### Stage 5: Session / Send Policy
- **`"deny"` send policy**: The agent executes fully — including tool calls and Anthropic API costs — but no reply is delivered. This is intentional for monitoring modes but represents a costly no-op if misconfigured.
- **Transcript load failure**: If the persistence layer cannot read the existing transcript (disk error, corrupted store), the agent starts without history, effectively restarting the conversation.

### Stage 6-7: Agent Runtime
- **Missing agent config**: If `agentId` resolved by routing has no entry in `cfg.agents.list`, `resolveSessionAgentIds()` falls back to the default agent config; this may produce unexpected behavior.
- **Skill load failure**: A skill file with invalid YAML frontmatter is skipped by `local-loader.ts`; the agent runs without that skill, which may change model behavior silently.
- **Anthropic API error**: `anthropic-transport-stream.ts` receives a non-2xx response or a stream interruption. The error is surfaced into the transcript as an error event; no partial reply is sent.
- **Tool approval timeout**: If `ExecApprovalManager` sends an approval request and no client responds within the timeout, the tool call is denied and the agent receives a denial result, potentially causing the model to loop or give up.
- **Subagent depth exceeded**: `getSubagentDepth()` counting `:subagent:` segments in the session key is the only guard against infinite subagent recursion.

### Stage 8: Outbound Dispatch
- **Send policy `"deny"`**: Delivery is suppressed without error. The agent run is recorded in the transcript but the user receives nothing.
- **Adapter `send()` failure**: A network error during outbound delivery is adapter-specific. The gateway does not retry outbound sends by default; the user receives no reply for that turn.
- **Rich content type mismatch**: If `ChannelOutboundPayloadHint` advertises an image but the adapter's `ChannelCapabilities` declares `image: false`, the adapter must degrade gracefully to text. Adapters that do not implement this fallback may throw.

## Source Evidence

| File | Real Function / Type |
|------|---------------------|
| `src/gateway/server.impl.ts` | `startGatewayServer()` — composition root; wires all subsystems |
| `src/gateway/server-channels.ts` | `createChannelManager()` — supervised per-account loop; `ChannelRuntimeStore`; `CHANNEL_RESTART_POLICY`; `MAX_RESTART_ATTEMPTS` |
| `src/channels/plugins/types.plugin.ts` | `ChannelPlugin`, `ChannelGatewayAdapter`, `ChannelOutboundAdapter`, `ChannelGatewayContext` |
| `src/channels/plugins/types.adapters.ts` | `ChannelOutboundContext`, `ChannelOutboundPayloadHint`, `ChannelAllowlistAdapter`, `ChannelSecurityAdapter` |
| `src/channels/plugins/types.core.ts` | `ChannelCapabilities`, `ChannelMeta` |
| `src/routing/resolve-route.ts` | `resolveAgentRoute()`, `ResolveAgentRouteInput`, `ResolvedAgentRoute` |
| `src/routing/session-key.ts` | `buildAgentSessionKey()`, `buildAgentMainSessionKey()`, `deriveLastRoutePolicy()` |
| `src/routing/account-id.ts` | `normalizeAccountId()`, `DEFAULT_ACCOUNT_ID` |
| `src/routing/bindings.ts` | `listBindings()`, `listBoundAccountIds()` |
| `src/config/bindings.ts` | `listRouteBindings()` — reads `agents.bindings` from `openclaw.yml` |
| `src/sessions/session-key-utils.ts` | `parseAgentSessionKey()`, `isCronSessionKey()`, `isSubagentSessionKey()`, `getSubagentDepth()` |
| `src/sessions/send-policy.ts` | `normalizeSendPolicy()`, `SessionSendPolicyDecision` |
| `src/sessions/session-lifecycle-events.ts` | `emitSessionLifecycleEvent()`, `onSessionLifecycleEvent()`, `SessionLifecycleEvent` |
| `src/sessions/transcript-events.ts` | Transcript event bus for streaming agent output |
| `src/agents/agent-scope.ts` | `resolveSessionAgentIds()`, `resolveDefaultAgentId()`, `ResolvedAgentConfig`, `AgentEntry` |
| `src/agents/agent-paths.ts` | `resolveOpenClawAgentDir()`, `resolveAgentWorkspaceDir()` |
| `src/agents/skills/agent-filter.ts` | `resolveEffectiveAgentSkillFilter()` |
| `src/agents/skills/local-loader.ts` | Skill markdown loading from disk |
| `src/agents/skills/types.ts` | `OpenClawSkillMetadata`, `SkillInvocationPolicy` |
| `src/agents/anthropic-transport-stream.ts` | Anthropic API streaming transport |
| `src/agents/bash-tools.exec.ts` | `execTool` — sandboxed command execution |
| `src/agents/bash-tools.exec-approval-request.ts` | Pre-execution approval prompts |
| `src/agents/subagent-registry.ts` | `initSubagentRegistry()`, subagent session tracking |
| `src/gateway/exec-approval-manager.ts` | `ExecApprovalManager` — cross-gateway approval coordination |
| `src/gateway/protocol/schema/frames.ts` | `ConnectParams`, `HelloOk`, `RequestFrame`, `ResponseFrame`, `EventFrame` |

## See Also

- [Multi-Channel Session Routing](../concepts/multi-channel-session-routing.md)
- [Gateway as Control Plane](../concepts/gateway-as-control-plane.md)
- [Channel Plugin Adapters](../entities/channel-plugin-adapters.md)
- [Routing System](../entities/routing-system.md)
- [Session System](../entities/session-system.md)
- [Agent Runtime](../entities/agent-runtime.md)
- [Channel Binding and Session Identity Flow](channel-binding-and-session-identity-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
