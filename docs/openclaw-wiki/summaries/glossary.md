# Glossary

## Overview

This glossary collects the terms that recur across the OpenClaw wiki. The entries are intentionally architectural rather than product-marketing oriented: each term is phrased so it helps a reader interpret runtime behavior, page boundaries, and source-file names.

Several of these terms overlap in everyday speech, but in the wiki they have narrower meanings. Use the definitions below together with the linked entity, concept, and synthesis pages when a source file uses one of these words as part of a protocol, configuration, or lifecycle decision.

## Terms

| Term | Definition |
| --- | --- |
| Gateway | The long-lived local server that coordinates config, auth, plugins, channels, sessions, apps, and protocol surfaces. |
| Control plane | The gateway-owned operational layer that manages policy, identity, runtime state, and connected clients. |
| Lane | An isolated execution path for one session or reply stream inside the broader assistant runtime. |
| Route | The resolved mapping from inbound channel and account context to a concrete agent and session target. |
| Binding | A persistent association among a channel context, account, peer, or thread and the route or session it should use. |
| Channel adapter | A plugin-backed integration that converts a network-specific surface into OpenClaw's normalized channel model. |
| Plugin | A runtime extension that can register channels, providers, hooks, setup flows, or tools. |
| Provider auth profile | A stored authentication choice or token configuration used for one model provider integration. |
| Node host | A paired device or remote execution host that can run commands or surface capabilities under gateway policy. |
| Canvas | A visual control or rendering surface that lets agents and users interact through richer UI primitives than chat alone. |
| Session key | The normalized identifier used to keep one conversation or interaction lane separate from others. |
| Send policy | Rules that determine how replies are dispatched, gated, or transformed for a given session and channel context. |
| Cron job | A scheduled unit of work that is executed through isolated agent turns rather than raw scripts. |
| Device auth | The authentication and authorization boundary for apps or paired devices connecting to the gateway. |
| ACP | Agent Client Protocol support that lets editor-like or protocol-oriented clients talk to OpenClaw. |
| MCP | Model Context Protocol support used for tool exposure and protocol bridging. |
| Skills platform | The bundle of bundled, managed, and workspace skills plus their installation and prompt integration flows. |
| Local-first | The architectural stance that the assistant should run under user control on local hardware even when cloud providers are involved. |

## How To Use This Glossary

1. When a term appears in a summary page, use the glossary to recover the repo-specific meaning before reading raw code.
2. If a term names a runtime boundary such as a session, backend, plugin, or route, jump next to the corresponding entity page.
3. If a term describes a recurring mechanism such as compaction, approval gating, or filesystem configuration, jump next to the corresponding concept or synthesis page.

## See Also

- [Architecture Overview](architecture-overview.md)
- [Gateway Control Plane](../entities/gateway-control-plane.md)
- [Plugin Platform](../entities/plugin-platform.md)
- [Multi Channel Session Routing](../concepts/multi-channel-session-routing.md)
- [Gateway As Control Plane](../concepts/gateway-as-control-plane.md)
- [Inbound Message To Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md)
- [Codebase Map](codebase-map.md)
