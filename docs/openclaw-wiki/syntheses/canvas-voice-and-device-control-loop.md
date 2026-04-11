# Canvas Voice and Device Control Loop

## Overview

OpenClaw exposes three distinct interaction surfaces to the user: a visual canvas/control UI in the browser, a voice interface through native mobile and desktop apps, and a device command execution layer via paired node hosts. This synthesis traces how all three surfaces connect to the same underlying agent runtime and session system, and how output from one loop can trigger another.

The key insight is that these are not independent products. A voice query can result in a canvas update. A canvas interaction can trigger a device command. A device command result can be spoken back via TTS. All three paths converge on a single agent turn, which produces a single reply that may fan out to multiple surfaces. Understanding the handoff points and shared session state is essential for diagnosing failures and reasoning about what can run concurrently.

## Systems Involved

| System | Contribution |
|---|---|
| [Native Apps and Platform Clients](../entities/native-apps-and-platform-clients.md) | iOS, Android, macOS apps; microphone/audio capture; typed WebSocket frame protocol |
| [Media and Voice Stack](../entities/media-and-voice-stack.md) | `RealtimeVoiceBridge`, TTS synthesis, audio transcoding via `ffmpeg` |
| [Canvas and Control UI](../entities/canvas-and-control-ui.md) | Canvas host serving, A2UI, Control UI WebSocket frame protocol |
| [Node Host and Device Pairing](../entities/node-host-and-device-pairing.md) | `system.run` execution, exec policy enforcement, device pairing lifecycle |
| [Local-First Personal Assistant Architecture](../concepts/local-first-personal-assistant-architecture.md) | Single local gateway as shared session authority; direct provider connections |

## The Three Interaction Loops

### Voice Input/Output Loop

The voice loop begins at the platform client — typically an iOS or Android app that has been paired with the gateway — and runs bidirectionally through the agent runtime and back.

**Step-by-step path:**

1. The user speaks into the native app. The app captures audio (mu-law encoded PCM) and streams it to the gateway over the existing WebSocket connection, identified by a `ConnectParams` frame that established the session.

2. The gateway routes the audio stream to an active `RealtimeVoiceBridge`. The bridge is opened by calling the configured realtime voice provider (e.g., an OpenAI Realtime API connection), and it wires up `RealtimeVoiceBridgeCallbacks`:

   ```ts
   // src/realtime-voice/provider-types.ts
   type RealtimeVoiceBridgeCallbacks = {
     onAudio: (muLaw: Buffer) => void;       // receive audio from bridge to send back to client
     onClearAudio: () => void;               // flush buffered audio on barge-in
     onMark?: (markName: string) => void;    // media timestamp synchronization marker
     onTranscript?: (role, text, isFinal) => void; // incremental transcription delivery
     onToolCall?: (event: RealtimeVoiceToolCallEvent) => void; // model-invoked tool during session
     onReady?: () => void;                   // bridge established, ready for audio
     onError?: (error: Error) => void;
     onClose?: (reason: "completed" | "error") => void;
   };
   ```

3. Inbound mu-law audio is sent to the provider via `RealtimeVoiceBridge.sendAudio(audio)`. The provider transcribes and generates a reply, streaming audio back via `onAudio` callbacks.

4. `onTranscript` delivers the incremental user transcript to the agent session for logging and context. When `isFinal` is true, the transcript is committed to session history.

5. If the model calls a registered tool during the voice session, `onToolCall` fires. Tool results are injected back into the provider session. Tools registered with the voice bridge follow the same JSON schema function contract as agent tools, so the agent's full tool set is available during a voice turn.

6. The outbound audio stream from `onAudio` is relayed to the native app over the same WebSocket connection. The app plays it through the device speaker. `onClearAudio` allows the system to interrupt playback (barge-in detection) when the user speaks again.

7. On session end, `onClose` fires with `"completed"` or `"error"`. The bridge is torn down and the session record is updated.

For non-interactive TTS (e.g., a voice note reply in a messaging channel), the path is shorter: the agent produces reply text, the TTS pipeline parses any embedded directives via `parseTtsDirective()`, calls the active TTS provider's `synthesize()` method, and the resulting audio bytes are delivered through the channel's outbound adapter.

### Canvas/Control UI Loop

The canvas loop covers two sub-surfaces: the full Control UI (React app, served from `ui/`) and the canvas host (user-authored canvas applications plus the A2UI embedded interface).

**Control UI path (user types in the management dashboard):**

1. The user types a message or interacts with a control in the React Control UI. The frontend sends a typed `RequestFrame` over the existing WebSocket connection to the gateway. There is no REST API — all state changes are expressed as typed frames.

2. The gateway dispatches the frame to the appropriate internal subsystem (session management, channel interaction, config update). If the frame initiates an agent turn, it is routed to the agent runtime with the session context attached.

3. The agent runtime produces a reply. The gateway emits one or more `EventFrame` pushes over the WebSocket connection back to the frontend. The Control UI applies the updates reactively — transcript entries, session status, channel state — without polling.

**Canvas host / A2UI path (agent pushes UI to the user's browser):**

1. During an agent turn, the agent may decide to render a canvas application or A2UI component. This is expressed as an agent action targeting the canvas host.

2. The canvas host (`src/canvas-host/server.ts`) serves user-authored files from its configured `rootDir` under `CANVAS_HOST_PATH` (`/__openclaw__/canvas`). The A2UI is served separately under `A2UI_PATH` (`/__openclaw__/a2ui`).

3. The `CanvasHostOpts` type governs the full canvas host configuration:

   ```ts
   // src/canvas-host/server.ts
   type CanvasHostOpts = {
     runtime: ...,
     rootDir?: string,
     port?: number,
     listenHost?: string,
     liveReload?: boolean,
     watchFactory?: ...,
     webSocketServerClass?: ...,
   };
   ```

4. If `liveReload` is enabled, `chokidar` watches `rootDir`. When files change, all connected WebSocket clients on `CANVAS_WS_PATH` (`/__openclaw__/ws`) receive a reload notification, enabling hot-reload development workflows.

5. The Control UI itself is served directly by the gateway. At startup, `handleControlUiRequest()` computes a `Content-Security-Policy` header via `buildControlUiCspHeader()`, hashing any inline scripts found by `computeInlineScriptHashes()`. The constant `CONTROL_UI_CONTENT_SECURITY_POLICY_DEFAULTS` provides the base CSP directive set that these hashes are appended to. The `CONTROL_UI_BOOTSTRAP_CONFIG_PATH` constant identifies the JSON block injected into `index.html` before serving, providing the WebSocket URL and initial auth state without a separate API call.

6. Avatar images requested by the Control UI are resolved and served under `CONTROL_UI_AVATAR_PREFIX` (`/avatar/...`) directly by the gateway handler, avoiding cross-origin issues.

### Device Command Execution Loop

The device command loop runs between the agent runtime and a paired node host. Unlike voice and canvas, this loop involves an explicit policy enforcement step before execution.

**Step-by-step path:**

1. The agent runtime, during a turn, invokes `system.run` (or another node-host command) targeting a specific `nodeId`. This invocation is packaged as a `NodeInvokeRequestPayload`:

   ```ts
   // src/node-host/invoke.ts
   type NodeInvokeRequestPayload = {
     id: string;
     nodeId: string;
     command: string;
     paramsJSON?: string;
     timeoutMs?: number;
     idempotencyKey?: string;
   };
   ```

2. The gateway routes the payload to the connected node host identified by `nodeId`. If the node host is disconnected, the invocation is held or failed immediately.

3. The node host's `invoke.ts` reads the `command` field and routes to the appropriate handler. For `system.run`, the handler calls `exec-policy.ts` first.

4. `exec-policy.ts` evaluates the command against the current policy configuration and returns a `SystemRunPolicyDecision`:

   - `ExecSecurity` (`"deny" | "allowlist" | "full"`) controls the overall stance:
     - `"deny"`: all `system.run` calls are rejected.
     - `"allowlist"`: only commands matching the persisted approval list are allowed.
     - `"full"`: all commands are allowed without approval.
   - `ExecAsk` (`"never" | "on-miss" | "always"`) controls whether to prompt the user:
     - `"never"`: no approval prompts; decisions are made by policy alone.
     - `"on-miss"`: an `"allowlist"` miss triggers an approval request rather than immediate denial.
     - `"always"`: every execution requires explicit user approval.
   - Shell wrapper invocations (`sh -c`, `bash -c`, `zsh -c`, `cmd.exe /c`) are always blocked under `"allowlist"` mode unless an explicit approval entry exists, producing a `SYSTEM_RUN_DENIED` error with diagnostic text.

5. If approved, the subprocess is spawned with `DEFAULT_NODE_PATH` set as `PATH`. Output is streamed back as events, capped at `OUTPUT_EVENT_TAIL` (20,000 bytes) per tail event and `OUTPUT_CAP` (200,000 bytes) total.

6. On process exit, the node host returns the result (exit code, output, truncation flag) to the gateway as the invocation response. The gateway delivers the result back to the agent runtime, which incorporates it into the ongoing turn context.

## Shared Agent Runtime and Session

All three loops converge on a single agent runtime instance, governed by a single session. This has concrete implications:

- **Session identity is shared.** The same session record — including transcript history, agent state, and tool context — is visible across all three surfaces simultaneously. A voice turn that queries device state can reference results from a previous canvas interaction without re-establishing context.

- **The gateway is the session authority.** As described in [Local-First Personal Assistant Architecture](../concepts/local-first-personal-assistant-architecture.md), the gateway runs locally and holds all session state in `~/.openclaw/state/`. No relay through a third-party cloud is required for any of the three loops.

- **Direct provider connections.** The agent runtime connects directly to AI providers (Anthropic, OpenAI, etc.) using the user's own API credentials. The voice bridge, TTS synthesis, and agent text turns all go directly from the gateway to provider endpoints.

- **The five-step device pairing flow establishes node host identity before any device command loop can start:**
  1. The gateway generates a pairing token.
  2. The native app scans the QR code or receives the token via the `OPENCLAW_GATEWAY_URL` URL scheme.
  3. The app authenticates with the gateway using the device token.
  4. The gateway registers the device and assigns a stable `nodeId`.
  5. The app starts a node host process (`src/node-host/runner.ts`) that connects back to the gateway; the node host advertises its full capability manifest (built-in commands plus plugin-contributed `OpenClawPluginNodeHostCommand` entries).

Once this pairing is complete, the gateway has an authoritative record of which node host is trusted for which operations, and the device command loop can proceed.

## Concurrency Invariants

Understanding what can run simultaneously and what is serialized prevents a class of reasoning errors about system behavior.

**What can run simultaneously:**

- A voice session and a canvas update can be active at the same time if they involve separate agent turns or separate sessions. The realtime voice bridge is managed per-session, so two simultaneous sessions (e.g., two paired clients) can each have an active bridge.
- File serving from the canvas host is fully concurrent — the HTTP server handles multiple requests in parallel, and live-reload WebSocket broadcasts go to all connected clients simultaneously.
- Node host command invocations with different `idempotencyKey` values are dispatched independently; the node host can run multiple subprocesses in parallel up to the limits imposed by the host OS and policy.
- TTS synthesis calls are independent of realtime voice bridge sessions; a channel can synthesize a voice note while a separate realtime session is active.

**What is serialized:**

- Within a single agent session, turns are serialized. A new input (voice transcript, canvas frame, device result) that arrives while a turn is in progress is queued until the current turn completes. This prevents interleaved writes to the agent's context window.
- The exec approval flow under `ExecAsk = "on-miss"` or `"always"` is synchronous from the invocation's perspective: the node host holds the invocation pending until the user approves or denies. No other invocation with the same command pattern can proceed concurrently if they would hit the same pending approval request.
- Control UI bootstrap config injection (`CONTROL_UI_BOOTSTRAP_CONFIG_PATH`) happens once at gateway startup; subsequent requests read the pre-computed value without re-computing.

## Failure Modes

### Voice Disconnection

If the WebSocket connection between the native app and the gateway drops during a voice session, `onClose` fires on the `RealtimeVoiceBridge` with reason `"error"`. The bridge is torn down, and any buffered outbound audio is discarded. The realtime voice provider connection is also closed.

The native app enters reconnect backoff. The gateway retains the session state — the transcript up to the disconnection point is preserved. When the client reconnects and re-establishes the session, it can resume from the saved state. However, any in-flight voice turn that had not yet completed is lost; the partial transcript (delivered via `onTranscript` with `isFinal = false`) is not committed to session history.

### Canvas Session Loss

If the Control UI WebSocket connection drops, the frontend loses its real-time event stream. The Control UI will attempt to reconnect. On reconnect, the gateway sends an initial state snapshot in the `HelloOk` acknowledgment, allowing the frontend to resynchronize without replaying the full event history. Canvas host live-reload clients similarly reconnect and re-register; no reload notifications are missed during the gap (the next file change will trigger a reload after reconnect).

If the canvas host process itself terminates (e.g., the gateway restarts), any connected WebSocket clients on `CANVAS_WS_PATH` will receive a close event. Their behavior depends on the canvas application's own reconnect logic. The A2UI (`/__openclaw__/a2ui`) is served from the same process, so it is also unavailable until the canvas host restarts.

### Exec Approval Timeout

When `ExecAsk = "on-miss"` or `"always"` causes a `system.run` invocation to be held pending user approval, the invocation will time out if the user does not respond within `timeoutMs` (from `NodeInvokeRequestPayload`). On timeout, the node host returns a denial to the gateway, and the agent runtime receives a tool call error. The agent can communicate this to the user in the next turn.

If the native app that would display the approval prompt is disconnected at the time the approval request is generated, the request may go unseen. The exec approval record (`~/.openclaw/state/exec-approvals.json`) is only written after an explicit approval via `system.exec-approvals-set`; a timeout does not write a denial record, so the same command will trigger another approval request on the next invocation.

## Source Evidence

| File | Contribution |
|---|---|
| `src/realtime-voice/provider-types.ts` | `RealtimeVoiceBridge`, `RealtimeVoiceBridgeCallbacks`, `RealtimeVoiceTool` |
| `src/tts/provider-types.ts` | `SpeechProviderId`, `TtsDirectiveParseResult`, `SpeechModelOverridePolicy` |
| `src/canvas-host/server.ts` | `CanvasHostOpts`, `CanvasHostServer`, `CANVAS_HOST_PATH`, `CANVAS_WS_PATH` |
| `src/canvas-host/a2ui.ts` | `A2UI_PATH`, `handleA2uiHttpRequest()`, `injectCanvasLiveReload()` |
| `src/gateway/control-ui.ts` | `handleControlUiRequest()`, `buildControlUiCspHeader()`, `computeInlineScriptHashes()`, `CONTROL_UI_BOOTSTRAP_CONFIG_PATH`, `CONTROL_UI_AVATAR_PREFIX`, `CONTROL_UI_CONTENT_SECURITY_POLICY_DEFAULTS` |
| `src/node-host/runner.ts` | `NodeHostRunOptions`, `NodeHostGatewayConfig`, `SkillBinsCache`, gateway event loop |
| `src/node-host/invoke.ts` | `NodeInvokeRequestPayload`, command dispatch, `OUTPUT_CAP`, `OUTPUT_EVENT_TAIL` |
| `src/node-host/exec-policy.ts` | `SystemRunPolicyDecision`, `ExecSecurity`, `ExecAsk`, shell wrapper blocking |
| `src/pairing/` | Device pairing token generation, identity persistence, connection management |
| `src/gateway/client.ts` | `GatewayClient` — base WebSocket client used by all native apps and the node host |
| `src/media/ffmpeg-exec.ts` | Audio transcoding supporting the voice pipeline |

## See Also

- [Device Augmented Agent Architecture](../concepts/device-augmented-agent-architecture.md)
- [Local-First Personal Assistant Architecture](../concepts/local-first-personal-assistant-architecture.md)
- [Canvas and Control UI](../entities/canvas-and-control-ui.md)
- [Media and Voice Stack](../entities/media-and-voice-stack.md)
- [Node Host and Device Pairing](../entities/node-host-and-device-pairing.md)
- [Native Apps and Platform Clients](../entities/native-apps-and-platform-clients.md)
- [Gateway As Control Plane](../concepts/gateway-as-control-plane.md)
- [Inbound Message To Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md)
