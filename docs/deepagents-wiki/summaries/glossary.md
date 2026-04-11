# Glossary

## Overview

This glossary collects the terms that recur across the Deep Agents wiki. The entries are intentionally architectural rather than product-marketing oriented: each term is phrased so it helps a reader interpret runtime behavior, page boundaries, and source-file names.

Several of these terms overlap in everyday speech, but in the wiki they have narrower meanings. Use the definitions below together with the linked entity, concept, and synthesis pages when a source file uses one of these words as part of a protocol, configuration, or lifecycle decision.

## Terms

| Term | Definition |
| --- | --- |
| Deep agent | An agent bundle that includes planning, filesystem access, summarization, and delegation as defaults rather than optional add-ons. |
| Graph factory | The `create_deep_agent` assembly layer in `libs/deepagents/deepagents/graph.py` that compiles the default LangGraph runtime. |
| Backend | A storage and execution abstraction that hides whether state and commands are handled in-memory, on disk, or in a remote sandbox. |
| State backend | The default backend implementation that keeps agent-visible state in structured in-process storage. |
| Filesystem backend | A backend that exposes file-oriented state and turns file mutations into part of the agent runtime contract. |
| Composite backend | A backend router that lets one agent compose multiple backend implementations behind a single interface. |
| Subagent | A delegated agent specification that can run inline or asynchronously and is usually exposed via the task tool. |
| Async subagent | A delegated agent that can outlive the immediate turn and run in a remote or background execution environment. |
| Skill | A filesystem-discovered `SKILL.md` package that adds prompt instructions and sometimes scripts or references. |
| Memory file | An `AGENTS.md` file whose contents are formatted into persistent instructions for the agent. |
| Interrupt-on policy | The approval configuration that forces human review before sensitive shell or tool behavior proceeds. |
| Textual UI | The terminal application layer that renders messages, approvals, status, and thread history in the CLI. |
| ACP | Agent Client Protocol, used here to expose a Deep Agents runtime to editor-hosted clients. |
| MCP | Model Context Protocol, used by the CLI to load external tool servers into the agent runtime. |
| Harbor | The evaluation harness layer inside `libs/evals` that wraps Deep Agents runs and aggregates benchmark metadata. |
| Partner backend | A provider-specific package that adapts Deep Agents to remote execution environments such as Daytona or Modal. |
| Offload | Moving long-form context or intermediate state out of the active prompt so the graph can stay inside model limits. |
| Batteries included | The design choice that Deep Agents should ship with a strong default architecture instead of exposing only primitives. |

## How To Use This Glossary

1. When a term appears in a summary page, use the glossary to recover the repo-specific meaning before reading raw code.
2. If a term names a runtime boundary such as a session, backend, plugin, or route, jump next to the corresponding entity page.
3. If a term describes a recurring mechanism such as compaction, approval gating, or filesystem configuration, jump next to the corresponding concept or synthesis page.

## See Also

- [Architecture Overview](architecture-overview.md)
- [Graph Factory](../entities/graph-factory.md)
- [Skills System](../entities/skills-system.md)
- [Human in the Loop Approval](../concepts/human-in-the-loop-approval.md)
- [Batteries Included Agent Architecture](../concepts/batteries-included-agent-architecture.md)
- [Sdk To Cli Composition](../syntheses/sdk-to-cli-composition.md)
- [Codebase Map](codebase-map.md)
