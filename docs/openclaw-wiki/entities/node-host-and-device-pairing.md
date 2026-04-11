# Node Host and Device Pairing

## Overview

The node host subsystem extends OpenClaw's execution reach beyond the gateway process by running as a paired client on a local or remote machine. It connects to the gateway via `GatewayClient`, registers a device identity, advertises its capabilities (including plugin-contributed commands), and then waits for invocation requests. When an agent turn calls `system.run` or another node-host command, the invocation travels from the gateway to the appropriate node host, which enforces an execution policy before running the requested operation.

Execution policy is a first-class citizen of this subsystem, not an afterthought. `ExecSecurity` and `ExecAsk` modes control whether commands are allowed, require approval, or are blocked outright. Shell wrapper invocations (`sh -c`, `bash -c`, `zsh -c`, and Windows `cmd.exe /c`) are always blocked unless explicitly approved, and the denial message includes diagnostic text to make the block reason auditable. The `OUTPUT_CAP` (200 000 bytes) and `OUTPUT_EVENT_TAIL` (20 000 bytes) constants prevent runaway processes from flooding the event stream.

Device pairing (`src/pairing/`) manages the identity and connection lifecycle between the gateway and node-host clients including iOS, Android, and Mac native applications. The pairing layer handles pairing tokens, device identity persistence, and connection re-establishment so that the gateway always has an authoritative record of which devices are trusted for which operations.

## Key Types

### Runner Configuration

| Type / Symbol | Location | Notes |
|---|---|---|
| `NodeHostRunOptions` | `src/node-host/runner.ts` | `{ gatewayHost, gatewayPort, gatewayTls?, gatewayTlsFingerprint?, nodeId?, displayName? }` — full connection options for starting a node host |
| `NodeHostGatewayConfig` | `src/node-host/runner.ts` | Persisted config loaded from disk via `ensureNodeHostConfig()` |
| `SkillBinsCache` | `src/node-host/runner.ts` | TTL-based binary path cache; `ttlMs = 90 000` ms; avoids repeated `which`-style lookups for skill executables |
| `DEFAULT_NODE_PATH` | `src/node-host/runner.ts` | `"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"` — `PATH` set before command execution |

**Startup helpers called by the runner:**

| Function | Purpose |
|---|---|
| `resolveGatewayConnectionAuth()` | Retrieves auth credentials before connecting `GatewayClient` |
| `loadOrCreateDeviceIdentity()` | Loads a persisted device identity or generates a new one; used for stable device identification across restarts |
| `ensureNodeHostPluginRegistry()` | Initializes the plugin registry for this node host instance |
| `listRegisteredNodeHostCapsAndCommands()` | Enumerates all capabilities and commands available on this host (including plugin contributions) to advertise to the gateway |

### Invocation

| Type / Symbol | Location | Notes |
|---|---|---|
| `NodeInvokeRequestPayload` | `src/node-host/invoke.ts` | `{ id, nodeId, command, paramsJSON?, timeoutMs?, idempotencyKey? }` — wire format for a command invocation arriving from the gateway |
| `OUTPUT_CAP` | `src/node-host/invoke.ts` | `200 000` bytes — maximum total output captured from a command execution |
| `OUTPUT_EVENT_TAIL` | `src/node-host/invoke.ts` | `20 000` bytes — maximum bytes sent as streaming tail events during execution |

**Commands dispatched by `invoke.ts`:**

| Command | Purpose |
|---|---|
| `system.which` | Resolves binary paths (uses `SkillBinsCache`) |
| `system.exec-approvals-set` | Updates the approval list for a command or command pattern |
| `system.exec-approvals-get` | Returns the current approval list |
| `system.run` | Executes a shell command subject to execution policy |
| `system.notify` | Sends a notification through the device's native notification channel |
| Plugin-contributed commands | Any `OpenClawPluginNodeHostCommand` registered by installed plugins |

### Execution Policy

| Type / Symbol | Location | Notes |
|---|---|---|
| `SystemRunPolicyDecision` | `src/node-host/exec-policy.ts` | Structured allow/deny result; includes a `reason` string included in error messages on denial |
| `ExecSecurity` | `src/node-host/exec-policy.ts` | `"deny" \| "allowlist" \| "full"` — overall security stance for command execution |
| `ExecAsk` | `src/node-host/exec-policy.ts` | `"never" \| "on-miss" \| "always"` — whether to prompt the user for approval |

Shell wrapper blocking produces a structured error with diagnostic text:

```
SYSTEM_RUN_DENIED: allowlist miss (shell wrappers like sh/bash/zsh -c require approval...)
```

The same pattern applies to Windows `cmd.exe /c`. The diagnostic text is intentionally included in the denial reason so that callers and logs can distinguish an allowlist miss from other policy failures.

### Plugin Extension

| Type | Location | Purpose |
|---|---|---|
| `OpenClawPluginNodeHostCommand` | `src/node-host/plugin-node-host.ts` | Interface that plugins implement to register additional invocable commands on a node host |

## Architecture

### Connection and Registration

When the node host process starts, `runner.ts` calls `resolveGatewayConnectionAuth()` to obtain gateway credentials, then opens a `GatewayClient` connection to the configured `gatewayHost:gatewayPort`. After the connection is established, `loadOrCreateDeviceIdentity()` loads or generates a stable device ID that persists across restarts. `ensureNodeHostPluginRegistry()` initializes the plugin system, and `listRegisteredNodeHostCapsAndCommands()` collects all built-in and plugin-contributed commands. This manifest is sent to the gateway, which records the node host's capabilities for routing invocation requests.

`NodeHostGatewayConfig` (loaded from disk via `ensureNodeHostConfig()`) holds settings that survive process restarts — specifically the gateway address and any persisted approval lists. The `SkillBinsCache` avoids repeated filesystem `which` lookups by caching resolved binary paths with a 90-second TTL.

### Invocation Dispatch

Incoming invocation requests from the gateway arrive as `NodeInvokeRequestPayload` frames. `invoke.ts` reads the `command` field and routes to the appropriate handler. For `system.run`, the handler first calls into `exec-policy.ts` to obtain a `SystemRunPolicyDecision` before starting any subprocess. If the decision is `deny`, the invocation returns immediately with the denial reason. If the decision is `allow`, the subprocess is started with `DEFAULT_NODE_PATH` set as `PATH`; output is capped at `OUTPUT_CAP` bytes total, with streaming tail events limited to `OUTPUT_EVENT_TAIL` bytes.

The `idempotencyKey` field on `NodeInvokeRequestPayload` allows the gateway to safely retry invocations on transient failures without risk of duplicate execution — the node host deduplicates requests with matching keys within the lifetime of the invocation.

### Execution Policy Evaluation

`exec-policy.ts` produces a `SystemRunPolicyDecision` by evaluating the requested command against the current `ExecSecurity` and `ExecAsk` configuration:

- `"deny"` mode: all `system.run` calls are rejected regardless of the command.
- `"allowlist"` mode: only commands that match an entry in the persisted approval list are allowed. Shell wrapper patterns (`sh -c`, `bash -c`, `zsh -c`, `cmd.exe /c`) are never auto-approved even if a wildcard allowlist entry would otherwise match them; they require an explicit approval entry.
- `"full"` mode: all commands are allowed without approval.

When `ExecAsk` is `"on-miss"`, a command that would otherwise be denied under `"allowlist"` mode is instead held pending user approval. The approval decision is persisted via `system.exec-approvals-set` so subsequent calls for the same command do not require re-approval.

### Plugin-Contributed Commands

`src/node-host/plugin-node-host.ts` defines the `OpenClawPluginNodeHostCommand` interface. Plugins implement this interface to register custom invocable commands. Registered commands are included in the capability manifest advertised to the gateway at startup and dispatched by `invoke.ts` alongside built-in system commands.

## Runtime Behavior

### Node Host Startup Sequence

1. `runner.ts` calls `resolveGatewayConnectionAuth()` to retrieve gateway credentials.
2. `ensureNodeHostConfig()` loads `NodeHostGatewayConfig` from disk (or creates it with defaults).
3. `loadOrCreateDeviceIdentity()` loads a persisted device UUID or generates and persists a new one.
4. `ensureNodeHostPluginRegistry()` initializes the plugin system; plugins register their `OpenClawPluginNodeHostCommand` entries.
5. `listRegisteredNodeHostCapsAndCommands()` collects the full command manifest (built-in + plugin-contributed).
6. `GatewayClient.connect()` opens the connection to `gatewayHost:gatewayPort` with optional TLS and fingerprint verification.
7. The node host sends its capability manifest to the gateway; the gateway records the device as available for routing.
8. The `SkillBinsCache` is initialized (empty; entries are populated on first `system.which` call).
9. The runner enters the event loop, waiting for `NodeInvokeRequestPayload` frames from the gateway.

### Command Invocation: `system.run`

1. A `NodeInvokeRequestPayload` with `command = "system.run"` arrives from the gateway.
2. `invoke.ts` parses `paramsJSON` and extracts the command string and environment.
3. `exec-policy.ts` is called; it produces a `SystemRunPolicyDecision`.
   - If `ExecSecurity = "deny"`: returns denial immediately with reason.
   - If command is a shell wrapper (`sh/bash/zsh -c` or `cmd.exe /c`) and no explicit approval exists: returns `SYSTEM_RUN_DENIED` with diagnostic text.
   - If `ExecSecurity = "allowlist"` and no match: returns denial, or triggers an approval request if `ExecAsk = "on-miss"`.
   - If `ExecSecurity = "full"` or an allowlist match exists: decision is `allow`.
4. If allowed, a subprocess is spawned with `DEFAULT_NODE_PATH` set as `PATH` and `timeoutMs` enforced.
5. Output is streamed back as events, capped at `OUTPUT_EVENT_TAIL = 20 000` bytes per tail event. Total output is capped at `OUTPUT_CAP = 200 000` bytes.
6. On process exit, the final result (exit code, truncation flag if applicable) is returned to the gateway as the invocation response.

## Source Files

| File | Purpose |
|---|---|
| `src/node-host/runner.ts` | `NodeHostRunOptions`; `NodeHostGatewayConfig` loading; device identity; plugin registry; `SkillBinsCache`; gateway event loop |
| `src/node-host/invoke.ts` | `NodeInvokeRequestPayload`; command dispatch table; `OUTPUT_CAP`; `OUTPUT_EVENT_TAIL` |
| `src/node-host/exec-policy.ts` | `SystemRunPolicyDecision`; `ExecSecurity`; `ExecAsk`; shell wrapper blocking; policy evaluation logic |
| `src/node-host/plugin-node-host.ts` | `OpenClawPluginNodeHostCommand` interface; plugin-contributed command registration |
| `src/pairing/` | Device pairing tokens, identity lifecycle, and connection management between gateway and native clients |

## See Also

- [Gateway Control Plane](gateway-control-plane.md)
- [Agent Runtime](agent-runtime.md)
- [Canvas and Control UI](canvas-and-control-ui.md)
- [Device Augmented Agent Architecture](../concepts/device-augmented-agent-architecture.md)
- [Canvas Voice and Device Control Loop](../syntheses/canvas-voice-and-device-control-loop.md)
