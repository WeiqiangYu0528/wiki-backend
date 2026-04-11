# Session System

## Overview

The session system provides the identity and persistence layer that connects a user conversation across channel reconnects, gateway restarts, and route changes. A session is identified by a structured string key (`agent:<agentId>:<rest>`) and tracks the transcript, send policy, lifecycle events, and provenance of a running or paused agent interaction. Sessions are not a storage system themselves — the gateway owns the actual SQLite/file-backed store — but the session system defines the key schema, lifecycle event protocol, label helpers, and send policy engine that the rest of the runtime depends on.

## Key Types

| Type | Source | Role |
|------|--------|------|
| `ParsedAgentSessionKey` | `src/sessions/session-key-utils.ts` | Parsed `{ agentId, rest }` extracted from a canonical session key |
| `SessionLifecycleEvent` | `src/sessions/session-lifecycle-events.ts` | Emitted when a session starts, resumes, or ends |
| `SessionSendPolicyDecision` | `src/sessions/send-policy.ts` | `"allow" \| "deny"` — whether outbound sends are permitted |
| `SESSION_ID_RE` | `src/sessions/session-id.ts` | UUID regex for session ID validation |

### Session Key Format

Session keys use a colon-separated schema:

```
agent:<agentId>:<channel>:<peerKind>:<peerId>
agent:<agentId>:cron:<jobId>:run:<runId>
agent:<agentId>:subagent:<...>
agent:<agentId>:acp:<...>
```

Key parsing is handled by `parseAgentSessionKey()`:

```ts
// src/sessions/session-key-utils.ts
export function parseAgentSessionKey(
  sessionKey: string | undefined | null,
): ParsedAgentSessionKey | null {
  const parts = raw.split(":").filter(Boolean);
  if (parts.length < 3 || parts[0] !== "agent") return null;
  return { agentId: parts[1], rest: parts.slice(2).join(":") };
}
```

The `rest` portion encodes the session's scope. Classifier functions derive meaning from it:

| Function | Pattern matched |
|----------|----------------|
| `isCronSessionKey()` | `rest.startsWith("cron:")` |
| `isCronRunSessionKey()` | `rest` matches `cron:<id>:run:<id>` |
| `isSubagentSessionKey()` | `rest.startsWith("subagent:")` or top-level `"subagent:"` prefix |
| `isAcpSessionKey()` | `rest.startsWith("acp:")` |
| `getSubagentDepth()` | Counts `:subagent:` segments — nesting depth |

## Architecture

### Lifecycle Events

Session start, resume, and end are communicated through a pub/sub bus in `src/sessions/session-lifecycle-events.ts`:

```ts
export type SessionLifecycleEvent = {
  sessionKey: string;
  reason: string;
  parentSessionKey?: string;
  label?: string;
  displayName?: string;
};

export function onSessionLifecycleEvent(listener): () => void;
export function emitSessionLifecycleEvent(event: SessionLifecycleEvent): void;
```

The gateway's `server.impl.ts` subscribes to `onSessionLifecycleEvent` at startup, forwarding events to connected Control UI clients as `EventFrame` messages. Channel plugins, cron jobs, and the ACP bridge emit lifecycle events when sessions start or close.

### Send Policy

`src/sessions/send-policy.ts` provides `SessionSendPolicyDecision` (`"allow" | "deny"`) by evaluating per-session `openclaw.yml` `send-policy` entries against the current session key. The policy engine strips session key prefixes, derives channel and chat type from the key structure, and matches against configured session entries:

```ts
export function normalizeSendPolicy(raw?: string | null): SessionSendPolicyDecision | undefined;
```

Send policy prevents a denied session from emitting outbound messages even if the agent produces output — used for read-only monitoring modes or staging environments.

### Transcript Events

`src/sessions/transcript-events.ts` defines the event bus for transcript updates (agent messages, tool calls, user messages). The gateway subscribes at startup to broadcast these as streaming events to connected subscribers.

### Session Label and Display Name

`src/sessions/session-label.ts` resolves a human-readable label for a session, used in the Control UI and logging. Labels are derived from peer information (user display names) and fall back to the raw session key.

### Provenance

`src/sessions/input-provenance.ts` carries the provenance of a session's input — which client, device, or channel initiated a given interaction. This is used for audit logging and rate-limiting decisions.

## Session ID vs Session Key

These are different:

- **Session Key** — structured routing/isolation key, e.g. `agent:main:discord:direct:123456`. Determines which agent owns the conversation and how it is stored.
- **Session ID** — a UUID assigned by the gateway to a specific conversation run, e.g. `3f4a1b2c-...`. Session IDs are random and not structural; they appear in transcripts and webhook payloads. Validated by `SESSION_ID_RE` in `src/sessions/session-id.ts`.

## Source Files

| File | Purpose |
|------|---------|
| `src/sessions/session-key-utils.ts` | `parseAgentSessionKey()`, key classifiers (`isCronSessionKey`, `isSubagentSessionKey`, etc.) |
| `src/sessions/session-lifecycle-events.ts` | Pub/sub bus for session start/resume/end events |
| `src/sessions/send-policy.ts` | `SessionSendPolicyDecision` logic — allow/deny outbound sends |
| `src/sessions/transcript-events.ts` | Event bus for transcript content updates |
| `src/sessions/session-id.ts` | `SESSION_ID_RE` UUID validation regex, `looksLikeSessionId()` |
| `src/sessions/session-label.ts` | Human-readable label resolution for Control UI display |
| `src/sessions/input-provenance.ts` | Input provenance tracking for audit and rate-limiting |
| `src/sessions/level-overrides.ts` | Per-session logging level overrides |
| `src/sessions/model-overrides.ts` | Per-session model override fields |

## See Also

- [Routing System](routing-system.md) — computes session keys before sessions run
- [Gateway Control Plane](gateway-control-plane.md) — subscribes to session lifecycle and transcript events
- [Automation and Cron](automation-and-cron.md) — uses cron-namespaced session keys
- [ACP and MCP Bridges](mcp-and-acp-bridges.md) — uses ACP-namespaced session keys
- [Interactive Session Lifecycle](../syntheses/onboarding-to-live-gateway-flow.md)
- [Multi-Channel Session Routing](../concepts/multi-channel-session-routing.md)
