# Codebase Map

## Overview

This map turns the openclaw/ tree into a reading plan. The goal is not only to say which folder maps to which page, but to show where control flow, state, policy, and extension points live so a newcomer can read the raw repository in an order that matches the architecture.

For OpenClaw, the most reliable pattern is to start with the modules that own runtime control or durable state, then move outward into adapters, protocol bridges, client shells, and examples. If you reverse that order, the repository can look broader and flatter than it really is.

## Control-Plane Core

| Source Area | Wiki Page | How To Read It |
| --- | --- | --- |
| `src/gateway/` | [Gateway Control Plane](../entities/gateway-control-plane.md) | Composition root for config loading, auth, plugin activation, channel startup, session wiring, node and device coordination, and HTTP and WebSocket serving. |
| `src/cli/`, `src/commands/`, and `src/wizard/` | [CLI And Onboarding](../entities/cli-and-onboarding.md) | User-facing setup, diagnostic, daemon, channel, plugin, and gateway commands. |
| `src/agents/` | [Agent Runtime](../entities/agent-runtime.md) | Model execution, tools, compaction, prompt shaping, failover, and embedded agent behavior. |
| `src/sessions/` | [Session System](../entities/session-system.md) | Session identity, send policy, transcript contracts, lifecycle events, and overrides. |
| `src/routing/` | [Routing System](../entities/routing-system.md) | Binding and account resolution that turns inbound traffic into specific agent and session lanes. |

## Channel, Plugin, and Capability Layer

| Source Area | Wiki Page | How To Read It |
| --- | --- | --- |
| `src/channels/` | [Channel System](../entities/channel-system.md) | Normalized channel contracts, metadata, gating, typing, reply behaviors, and run-state handling. |
| `src/channels/plugins/` and channel-oriented `extensions/` | [Channel Plugin Adapters](../entities/channel-plugin-adapters.md) | Plugin-backed integrations for Telegram, Slack, Discord, Signal, WhatsApp, and related channels. |
| `src/plugins/` and `src/plugin-sdk/` | [Plugin Platform](../entities/plugin-platform.md) | Manifest parsing, installation, activation, hooks, provider wiring, and capability delivery. |
| `extensions/` provider and tool packages | [Provider And Model System](../entities/provider-and-model-system.md) | Model-provider packages and capability-specific extensions that become live runtime behavior through plugin activation. |
| `src/agents/skills.ts`, `src/cli/skills-cli.ts`, and `skills/` | [Skills Platform](../entities/skills-platform.md) | Bundled, managed, and workspace skill discovery plus installation and prompt assembly. |

## Device, Media, and Client Surfaces

| Source Area | Wiki Page | How To Read It |
| --- | --- | --- |
| `src/canvas-host/` and control UI assets | [Canvas And Control UI](../entities/canvas-and-control-ui.md) | Visual interaction surfaces, A2UI serving, and control-plane presentation. |
| `src/node-host/` and `src/pairing/` | [Node Host And Device Pairing](../entities/node-host-and-device-pairing.md) | Remote device execution, pairing, and capability policy enforcement. |
| `src/media/`, `src/media-generation/`, `src/media-understanding/`, `src/realtime-transcription/`, `src/realtime-voice/`, and `src/tts/` | [Media And Voice Stack](../entities/media-and-voice-stack.md) | Speech, transcription, vision, generation, and realtime voice behaviors. |
| `apps/` | [Native Apps And Platform Clients](../entities/native-apps-and-platform-clients.md) | macOS, iOS, Android, and shared app code that connect to the same gateway-centric runtime. |
| `src/acp/` and `src/mcp/` | [MCP And ACP Bridges](../entities/mcp-and-acp-bridges.md) | Protocol adapters that expose or translate runtime behavior for external tools and editors. |

## Reading Strategy

1. Start with the source areas that own runtime control flow, persistent state, or policy decisions.
2. Read extension, plugin, protocol, or adapter directories only after the core runtime contract is clear.
3. Use client or UI packages to understand how the architecture is surfaced to users rather than where the architecture itself is defined.
4. When a behavior crosses package boundaries, jump from the mapped entity page into the relevant concept or synthesis page instead of staying directory-local.

## See Also

- [Architecture Overview](architecture-overview.md)
- [Glossary](glossary.md)
- [Plugin Platform](../entities/plugin-platform.md)
- [Gateway Control Plane](../entities/gateway-control-plane.md)
- [Gateway As Control Plane](../concepts/gateway-as-control-plane.md)
- [Inbound Message To Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md)
