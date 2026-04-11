# Native Apps and Platform Clients

## Overview

OpenClaw ships beyond the CLI. The repository includes macOS, iOS, and Android native apps (`apps/`), a shared app code library (`apps/shared/`), and the web-based Control UI (`ui/`). These clients connect to the gateway over the same typed WebSocket frame protocol used by the CLI. They are not optional demos — they are first-class product surfaces that provide persistent background presence, platform notifications, QR code pairing, Watch app integration (iOS), and native media capabilities (camera, microphone, telephony).

The native apps function as "node hosts" paired to a gateway. The iOS and Android apps install the `openclaw` CLI into the device environment and run it as a node host process, bridging the gap between a mobile keyboard and a full agent runtime. The macOS app provides a menu-bar presence, system notification delivery, and background gateway management without requiring a terminal.

## Architecture

### App Surfaces

| Surface | Location | Technology |
|---------|----------|-----------|
| macOS menu bar app | `apps/macos/` | Swift (`Package.swift`, SwiftUI) |
| iOS app | `apps/ios/` | Swift (Xcode project, `Package.swift`) |
| Android app | `apps/android/` | Android (Java/Kotlin, Gradle) |
| Shared app logic | `apps/shared/` | Cross-platform shared code |
| Control UI | `ui/` | Web (React, bundled by gateway) |

### Protocol Layer

All native clients communicate with the gateway using the same frame protocol as the CLI:
- `ConnectParams` frame with client `mode`, `version`, `platform`, and auth credentials
- `HelloOk` acknowledgment with protocol version, feature list, and initial snapshot
- `RequestFrame` / `ResponseFrame` for method calls
- `EventFrame` for push notifications (session updates, agent output, channel events)

Client modes (defined in `src/utils/message-channel.ts`): `GATEWAY_CLIENT_MODES` and `GATEWAY_CLIENT_NAMES` enumerate the known client types. Native apps identify themselves with a platform-specific mode string so the gateway can apply per-client policy.

### Node Host Pairing

The iOS and Android apps pair with the gateway via the device pairing flow (`src/pairing/`):
1. Gateway generates a pairing token.
2. App scans the QR code or receives the token via URL scheme.
3. App authenticates with the gateway using the device token.
4. Gateway registers the device and assigns a `nodeId`.
5. App starts a node host process (`src/node-host/runner.ts`) that connects back to the gateway.

Once paired, the mobile app's node host can execute `system.run` commands, respond to exec approval requests, and serve as the device-local execution environment for skills that require on-device binaries (e.g., `shortcuts`, `siri`, `say`).

### iOS-Specific Features

- **Watch app** (`apps/ios/WatchApp/`) — sends messages and receives assistant replies from the Apple Watch
- **Share extension** (`apps/ios/ShareExtension/`) — shares content from other apps directly into the assistant
- **Activity widget** (`apps/ios/ActivityWidget/`) — Live Activity widget showing agent status
- `OPENCLAW_GATEWAY_URL` URL scheme handling — deep-links to pair or resume sessions

The iOS app's gateway capability policy is managed in `src/gateway/android-node.capabilities.policy-source.ts` (despite the name, this covers both platforms) and `android-node.capabilities.policy-config.ts`.

### Android-Specific Features

- Standard activity and service lifecycle
- FCM push notifications for approval requests and session updates
- Deep link handling for pairing

### Control UI

The `ui/` web application is the browser-based control surface:
- Built with the `pnpm ui:build` command; outputs to `dist/` served by the gateway
- Communicates exclusively via the gateway WebSocket
- Shows live agent transcripts, channel status, session list, and settings
- Supports hot reload via the gateway's `ControlUiRootState` override mechanism during development (`OPENCLAW_CONTROL_UI_ROOT` env var)

The Control UI bootstrap config is injected into `index.html` at serve time via `CONTROL_UI_BOOTSTRAP_CONFIG_PATH`, providing the gateway URL and initial auth state before the WebSocket connects.

### Canvas A2UI

The A2UI (`/__openclaw__/a2ui`) is a lightweight browser-based interface embedded in the canvas host, distinct from the full Control UI. It is used for agent-to-user-interface interactions — the assistant can launch the A2UI to present forms, confirmations, or rich media to the user in a browser tab or embedded WebView.

## Connection Lifecycle

1. Native app/client calls `GatewayClient.connect(opts)` with gateway URL and credentials.
2. WebSocket handshake completes; client sends `ConnectParams`.
3. Gateway authenticates and responds with `HelloOk` + initial state snapshot.
4. Client enters event loop: listens for `EventFrame` pushes, sends `RequestFrame` for user actions.
5. On disconnect, client enters reconnect backoff; gateway retains session state.

## Source Files

| File | Purpose |
|------|---------|
| `apps/macos/` | macOS Swift app (menu bar, notifications, background gateway management) |
| `apps/ios/` | iOS Swift app (Watch, Share Extension, Activity Widget) |
| `apps/android/` | Android app |
| `apps/shared/` | Cross-platform shared app code |
| `ui/` | Control UI web application |
| `src/gateway/client.ts` | `GatewayClient` — base class used by all native app clients |
| `src/utils/message-channel.ts` | `GATEWAY_CLIENT_MODES`, `GATEWAY_CLIENT_NAMES` — client mode identifiers |
| `src/pairing/` | Device pairing flows and helpers |
| `src/gateway/device-auth.ts` | Device token auth handling |
| `src/gateway/android-node.capabilities.policy-source.ts` | Mobile node capability policy source |
| `src/gateway/android-node.capabilities.policy-config.ts` | Mobile node capability policy configuration |
| `src/canvas-host/server.ts` | Canvas host server for A2UI |
| `src/gateway/control-ui.ts` | Control UI serving and CSP |

## See Also

- [Gateway Control Plane](gateway-control-plane.md) — gateway the apps connect to
- [Node Host and Device Pairing](node-host-and-device-pairing.md) — node host runtime running on mobile devices
- [Canvas and Control UI](canvas-and-control-ui.md) — A2UI and Control UI surfaces served by the gateway
- [Device Augmented Agent Architecture](../concepts/device-augmented-agent-architecture.md)
- [Canvas Voice and Device Control Loop](../syntheses/canvas-voice-and-device-control-loop.md)
- [Local-First Personal Assistant Architecture](../concepts/local-first-personal-assistant-architecture.md)
