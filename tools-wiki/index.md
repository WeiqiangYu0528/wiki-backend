# Claude Code Tools — Wiki Index

This wiki documents the source code of the Claude Code tool system found at
`/Users/weiqiangyu/Downloads/wiki/docs/claude_code/src/tools`.

## Navigation

| Page | Type | Description |
|------|------|-------------|
| [schema.md](schema.md) | Schema | Wiki structure and conventions |
| [log.md](log.md) | Log | Analysis build log |
| [overview.md](overview.md) | Summary | High-level system overview |
| [entity_bashtool.md](entity_bashtool.md) | Entity | BashTool — shell command execution subsystem |
| [entity_agenttool.md](entity_agenttool.md) | Entity | AgentTool — sub-agent orchestration subsystem |
| [concept_permissions.md](concept_permissions.md) | Concept | The cross-cutting permission and security model |
| [synthesis_composition.md](synthesis_composition.md) | Synthesis | Tool composition and the agent-tool feedback loop |

## System at a Glance

The `tools/` directory implements ~40 individual tools that Claude Code can invoke during a session. Each tool is built using a shared `buildTool()` factory and exposes a standard interface for:

- Input/output schema validation (via Zod)
- Permission checking
- Rendering in the terminal UI
- Progress reporting

The two architecturally dominant subsystems are:

1. **[BashTool](entity_bashtool.md)** — Executes shell commands with a layered security model.
2. **[AgentTool](entity_agenttool.md)** — Spawns sub-agents (local, remote, background) to run tasks in parallel.

The **[Permission System](concept_permissions.md)** underpins every tool and decides whether a given action is allowed, needs user confirmation, or is blocked.

The **[Synthesis](synthesis_composition.md)** page explains how these parts combine to create Claude Code's recursive, self-orchestrating capability.

---

See [schema.md](schema.md) for page conventions. See [log.md](log.md) for analysis decisions.
