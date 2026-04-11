# OpenClaw Architecture Wiki — Index

> Master catalog of the OpenClaw sub-wiki.

| Meta | Value |
|------|-------|
| **Pages** | 32 |
| **Last Updated** | 2026-04-06 |
| **Last Lint** | 2026-04-06 |

---

## Summaries

| Page | Description |
|------|-------------|
| [Architecture Overview](summaries/architecture-overview.md) | High-level orientation to OpenClaw as a local-first personal assistant platform |
| [Codebase Map](summaries/codebase-map.md) | Maps `src/`, `extensions/`, `apps/`, `skills/`, and `docs/` to the corresponding wiki pages |
| [Glossary](summaries/glossary.md) | Definitions for recurring OpenClaw terms, protocols, and runtime concepts |

## Entities

| Page | Description |
|------|-------------|
| [Gateway Control Plane](entities/gateway-control-plane.md) | Gateway server startup, auth, sessions, plugin bootstrap, and control-plane duties |
| [CLI and Onboarding](entities/cli-and-onboarding.md) | CLI entry points, onboarding, doctor, daemon, and update flows |
| [Agent Runtime](entities/agent-runtime.md) | Pi/agent execution, tools, prompts, embedded runners, and sandbox edges |
| [Session System](entities/session-system.md) | Session identity, lifecycle, provenance, send policy, and transcript events |
| [Channel System](entities/channel-system.md) | Channel abstractions, gating, typing, metadata, and reply-facing conventions |
| [Channel Plugin Adapters](entities/channel-plugin-adapters.md) | Plugin-backed channel integrations, bindings, pairing, setup, and approvals |
| [Plugin Platform](entities/plugin-platform.md) | Loader, manifests, install/uninstall, registry state, and runtime activation |
| [Provider and Model System](entities/provider-and-model-system.md) | Provider catalogs, auth choices, model selection, and failover surfaces |
| [Routing System](entities/routing-system.md) | Account, peer, and binding-based route resolution into agent/session targets |
| [Automation and Cron](entities/automation-and-cron.md) | Scheduled jobs, isolated-agent execution, delivery, and timer service |
| [Canvas and Control UI](entities/canvas-and-control-ui.md) | Canvas host, A2UI, and web/control-plane presentation surfaces |
| [Node Host and Device Pairing](entities/node-host-and-device-pairing.md) | Remote device execution, pairing, invocation, and capability policies |
| [MCP and ACP Bridges](entities/mcp-and-acp-bridges.md) | MCP server surfaces and ACP translation between gateway and editors |
| [Media and Voice Stack](entities/media-and-voice-stack.md) | Media understanding/generation, transcription, TTS, and realtime voice |
| [Skills Platform](entities/skills-platform.md) | Bundled, managed, and workspace skills plus skill refresh/integration |
| [Native Apps and Platform Clients](entities/native-apps-and-platform-clients.md) | macOS, iOS, Android, shared UI, and client-facing runtime surfaces |

## Concepts

| Page | Description |
|------|-------------|
| [Local First Personal Assistant Architecture](concepts/local-first-personal-assistant-architecture.md) | OpenClaw as a user-owned assistant centered on a local gateway |
| [Gateway as Control Plane](concepts/gateway-as-control-plane.md) | Why the gateway owns sessions, channels, tools, config, and UI surfaces |
| [Multi Channel Session Routing](concepts/multi-channel-session-routing.md) | How inbound channels and accounts map into isolated sessions and agents |
| [Pluginized Capability Delivery](concepts/pluginized-capability-delivery.md) | Providers, channels, and tools delivered through plugin activation |
| [Device Augmented Agent Architecture](concepts/device-augmented-agent-architecture.md) | Nodes, canvas, apps, and device execution as agent extensions |
| [Auth and Approval Boundaries](concepts/auth-and-approval-boundaries.md) | Tokens, passwords, allowlists, approvals, and safety envelopes |
| [Isolated Agent Automation](concepts/isolated-agent-automation.md) | Cron jobs and other background tasks as isolated-agent workloads |

## Syntheses

| Page | Description |
|------|-------------|
| [Inbound Message to Agent Reply Flow](syntheses/inbound-message-to-agent-reply-flow.md) | End-to-end flow from channel ingress through routing, session, agent, and reply dispatch |
| [Onboarding to Live Gateway Flow](syntheses/onboarding-to-live-gateway-flow.md) | Install, configure, daemonize, and bring a live OpenClaw gateway online |
| [Extension to Runtime Capability Flow](syntheses/extension-to-runtime-capability-flow.md) | How extensions become active providers, channels, or tools in the runtime |
| [Scheduled Job Delivery Flow](syntheses/scheduled-job-delivery-flow.md) | How cron normalization, isolated execution, delivery, and cleanup compose |
| [Channel Binding and Session Identity Flow](syntheses/channel-binding-and-session-identity-flow.md) | How bindings, account IDs, routes, and session keys compose |
| [Canvas Voice and Device Control Loop](syntheses/canvas-voice-and-device-control-loop.md) | How canvas, voice, nodes, and native clients form one interaction loop |
