# Local-First Personal Assistant Architecture

## Overview

OpenClaw is designed to run on the user's own devices and accounts rather than primarily inside a hosted SaaS shell. The gateway runs as a local process, channel integrations use the user's own bot credentials, the model communicates directly with AI providers using the user's own API keys, and native apps connect directly to the local gateway without relaying through a third-party cloud. This architecture shapes nearly every design decision: the filesystem-first configuration model, the local `openclaw.yml` config, the keychain-based secrets storage, the node-host pairing model, and the gateway-as-control-plane invariant all reflect the premise that the user's data and conversations stay on their infrastructure.

## Why It Exists

The VISION.md in the repository frames this explicitly: the goal is a personal assistant that is persistent, device-aware, multi-channel, and genuinely under the user's control. A hosted SaaS model would require routing all conversations through a third-party server, which conflicts with the goal of personal control. Instead, OpenClaw runs the gateway locally and connects outward to channels and providers, rather than being a wrapper around a central service.

This has concrete architectural consequences:
- Auth credentials live in the OS keychain, not in a hosted database.
- Session transcripts are stored locally in the state directory (`~/.openclaw/state/`).
- The gateway's REST/WebSocket surface is exposed locally or via Tailscale, not via a public internet endpoint.
- Remote exposure (`fly.toml`, `render.yaml`) exists as an option, not the default.

## Mechanism

### Local Gateway as the Authority

The gateway is the user's local control plane. It starts via `openclaw gateway start` or a launchd/systemd unit, runs as a background process, and all other components (CLI, mobile apps, channels) connect to it on `localhost` or a VPN address. The gateway's `openclaw.yml` lives in the user's home directory, and its state dir (`resolveStateDir()`) holds SQLite databases, session transcripts, and exec approval records.

### Filesystem-First Configuration

All configuration is files the user can read and edit:
- `openclaw.yml` — main config: agents, channels, bindings, plugins, model preferences
- `~/.openclaw/skills/` — user's personal skills (markdown files)
- `~/.openclaw/agents/<id>/agent/` — per-agent workspace
- `~/.openclaw/plugins/` — user-installed plugins
- `~/.openclaw/state/exec-approvals.json` — exec approval record

The CLI's wizard flow (`runSetupWizard()`) writes to these files; there is no remote config store. `CLAUDE.md` and `AGENTS.md` in working directories follow the same filesystem-first pattern.

### Direct Provider Connections

The agent runtime connects directly to AI providers (Anthropic, OpenAI, etc.) using the user's own credentials. There is no OpenClaw relay in the API call path — the request goes from the gateway process to the provider's API endpoint. This means API usage appears in the user's provider dashboard, not OpenClaw's.

### Device Presence Without Cloud Relay

Mobile apps (iOS, Android, macOS) pair directly with the user's gateway via device token authentication. The pairing flow generates a QR code or deep link; the app authenticates with the gateway on the local network or Tailscale mesh. Once paired, the app communicates directly with the gateway — no relay through an OpenClaw cloud service.

### Optional Remote Exposure

For users who want gateway access outside their local network, OpenClaw supports:
- **Tailscale** — mesh VPN integration (`startGatewayTailscaleExposure()`, `readTailscaleWhoisIdentity()`). The gateway is reachable on the Tailscale network by trusted devices.
- **Fly.io / Render** — `fly.toml` and `render.yaml` in the repo enable deploying the gateway as a cloud process for users who want persistent remote access without a home server.
- **Self-hosted VPS** — the gateway runs on any machine; clients point their gateway URL to it.

These are deployment options, not the default.

### Local Secrets Storage

`src/secrets/` manages credential storage using the OS keychain (macOS Keychain, Linux SecretService, Windows Credential Manager). Provider API keys and channel OAuth tokens are stored per-credential entry keyed by provider/channel ID. `activateSecretsRuntimeSnapshot()` loads all secrets into a runtime snapshot at gateway startup, making them accessible without repeated keychain I/O.

## Operational Implications

- Offline operation: conversations work as long as the local gateway and AI provider API are reachable. Channel polling continues without an OpenClaw cloud dependency.
- Data locality: transcripts and session state stay in `~/.openclaw/state/` unless the user explicitly exports or syncs them.
- Credential sovereignty: rotating or revoking API keys happens in the user's provider dashboard; OpenClaw has no copy in a remote database.
- Deployment flexibility: the same gateway code runs on a MacBook, a Raspberry Pi, or a cloud VM.

## Involved Entities

- [Gateway Control Plane](../entities/gateway-control-plane.md) — local control plane implementation
- [CLI and Onboarding](../entities/cli-and-onboarding.md) — filesystem-first setup wizard
- [Node Host and Device Pairing](../entities/node-host-and-device-pairing.md) — direct device pairing
- [Native Apps and Platform Clients](../entities/native-apps-and-platform-clients.md) — local-first app clients
- [Skills Platform](../entities/skills-platform.md) — skills are local markdown files

## Source Evidence

| File | Contribution |
|------|-------------|
| `src/config/paths.ts` | `resolveStateDir()` — local state directory resolution |
| `openclaw.yml` (user file) | Main config file in user's home directory |
| `src/wizard/setup.ts` | `runSetupWizard()` — writes config to local filesystem |
| `src/secrets/runtime.ts` | `activateSecretsRuntimeSnapshot()` — local keychain access |
| `src/gateway/server-tailscale.ts` | `startGatewayTailscaleExposure()` — Tailscale mesh integration |
| `fly.toml`, `render.yaml` | Optional cloud deployment descriptors |
| `src/infra/device-identity.ts` | `loadOrCreateDeviceIdentity()` — per-device identity |
| `VISION.md` | Design intent and local-first framing |

## See Also

- [Gateway as Control Plane](gateway-as-control-plane.md)
- [Auth and Approval Boundaries](auth-and-approval-boundaries.md)
- [Node Host and Device Pairing](../entities/node-host-and-device-pairing.md)
- [Onboarding to Live Gateway Flow](../syntheses/onboarding-to-live-gateway-flow.md)
- [Device Augmented Agent Architecture](device-augmented-agent-architecture.md)
