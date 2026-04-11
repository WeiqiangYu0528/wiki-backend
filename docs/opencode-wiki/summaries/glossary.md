# Glossary

## Overview

This glossary collects the terms that recur across the OpenCode wiki. The entries are intentionally architectural rather than product-marketing oriented: each term is phrased so it helps a reader interpret runtime behavior, page boundaries, and source-file names.

Several of these terms overlap in everyday speech, but in the wiki they have narrower meanings. Use the definitions below together with the linked entity, concept, and synthesis pages when a source file uses one of these words as part of a protocol, configuration, or lifecycle decision.

## Terms

| Term | Definition |
| --- | --- |
| Instance | A project-scoped runtime container that caches services and state for one working directory or worktree. |
| Workspace | A control-plane representation of a local or remote project that can be routed to and synchronized. |
| Control plane | The layer that tracks workspaces, forwarding, and remote interaction above the raw session runtime. |
| Session | The persistent conversational state for one agent interaction stream, including messages, summaries, permissions, and mode. |
| Compaction | The process of shrinking prior context into summaries or alternate prompt state so long conversations can continue. |
| Prompt variant | A text prompt file selected according to mode, provider family, or runtime condition. |
| Provider | A model vendor or integration surface normalized behind OpenCode's provider APIs. |
| Model routing | The process of turning user or config intent into a concrete provider and model binding. |
| Tool registry | The central registry that exposes built-in and plugin tools with schemas and prompt descriptions. |
| Plan mode | A structured agent mode that changes prompt selection and tool behavior for planning-oriented turns. |
| Build mode | A more execution-oriented session mode that expects tool-heavy implementation behavior. |
| Permission gate | The policy path that decides whether a tool call can run immediately, must ask, or is denied. |
| Plugin | An extension that can register hooks, tools, or runtime behavior inside OpenCode. |
| MCP | Model Context Protocol integration used to bring external tool servers into the runtime. |
| ACP | Agent Client Protocol integration used to expose the runtime to editor-hosted or protocol-facing clients. |
| Project bootstrap | The initialization path that prepares per-project state such as plugins, VCS context, snapshots, and watchers. |
| Sync event | A persisted event used to keep workspace state and client views coherent across product surfaces. |
| LSP | Language Server Protocol integration used for code-intelligence features and tool-assisted navigation. |

## How To Use This Glossary

1. When a term appears in a summary page, use the glossary to recover the repo-specific meaning before reading raw code.
2. If a term names a runtime boundary such as a session, backend, plugin, or route, jump next to the corresponding entity page.
3. If a term describes a recurring mechanism such as compaction, approval gating, or filesystem configuration, jump next to the corresponding concept or synthesis page.

## See Also

- [Architecture Overview](architecture-overview.md)
- [Session System](../entities/session-system.md)
- [Control Plane and Workspaces](../entities/control-plane-and-workspaces.md)
- [Tool and Agent Composition](../concepts/tool-and-agent-composition.md)
- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [Request To Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Codebase Map](codebase-map.md)
