# Bridge System

## Overview

The Bridge (Remote Control) system connects the Claude Code CLI to the claude.ai web UI, enabling collaborative sessions where a user on claude.ai can drive a Claude Code instance running in a terminal. It uses poll-based event delivery, JWT authentication, and session management to bridge the gap between terminal and web environments. The system supports two major modes: a REPL bridge (always-on, embedded in an interactive CLI session via `replBridge.ts`) and a standalone bridge main loop (persistent multi-session server via `bridgeMain.ts`). Both share the same environment registration, work-poll, and session-ingress plumbing but differ in lifecycle -- the REPL bridge manages a single session within an existing REPL, while the main bridge spawns and supervises child processes for each session.

## Key Types

### BridgeConfig

Connection and runtime configuration for a bridge instance, defined in `types.ts`:

```ts
type BridgeConfig = {
  dir: string                     // working directory
  machineName: string             // hostname for display
  branch: string                  // current git branch
  gitRepoUrl: string | null       // repo URL for session cards
  maxSessions: number             // concurrent session cap
  spawnMode: SpawnMode            // 'single-session' | 'worktree' | 'same-dir'
  verbose: boolean
  sandbox: boolean
  bridgeId: string                // client-generated UUID
  workerType: string              // e.g. 'claude_code' or 'claude_code_assistant'
  environmentId: string           // client-generated UUID for idempotent registration
  reuseEnvironmentId?: string     // backend-issued ID for reconnect
  apiBaseUrl: string              // polling endpoint
  sessionIngressUrl: string       // WebSocket base URL
  debugFile?: string
  sessionTimeoutMs?: number       // per-session timeout (default 24h)
}
```

### WorkData and WorkSecret

When the server assigns work to a bridge environment, it returns a `WorkResponse` containing a `WorkData` discriminant and a base64url-encoded `WorkSecret`:

```ts
type WorkData = {
  type: 'session' | 'healthcheck'
  id: string
}

type WorkSecret = {
  version: number                              // must be 1
  session_ingress_token: string                // JWT for session ingress
  api_base_url: string
  sources: Array<{ type: string; git_info?: { ... } }>
  auth: Array<{ type: string; token: string }>
  claude_code_args?: Record<string, string>
  mcp_config?: unknown
  environment_variables?: Record<string, string>
  use_code_sessions?: boolean                  // CCR v2 selector
}
```

### BridgeApiClient

Interface abstracting all bridge HTTP calls -- environment registration, work polling, acknowledgement, heartbeat, stop, deregister, permission response relay, session archive, and session reconnect. Implemented by `createBridgeApiClient` in `bridgeApi.ts`.

### SessionHandle

Represents a running child session process:

```ts
type SessionHandle = {
  sessionId: string
  done: Promise<SessionDoneStatus>   // 'completed' | 'failed' | 'interrupted'
  kill(): void
  forceKill(): void
  activities: SessionActivity[]      // ring buffer (~10 recent)
  currentActivity: SessionActivity | null
  accessToken: string
  lastStderr: string[]
  writeStdin(data: string): void
  updateAccessToken(token: string): void
}
```

### ReplBridgeHandle

The handle returned by `initBridgeCore` for REPL-mode bridges, exposing write/send methods for messages, SDK messages, control requests/responses, and teardown.

### BridgePermissionCallbacks

Typed callback interface for delegating permission decisions from the CLI to the web UI:

```ts
type BridgePermissionCallbacks = {
  sendRequest(requestId, toolName, input, toolUseId, description, ...): void
  sendResponse(requestId, response: BridgePermissionResponse): void
  cancelRequest(requestId): void
  onResponse(requestId, handler): () => void   // returns unsubscribe
}
```

A `BridgePermissionResponse` carries `behavior: 'allow' | 'deny'` plus optional `updatedInput`, `updatedPermissions`, and `message`.

### SpawnMode

Controls how `claude remote-control` assigns working directories to sessions:

| Mode | Behavior |
|---|---|
| `single-session` | One session in cwd; bridge tears down when it ends |
| `worktree` | Persistent server; each session gets an isolated git worktree |
| `same-dir` | Persistent server; all sessions share cwd |

## Architecture

### Environment Registration

1. The bridge generates a client-side `environmentId` (UUID) and calls `registerBridgeEnvironment` with its `BridgeConfig`.
2. The server returns a backend-issued `environment_id` and `environment_secret`.
3. For reconnect scenarios (`--session-id` resume), a `reuseEnvironmentId` can be passed to rebind to an existing environment.

### Work Polling

The bridge enters a poll loop (`runBridgeLoop` in `bridgeMain.ts`, or the internal poll in `replBridge.ts`) that calls `pollForWork(environmentId, environmentSecret)`. The server returns a `WorkResponse` when a session is assigned, or null on timeout. The poll uses configurable intervals (`PollIntervalConfig`) with GrowthBook-backed live tuning and exponential backoff on errors.

### Session Lifecycle (bridgeMain.ts)

1. **Work received**: Decode `WorkSecret`, extract `session_ingress_token` and `api_base_url`.
2. **Acknowledge**: Call `acknowledgeWork` so the server marks the work item as claimed.
3. **Spawn**: Use `SessionSpawner` to start a child Claude Code process with `--sdk-url` pointing at the session ingress WebSocket (v1) or HTTP endpoint (CCR v2).
4. **Heartbeat**: Periodically call `heartbeatWork` using the session JWT to extend the work lease (default 5-minute TTL).
5. **Completion**: When the child exits, report status via `stopWork` and optionally `archiveSession`.
6. **Timeout watchdog**: Sessions exceeding `sessionTimeoutMs` (default 24h) are killed.

### Session Lifecycle (replBridge.ts -- REPL mode)

1. **initBridgeCore** receives `BridgeCoreParams` with injected dependencies (session creator, message mapper, OAuth handler) to avoid pulling the full REPL dependency tree into daemon bundles.
2. Registers the environment, creates a session via the injected `createSession` callback, and opens a `ReplBridgeTransport` (v1 WebSocket or v2 SSE via `HybridTransport`).
3. Flushes initial message history (capped by `initialHistoryCap`, default 200) to the web UI.
4. Handles inbound messages (`handleIngressMessage`), permission callbacks, model/mode changes, and interrupts via the `on*` callbacks.
5. Uses a `BoundedUUIDSet` for deduplication and a `FlushGate` to coordinate initial flush ordering.

### Session Ingress and SDK URLs

`workSecret.ts` provides URL builders:

- `buildSdkUrl`: Constructs `wss://host/v1/session_ingress/ws/{sessionId}` (production) or `ws://localhost/v2/...` (local dev). This is the v1 WebSocket path.
- `buildCCRv2SdkUrl`: Constructs `https://host/v1/code/sessions/{sessionId}` for CCR v2 SSE transport.
- `sameSessionId`: Compares session IDs across tag prefixes (`session_*` vs `cse_*`) by extracting the UUID suffix, handling the CCR v2 compat layer.

### Permission Delegation

When the CLI needs a permission decision and the bridge is active, it sends a `control_request` to the web UI via the session ingress. The web UI renders the permission prompt and sends back a `control_response` with `behavior: 'allow'` or `'deny'`. Validated by `isBridgePermissionResponse` type guard in `bridgePermissionCallbacks.ts`. The `BridgeApiClient.sendPermissionResponseEvent` method relays responses from the main bridge to child sessions.

## Bridge States

The bridge exposes its lifecycle through `AppState` fields consumed by the UI:

| AppState field | Meaning |
|---|---|
| `replBridgeEnabled` | Bridge feature is turned on |
| `replBridgeConnected` | Environment registered and session created successfully |
| `replBridgeSessionActive` | Ingress WebSocket/SSE connection is open (user is on claude.ai) |
| `replBridgeReconnecting` | Connection lost; exponential backoff in progress |
| `replBridgeError` | Failure state with error message |
| `replBridgeConnectUrl` | URL for connecting to the bridge |
| `replBridgeSessionUrl` | URL for the active session on claude.ai |
| `replBridgeEnvironmentId` | Backend environment ID |
| `replBridgeSessionId` | Current session ID |

The standalone `bridgeMain.ts` uses a simpler `BridgeState` union: `'ready' | 'connected' | 'reconnecting' | 'failed'`, reported via the `onStateChange` callback.

### Backoff Configuration

Connection recovery uses `BackoffConfig` with separate knobs for connection errors and general errors:

```ts
type BackoffConfig = {
  connInitialMs: number       // 2s default
  connCapMs: number           // 2min cap
  connGiveUpMs: number        // 10min give-up
  generalInitialMs: number    // 500ms default
  generalCapMs: number        // 30s cap
  generalGiveUpMs: number     // 10min give-up
  shutdownGraceMs?: number    // SIGTERM->SIGKILL grace (30s)
  stopWorkBaseDelayMs?: number
}
```

Sleep/wake detection threshold is set to 2x the connection backoff cap to avoid false positives from normal backoff delays.

## Security

### JWT Authentication

Session ingress tokens are JWTs included in the `WorkSecret`. They authenticate all session-level API calls (heartbeat, event push) without hitting the database. Token refresh is handled by `createTokenRefreshScheduler` in `jwtUtils.ts`. The `sessionIngressTokens` map in the main bridge loop tracks per-session JWTs separately from OAuth tokens.

### Trusted Device Registration

Bridge sessions have `SecurityTier=ELEVATED` on the server. The CLI participates in trusted device verification:

1. **Enrollment**: During `/login`, `enrollTrustedDevice()` calls `POST /auth/trusted_devices` with a display name. The server gates enrollment on `account_session.created_at < 10min` (must happen immediately after login).
2. **Storage**: The returned `device_token` is persisted to the OS keychain via `secureStorage`.
3. **Usage**: `getTrustedDeviceToken()` reads the cached token and includes it as `X-Trusted-Device-Token` in bridge API headers. Gated by the `tengu_sessions_elevated_auth_enforcement` GrowthBook flag (CLI-side and server-side flags are staged independently).
4. **Cache**: Token read is memoized (macOS `security` subprocess is ~40ms); cache is cleared on enrollment and logout.

### OAuth 401 Handling

The bridge accepts an `onAuth401` callback for refreshing expired OAuth tokens. In REPL mode this delegates to `handleOAuth401Error`; daemon callers supply their own `AuthManager` handler.

## Source Files

| File | Purpose |
|---|---|
| `bridge/types.ts` | Core type definitions: `BridgeConfig`, `WorkData`, `WorkSecret`, `SessionHandle`, `BridgeApiClient`, `SpawnMode`, `BridgeLogger` |
| `bridge/replBridge.ts` | REPL-mode bridge: `initBridgeCore`, poll loop, message flush, inbound handling, `ReplBridgeHandle` |
| `bridge/bridgeMain.ts` | Standalone bridge server: `runBridgeLoop`, multi-session management, spawn/heartbeat/timeout |
| `bridge/bridgeApi.ts` | HTTP client: `createBridgeApiClient`, environment CRUD, work poll/ack/stop/heartbeat |
| `bridge/bridgeMessaging.ts` | Message processing: `handleIngressMessage`, `handleServerControlRequest`, `makeResultMessage`, `BoundedUUIDSet` |
| `bridge/bridgePermissionCallbacks.ts` | Permission delegation types and `isBridgePermissionResponse` validator |
| `bridge/bridgeUI.ts` | Terminal UI: `createBridgeLogger`, status display, QR code, multi-session list |
| `bridge/bridgeConfig.ts` | Config construction helpers |
| `bridge/bridgeEnabled.ts` | Feature gate checks for bridge availability |
| `bridge/bridgePointer.ts` | Bridge pointer/URL management |
| `bridge/bridgeStatusUtil.ts` | Status formatting utilities (`formatDuration`) |
| `bridge/bridgeDebug.ts` | Fault injection and debug handles for testing |
| `bridge/workSecret.ts` | `decodeWorkSecret`, `buildSdkUrl`, `buildCCRv2SdkUrl`, `sameSessionId`, `registerWorker` |
| `bridge/trustedDevice.ts` | Trusted device enrollment and token management |
| `bridge/jwtUtils.ts` | JWT token refresh scheduling |
| `bridge/sessionRunner.ts` | `createSessionSpawner`: child process spawn logic |
| `bridge/sessionIdCompat.ts` | `toCompatSessionId` / `toInfraSessionId` for CCR v2 tag translation |
| `bridge/replBridgeTransport.ts` | Transport layer: `createV1ReplTransport` (WebSocket), `createV2ReplTransport` (SSE) |
| `bridge/replBridgeHandle.ts` | Handle wrapper for REPL bridge |
| `bridge/initReplBridge.ts` | REPL bridge initialization and bootstrap wiring |
| `bridge/createSession.ts` | Session creation via `POST /v1/sessions` |
| `bridge/codeSessionApi.ts` | CCR v2 code session API calls |
| `bridge/pollConfig.ts` | GrowthBook-backed poll interval configuration |
| `bridge/pollConfigDefaults.ts` | Default poll interval constants |
| `bridge/capacityWake.ts` | Signal to wake the at-capacity sleep early when a session completes |
| `bridge/flushGate.ts` | Coordination gate for initial message flush ordering |
| `bridge/inboundMessages.ts` | Inbound message processing |
| `bridge/inboundAttachments.ts` | Attachment handling for inbound messages |
| `bridge/envLessBridgeConfig.ts` | Bridge config for environment-less mode |
| `bridge/debugUtils.ts` | Debug/error formatting utilities |

## See Also

- [State Management](state-management.md)
- [Command System](command-system.md) (the /bridge and /remote-control commands)
- [Architecture Overview](../summaries/architecture-overview.md)
