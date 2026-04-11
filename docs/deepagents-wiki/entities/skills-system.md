# Skills System

## Overview

Skills are reusable prompt packages that extend the agent with specialized knowledge, workflows, and domain-specific instructions. Each skill is a directory containing a required `SKILL.md` file with YAML frontmatter and markdown content. Skills are discovered at startup from one or more configurable filesystem locations, parsed into metadata, and injected into the agent's system prompt using a **progressive disclosure** pattern: the agent sees only the skill's name and description at first, and reads the full `SKILL.md` content on demand when the skill applies to the current task.

Skills are invoked directly from the CLI via slash commands of the form `/skill:<name>` (e.g., `/skill:web-research`). Some built-in skills also have dedicated top-level aliases (`/remember`, `/skill-creator`). The CLI ships with two built-in skills and supports arbitrary user- and project-level skills layered on top.

---

## Key Concepts

### Skill File Format

Every skill lives in a directory whose name must match the skill's `name` frontmatter field. The only required file is `SKILL.md`. Optional supporting files (scripts, reference docs, assets) may live alongside it.

```
skill-name/
├── SKILL.md          # Required: YAML frontmatter + markdown instructions
├── scripts/          # Optional: executable helpers
├── references/       # Optional: detailed reference documentation
└── assets/           # Optional: templates and examples
```

The `SKILL.md` file must begin with a YAML frontmatter block delimited by `---`:

```markdown
---
name: web-research
description: "Structured approach to conducting thorough web research. Use when the user asks to research a topic."
license: MIT
compatibility: "Python 3.10+"
allowed-tools: WebSearch, Read
metadata:
  author: "Alice"
  version: "1.0"
---

# Web Research Skill

## When to Use
- User asks you to research a topic

## Process
1. Search for relevant sources
2. Synthesize findings
...
```

### Frontmatter Schema (`SkillMetadata`)

All fields are parsed by `_parse_skill_metadata()` in `skills.py`. The fields `name` and `description` are required; all others are optional.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `name` | `str` | Yes | 1–64 chars, lowercase alphanumeric and hyphens only, no leading/trailing/consecutive hyphens, must match the parent directory name |
| `description` | `str` | Yes | 1–1024 chars; describes what the skill does and when to use it |
| `license` | `str \| None` | No | License name or reference to a bundled license file |
| `compatibility` | `str \| None` | No | Max 500 chars; environment requirements, intended product, or required packages |
| `allowed-tools` | `str` | No | Space- or comma-delimited list of tool names the skill recommends |
| `metadata` | `dict[str, str]` | No | Arbitrary key-value pairs for additional metadata not defined by the spec |

If `name` violates naming constraints the skill is still loaded (for backwards compatibility) but a warning is logged. If either required field is missing, the skill is skipped entirely. Files larger than 10 MB are also skipped as a DoS guard (`MAX_SKILL_FILE_SIZE = 10 * 1024 * 1024`).

### Discovery Paths

Skills are loaded from an ordered list of **sources** — directories in a backend. The CLI wires up five standard locations (from the built-in `skill-creator` skill documentation), listed here from lowest to highest precedence:

| # | Path | Scope |
|---|---|---|
| 0 | `<package>/built_in_skills/` | Built-in (ships with the CLI) |
| 1 | `~/.deepagents/<agent>/skills/` | User (deepagents alias) |
| 2 | `~/.agents/skills/` | User (shared across agent tools) |
| 3 | `.deepagents/skills/` | Project (deepagents alias) |
| 4 | `.agents/skills/` | Project (shared across agent tools) |

`<agent>` defaults to `agent` and can be changed with the `-a`/`--agent` CLI flag. When two sources contain a skill with the same `name`, the higher-precedence (later-listed) source wins (last-one-wins merge).

### `SkillsMiddleware` Class

`SkillsMiddleware` is an `AgentMiddleware` subclass that loads skill metadata before each agent session and injects it into the system prompt before every model call.

Constructor:

```python
SkillsMiddleware(
    backend: BACKEND_TYPES,   # e.g. FilesystemBackend or StateBackend
    sources: list[str],       # Ordered list of source directory paths
)
```

The middleware stores loaded metadata in the `SkillsState.skills_metadata` private state field. The `PrivateStateAttr` annotation on that field prevents it from being propagated to parent agents in multi-agent graphs.

### How Skills Become Slash Commands

`command_registry.py` defines all static slash commands as `SlashCommand` dataclass instances in the `COMMANDS` tuple. Each command has a `bypass_tier` (`BypassTier` enum) that controls whether it can execute while the app is busy:

| Tier | Behavior |
|---|---|
| `ALWAYS` | Executes regardless of any busy state (e.g., `/quit`) |
| `CONNECTING` | Bypasses only during initial connection (e.g., `/version`) |
| `IMMEDIATE_UI` | Opens modal UI immediately; real work deferred (e.g., `/model`, `/theme`) |
| `SIDE_EFFECT_FREE` | Side effect fires immediately; chat output deferred (e.g., `/mcp`, `/trace`) |
| `QUEUED` | Waits in the queue when the app is busy (e.g., `/clear`, `/remember`) |

Dynamic skill commands are generated by `build_skill_commands()`: it turns each discovered skill into a `/skill:<name>` autocomplete entry `(name, description, hidden_keywords)`. Skills whose names appear in `_STATIC_SKILL_ALIASES` (`remember`, `skill-creator`) are excluded because they already have dedicated top-level commands.

Skill commands accept arguments: `/skill:web-research find quantum computing papers`. The `parse_skill_command()` function splits such a string into `(skill_name, args)`.

### Built-in Skills

The CLI ships two built-in skills in `libs/cli/deepagents_cli/built_in_skills/`:

**`remember`** — invoked as `/remember` or `/skill:remember`
Triggered when the user says "remember this", "save what we learned", "update memory", or "capture learnings". Reviews the current conversation and captures valuable knowledge into either persistent memory (`AGENTS.md`) or new reusable skills. Chooses between global scope (`~/.deepagents/agent/AGENTS.md`) and project scope (`.deepagents/AGENTS.md`) based on the nature of the knowledge. Encodes best practices prominently and prefers skills over flat memory entries for multi-step workflows.

**`skill-creator`** — invoked as `/skill-creator` or `/skill:skill-creator`
A guide for creating effective skills. Triggered when the user asks to create, build, scaffold, or understand a new skill. Explains the five discovery paths, the `SKILL.md` format, core design principles (conciseness, appropriate degrees of freedom, clear trigger descriptions in the `description` field), and how to encode best practices into reusable workflows.

---

## Architecture

### Discovery → Parsing → Registration → Invocation Flow

```
Startup
  └─ SkillsMiddleware.before_agent() / abefore_agent()
       ├─ Skip if skills_metadata already in state (checkpoint or prior turn)
       ├─ For each source path in self.sources (in order):
       │    └─ _list_skills(backend, source_path)  [or _alist_skills for async]
       │         ├─ backend.ls(source_path)           → enumerate subdirectories
       │         ├─ backend.download_files([...])     → fetch all SKILL.md content
       │         └─ _parse_skill_metadata(content)    → SkillMetadata or None
       └─ Merge results: later sources override earlier by name (last-one-wins)
            └─ Return SkillsStateUpdate(skills_metadata=[...])

Per Model Call
  └─ SkillsMiddleware.wrap_model_call() / awrap_model_call()
       └─ modify_request(request)
            ├─ Read skills_metadata from request.state
            ├─ _format_skills_locations()  → list of source paths with priority labels
            ├─ _format_skills_list()       → bullet list: name, description, allowed tools, path
            └─ append_to_system_message()  → inject SKILLS_SYSTEM_PROMPT block

Agent Runtime
  └─ Agent sees skill metadata in system prompt (progressive disclosure)
       └─ When a skill applies:
            ├─ Agent reads full SKILL.md via the absolute path shown in the listing
            └─ Agent follows skill instructions and uses any helper scripts with absolute paths
```

### System Prompt Injection

The `SKILLS_SYSTEM_PROMPT` template is appended to the existing system message on every model call. It contains three sections:

1. **Skills locations** — source paths formatted with priority labels (last source marked "higher priority").
2. **Available skills** — one bullet per skill showing `name`, `description`, optional license/compatibility annotation, optional `allowed_tools`, and the absolute backend path to read for full instructions.
3. **Progressive disclosure instructions** — tells the agent when and how to recognize applicable skills, read their full content, and use helper scripts with absolute paths.

When no skills are available, the listing section shows a placeholder message pointing to where skills can be created.

### State Schema

`SkillsState` extends `AgentState`:

```python
class SkillsState(AgentState):
    skills_metadata: NotRequired[Annotated[list[SkillMetadata], PrivateStateAttr]]
```

The `PrivateStateAttr` annotation keeps this field local to the current agent; it is not propagated to parent agents in subagent graphs. Skills are loaded exactly once per session: if `skills_metadata` is already present in state (from a prior turn or a deserialized checkpoint), `before_agent` returns `None` and skips the backend round-trip.

---

## Source Files

- `libs/deepagents/deepagents/middleware/skills.py` — `SkillsMiddleware`, `SkillMetadata`, `SkillsState`, all parsing and formatting logic
- `libs/cli/deepagents_cli/command_registry.py` — `SlashCommand`, `COMMANDS`, `BypassTier`, `build_skill_commands()`, `parse_skill_command()`
- `libs/cli/deepagents_cli/built_in_skills/remember/SKILL.md` — built-in remember skill definition
- `libs/cli/deepagents_cli/built_in_skills/skill-creator/SKILL.md` — built-in skill-creator skill definition

---

## See Also

- [Memory System](./memory-system.md) — `MemoryMiddleware` and persistent `AGENTS.md` memory, closely related to the `remember` skill
- [CLI Runtime](./cli-runtime.md) — how the CLI wires `SkillsMiddleware` into the agent and how slash commands are dispatched
- [Backend System](./backend-system.md) — `FilesystemBackend` and other backend types used by `SkillsMiddleware` for skill discovery
