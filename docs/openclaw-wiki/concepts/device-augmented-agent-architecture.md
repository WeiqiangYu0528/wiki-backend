# Device Augmented Agent Architecture

## Overview

OpenClaw extends the assistant into physical devices and platform UIs through nodes, pairing, canvas, native apps, camera/screen surfaces, voice flows, and local command execution.

This concept is a platform invariant. It explains why the gateway, routing, plugins, channels, and clients can evolve independently without collapsing into contradictory behavior. Device Augmented Agent Architecture is therefore best read as a mechanism with operational consequences, not merely a label for related features.

## Why It Exists

This concept exists because the OpenClaw codebase repeatedly needs a stable way to coordinate behavior across multiple entities without turning those entities into one monolith.

A concept page earns its place only when it explains a guarantee that several entities rely on. In OpenClaw, this pattern keeps implementation detail from leaking across subsystem boundaries while still letting the overall product behave as one runtime.

A concept page earns its place only when it explains a guarantee that several entities rely on. In OpenClaw, this pattern keeps implementation detail from leaking across subsystem boundaries while still letting the overall product behave as one runtime.

A concept page earns its place only when it explains a guarantee that several entities rely on. In OpenClaw, this pattern keeps implementation detail from leaking across subsystem boundaries while still letting the overall product behave as one runtime.

A concept page earns its place only when it explains a guarantee that several entities rely on. In OpenClaw, this pattern keeps implementation detail from leaking across subsystem boundaries while still letting the overall product behave as one runtime.

## Mechanism

A useful way to read this mechanism is as an ordered path through the participating subsystems:
1. Pair a device or node with the gateway.
2. Advertise available capabilities and commands.
3. Use canvas, media, or voice surfaces to gather or present interaction state.
4. Let the assistant invoke device commands or react to device-originated events.
5. Keep the gateway as the central coordinator of permissions and identity.

The steps above are the operational skeleton. The exact file names vary by subsystem, but the concept remains stable because each participating entity contributes one predictable part of the chain. That is why the same concept can show up in SDK code, CLI wiring, plugin activation, channel routing, or persistence without becoming ambiguous.

## Invariants and Operational Implications

The most important invariant is that the linked entities are allowed to change implementation detail without changing the high-level guarantee described here. When a change breaks that guarantee, the failure usually appears at subsystem boundaries first: a summary no longer compacts correctly, a session route stops being stable, a skill path is not loaded consistently, or a permission rule is evaluated in the wrong layer.

Operationally, this means debugging should follow the mechanism rather than a UI symptom. Start where the concept is introduced, then inspect the next boundary where data, policy, or control is handed off. The source evidence table below is organized to support exactly that style of investigation.

## Involved Entities

| Entity | Role In This Concept |
| --- | --- |
| [Local First Personal Assistant Architecture](local-first-personal-assistant-architecture.md) | OpenClaw as a user-owned assistant centered on a local gateway |
| [Auth and Approval Boundaries](auth-and-approval-boundaries.md) | Tokens, passwords, allowlists, approvals, and safety envelopes |
| [Node Host and Device Pairing](../entities/node-host-and-device-pairing.md) | Remote device execution, pairing, invocation, and capability policies |
| [Canvas Voice and Device Control Loop](../syntheses/canvas-voice-and-device-control-loop.md) | How canvas, voice, nodes, and native clients form one interaction loop |
| [Gateway As Control Plane](../concepts/gateway-as-control-plane.md) | Related page in this wiki. |
| [Inbound Message To Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md) | Related page in this wiki. |

## Source Evidence

| File | Why It Matters |
| --- | --- |
| `src/node-host/runner.ts` | Main node-host process and gateway event loop |
| `src/node-host/invoke.ts` | Invocation handling |
| `src/canvas-host/server.ts` | Canvas HTTP/WebSocket host implementation |
| `src/canvas-host/a2ui.ts` | A2UI request handling and live-reload injection |
| `src/media/` | Shared media handling utilities and payload flows |
| `src/media-generation/` | Generated media runtime support |

## See Also

- [Local First Personal Assistant Architecture](local-first-personal-assistant-architecture.md)
- [Auth and Approval Boundaries](auth-and-approval-boundaries.md)
- [Node Host and Device Pairing](../entities/node-host-and-device-pairing.md)
- [Canvas Voice and Device Control Loop](../syntheses/canvas-voice-and-device-control-loop.md)
- [Gateway As Control Plane](../concepts/gateway-as-control-plane.md)
- [Inbound Message To Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
