# Auth and Approval Boundaries

## Overview

OpenClaw crosses multiple trust boundaries in normal operation. The gateway itself requires authentication from connecting clients. Channels authenticate with external networks using per-account credentials. AI providers require API keys or OAuth tokens. Paired node hosts authenticate with device tokens. Command execution on node hosts requires pre-approved allowlists or interactive approval. Each boundary uses a distinct authentication and authorization model, and the codebase deliberately separates them rather than collapsing into one trust zone.

The boundary separation matters because each surface has different threat models: gateway auth guards the control plane from remote access; channel credentials are per-account secrets stored in the system keychain; exec approval prevents the agent from running arbitrary commands without human sign-off. Mixing these would require trusting a single secret with everything, which the design explicitly avoids.

## Mechanism

### Gateway Authentication

The gateway evaluates auth at the WebSocket handshake via `resolveGatewayAuth()` in `src/gateway/auth.ts`:

```ts
export type ResolvedGatewayAuthMode = "none" | "token" | "password" | "trusted-proxy";

export type GatewayAuthResult = {
  ok: boolean;
  method?: "none" | "token" | "password" | "tailscale" | "device-token"
         | "bootstrap-token" | "trusted-proxy";
  user?: string;
  reason?: string;
  rateLimited?: boolean;
  retryAfterMs?: number;
};
```

Auth modes:
- `"none"` — loopback or trusted-host (no credential required)
- `"token"` — shared bearer token
- `"password"` — password auth
- `"tailscale"` — Tailscale Whois identity (trusted mesh network membership)
- `"device-token"` — paired mobile device/node token
- `"trusted-proxy"` — downstream proxy declared trusted via config

`AUTH_RATE_LIMIT_SCOPE_SHARED_SECRET` constrains brute-force attempts. The rate limiter (`createAuthRateLimiter()`) tracks failed attempts per IP and applies exponential backoff.

### Auth Surface Policies

`GATEWAY_AUTH_SURFACE_PATHS` in `src/secrets/runtime-gateway-auth-surfaces.ts` defines which HTTP paths require which auth modes. `evaluateGatewayAuthSurfaceStates()` computes the effective policy at startup and after config reload. This allows, for example, the Control UI to require a token while the loopback health endpoint requires none.

### Channel Credentials

Channel adapters manage their own credential storage via `ChannelSecretsAdapter`. Credentials (OAuth tokens, API keys, session cookies) are stored in the OS keychain via `src/secrets/` rather than in `openclaw.yml`, preventing accidental config leaks. The secrets module (`src/secrets/runtime.ts`) provides `activateSecretsRuntimeSnapshot()` to load all secrets into a runtime snapshot at gateway startup, making them accessible to channel plugins without repeated keychain reads.

### Provider Auth

Provider authentication (API keys, OAuth tokens) follows the same keychain pattern via `src/plugins/provider-auth-storage.ts`. The `resolveCommandSecretsFromActiveRuntimeSnapshot()` function resolves provider credentials at request time from the preloaded snapshot.

### Node Host Exec Approval

Command execution on node hosts enforces a three-layer policy in `src/node-host/exec-policy.ts`:

```ts
export type ExecSecurity = "deny" | "allowlist" | "full";
export type ExecAsk = "never" | "on-miss" | "always";
```

`evaluateSystemRunPolicy()` produces a `SystemRunPolicyDecision`:
- `security = "deny"` — all executions blocked
- `security = "allowlist"` — only pre-approved commands allowed; missing commands blocked or prompted
- `security = "full"` — all commands allowed (development mode only)

Shell wrappers (`sh/bash/zsh -c`, `cmd.exe /c`) are blocked by default even in allowlist mode and require explicit approval. This prevents the model from injecting arbitrary code through a shell escape.

Interactive approval requests (`src/agents/bash-tools.exec-approval-request.ts`) send a prompt to the Control UI or mobile app. The user approves `"allow-once"` or `"allow-always"`. `"allow-always"` writes a durable approval to `exec-approvals.json` (`ExecApprovalsFile`), persisting it across sessions.

### Device Token Auth

Mobile devices and node hosts authenticate with the gateway using device tokens (not the shared bearer token). `src/gateway/device-auth.ts` issues and validates device tokens. Device tokens are scoped to a specific `nodeId` and cannot be used as general gateway tokens.

### ACP Auth

The ACP bridge (`src/acp/policy.ts`) applies an additional approval classifier (`src/acp/approval-classifier.ts`) on top of gateway auth. ACP clients must authenticate with the gateway credentials and then pass the ACP-layer auth before gaining access to sessions.

## Invariants

1. **Gateway auth and exec approval are independent.** A client authenticated to the gateway cannot bypass node host exec allowlists.
2. **Channel credentials are never written to `openclaw.yml`.** They live in the secrets store.
3. **Shell wrappers require explicit approval.** `sh -c` and `bash -c` are blocked in allowlist mode.
4. **Device tokens are scoped.** A mobile device token cannot impersonate the gateway's owner token.
5. **Rate limiting applies to all auth surfaces.** The rate limiter protects against credential brute force across all auth modes.

## Involved Entities

- [Gateway Control Plane](../entities/gateway-control-plane.md) — implements gateway auth evaluation
- [Node Host and Device Pairing](../entities/node-host-and-device-pairing.md) — exec approval policy
- [Channel Plugin Adapters](../entities/channel-plugin-adapters.md) — channel credential management
- [Provider and Model System](../entities/provider-and-model-system.md) — provider API key/OAuth auth
- [MCP and ACP Bridges](../entities/mcp-and-acp-bridges.md) — ACP auth layer

## Source Evidence

| File | Contribution |
|------|-------------|
| `src/gateway/auth.ts` | `ResolvedGatewayAuthMode`, `GatewayAuthResult`, `resolveGatewayAuth()` |
| `src/gateway/auth-rate-limit.ts` | `createAuthRateLimiter()`, `AUTH_RATE_LIMIT_SCOPE_SHARED_SECRET` |
| `src/secrets/runtime-gateway-auth-surfaces.ts` | `GATEWAY_AUTH_SURFACE_PATHS`, `evaluateGatewayAuthSurfaceStates()` |
| `src/secrets/runtime.ts` | `activateSecretsRuntimeSnapshot()`, `resolveCommandSecretsFromActiveRuntimeSnapshot()` |
| `src/node-host/exec-policy.ts` | `ExecSecurity`, `ExecAsk`, `SystemRunPolicyDecision`, `evaluateSystemRunPolicy()` |
| `src/agents/bash-tools.exec-approval-request.ts` | Interactive approval request dispatch |
| `src/infra/exec-approvals.ts` | `ExecApprovalsFile`, `ExecAsk`, `requiresExecApproval()` |
| `src/gateway/device-auth.ts` | Device token issuance and validation |
| `src/acp/approval-classifier.ts` | ACP-layer approval classification |

## See Also

- [Gateway Control Plane](../entities/gateway-control-plane.md)
- [Node Host and Device Pairing](../entities/node-host-and-device-pairing.md)
- [Gateway as Control Plane](gateway-as-control-plane.md)
- [Canvas Voice and Device Control Loop](../syntheses/canvas-voice-and-device-control-loop.md)
- [Inbound Message to Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md)
