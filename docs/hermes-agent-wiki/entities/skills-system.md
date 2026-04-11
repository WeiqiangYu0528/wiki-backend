# Skills System

## Overview

Hermes uses skills as reusable instruction bundles. A skill is not a Python tool, and it is not just a markdown note. It is a directory-centered workflow package whose `SKILL.md` file tells the model how to handle a particular kind of task, while optional `references/`, `templates/`, `scripts/`, and `assets/` files provide supporting material.

The reason this subsystem exists is simple: Hermes wants a large library of procedural know-how without stuffing every workflow into the always-on system prompt. Skills solve that by keeping most procedural knowledge in a catalog that can be discovered and loaded only when relevant.

The cleanest mental model is to separate the catalog from the four exposure paths built on top of it:

1. **Prompt index**: Hermes shows the model a compact list of available skills in the system prompt.
2. **Slash command**: a shell turns installed skills into `/skill-name` commands.
3. **Direct tool access**: the model can call `skills_list`, `skill_view`, and `skill_manage`.
4. **Session preloading**: the CLI can load specific skills into the session prompt before the conversation starts.

Those four paths all use the same underlying catalog, but they do different things. The prompt index advertises skills. Slash commands activate a specific skill from user intent. Tool access lets the model discover or inspect skills on demand. Preloading makes selected skills active for the whole session from the start.

That distinction matters because the most common misunderstanding in this subsystem is to treat "visible in the catalog," "listed in the prompt," and "fully loaded into the session" as the same state. They are not.

## Key Interfaces and Configs

The first thing a reader should know is not a long file list but the runtime roles of the four exposure paths.

| Exposure path | What Hermes surfaces | When the full skill body loads | Main implementation owner |
| --- | --- | --- | --- |
| Prompt index | Category-organized skill names and short descriptions in the system prompt | Only if the model later calls `skill_view` | `agent/prompt_builder.py` |
| Slash command | `/skill-name` commands in CLI or messaging-style shells | When the user invokes that command | `agent/skill_commands.py` |
| Direct tool access | `skills_list`, `skill_view`, `skill_manage` tool calls | `skill_view` and `skill_manage` load or mutate the skill directly | `tools/skills_tool.py`, `tools/skill_manager_tool.py` |
| Session preloading | One or more explicitly requested skills appended to the session prompt | Immediately during CLI session setup | `agent/skill_commands.py`, `cli.py` |

Two runtime roots shape almost everything else:

| Path or config | Why it matters |
| --- | --- |
| `~/.hermes/skills/` | The main writable catalog. Bundled skills are seeded here, hub-installed skills land here, and agent-created skills are written here. |
| `skills.external_dirs` in `config.yaml` | Optional read-only extensions scanned after the local catalog. |
| `skills.disabled` / `skills.platform_disabled` | Global and per-platform visibility controls. |
| `metadata.hermes.*` frontmatter in `SKILL.md` | Conditional activation, tags, related skills, config declarations, and setup metadata that change runtime behavior. |

## Architecture

Hermes splits the skills subsystem into four responsibilities.

| Responsibility | Owns | Does not own |
| --- | --- | --- |
| Catalog management | Building the installed skill catalog, applying source order, platform filters, and disabled-skill config | Executing the workflows described by the skill |
| Exposure | Prompt indexing, slash-command registration, direct tool access, and CLI preloading | Tool execution semantics |
| Metadata interpretation | Readiness checks, required env vars, linked-file discovery, conditional visibility, and config injection | Deciding which tools exist in the session |
| Skill lifecycle | Bundled-skill sync, hub install/update/audit, agent-created edits, and security scanning | General memory storage or cross-session recall |

This architecture is why skills sit beside tools instead of inside them. Tools define capabilities Hermes can execute. Skills define reusable procedures for how the model should use those capabilities.

That also explains the relationship to memory and learning. Skills are a form of procedural knowledge, but they are not the same subsystem as `memory`, `session_search`, or external memory providers. Memory stores facts, preferences, or recalled context. Skills store reusable "how to do this" workflows in directory form. Hermes connects the two socially by encouraging the agent to save successful procedures as skills, but the storage and runtime paths remain separate.

## Runtime Behavior

### 1. Hermes builds one working catalog

The main working catalog is `~/.hermes/skills/`. Hermes treats that directory, not the repository, as the live skill store.

That choice matters because skills enter the catalog through more than one source:

| Skill source | How it enters the runtime catalog | Normal runtime location |
| --- | --- | --- |
| Bundled built-in skills | Seeded from the repo's `skills/` directory by `tools.skills_sync.sync_skills()` | `~/.hermes/skills/` |
| Official optional skills | Installed through the Skills Hub from the repo's `optional-skills/` catalog | `~/.hermes/skills/` |
| User-created or agent-created skills | Written directly through `skill_manage()` or manual edits | `~/.hermes/skills/` |
| Team or project skill directories | Added through `skills.external_dirs` and scanned read-only | Original external path |

`sync_skills()` keeps bundled skills conservative. It copies in new bundled skills, updates unchanged local copies, and skips user-modified copies instead of overwriting them. So the repo is a seed source, while `~/.hermes/skills/` is the mutable runtime catalog.

### 2. Source order is local first, then external

Hermes extends the local catalog with `skills.external_dirs` from `config.yaml`, but the precedence rule is stable:

- the local `~/.hermes/skills/` directory is scanned first
- external directories are scanned after it
- if the same skill name exists in both places, the local one wins

This rule shows up in `_find_all_skills()` in `tools/skills_tool.py`, in `scan_skill_commands()` in `agent/skill_commands.py`, and in `build_skills_system_prompt()` in `agent/prompt_builder.py`.

That consistency is important. A user can shadow a team-shared skill locally without fighting different precedence rules in different parts of the runtime.

### 3. Discovery is metadata-first

Hermes does not load full skill bodies just to build the catalog. Discovery is intentionally metadata-first.

At discovery time, Hermes usually needs only:

- the skill name
- a short description
- the category inferred from directory layout
- frontmatter fields relevant to filtering, such as platform support or conditional activation

This is the progressive-disclosure design in practical form. `skills_list()` returns cheap metadata. `skill_view()` loads the full `SKILL.md` only when the model or shell actually needs the instructions. Supporting files are then loaded one at a time through `skill_view(name, file_path=...)`.

The directory layout therefore changes runtime behavior directly:

| Layout piece | Runtime effect |
| --- | --- |
| `SKILL.md` | Main instructions and frontmatter metadata |
| `references/` | Additional docs the model can inspect after loading the skill |
| `templates/` | Output or file templates that can be loaded on demand |
| `scripts/` | Helper scripts that the skill may tell the model to inspect or run |
| `assets/` | Supplementary files surfaced as linked files |
| `DESCRIPTION.md` in category dirs | Category descriptions used by prompt indexing and category discovery |

### 4. The prompt index advertises the catalog

`agent.prompt_builder.build_skills_system_prompt()` creates a compact category-organized index for the system prompt. This is the first exposure path.

What the model sees here is not the full skill content. It sees enough information to notice that a skill exists and decide whether to call `skill_view(name)`.

Before Hermes includes a skill in that index, it applies filters from frontmatter and config:

- platform compatibility
- global or per-platform disabled-skill settings
- conditional activation rules from `metadata.hermes`

The conditional rules are read by `_skill_should_show(...)`:

- `fallback_for_toolsets` and `fallback_for_tools` hide a skill when the preferred tool or toolset is already available
- `requires_toolsets` and `requires_tools` hide a skill when needed tools are missing

This is where skills intersect with tool governance without becoming the same subsystem. Tool governance decides which tools exist. The skills system looks at that already-resolved availability and decides which skills should be shown.

### 5. Slash commands activate one named skill from user intent

`agent.skill_commands.scan_skill_commands()` builds the slash-command surface from the same catalog. This is the second exposure path.

At this stage Hermes is not merely advertising skills. It is creating a user-facing command mapping, such as `/dogfood` or `/github-pr-workflow`, based on installed skills. The command slug is normalized so users can type a clean command name even when the underlying directory layout is more complex.

When a user invokes one of those commands, `build_skill_invocation_message()` loads the skill via `skill_view()`, wraps it in an activation note, and appends any setup or config notes that came back from the loader.

So slash commands are not a different storage system. They are a shell-facing activation path over the same catalog and loader.

### 6. Direct tool access lets the model inspect or modify skills itself

The third exposure path is the skills toolset itself:

- `skills_list` for metadata discovery
- `skill_view` for loading a skill or a linked file
- `skill_manage` for creating, patching, editing, and deleting skills

This path matters because it is the most explicit one. The model can decide for itself that a listed skill looks relevant, load it, inspect supporting files, and then later patch or save a skill if the workflow needed improvement.

That makes the skills subsystem self-reinforcing: the same model that consumes skills can also help maintain them.

### 7. Session preloading makes selected skills active from the start

The fourth exposure path is CLI preloading. When a user launches Hermes with `--skills`, `build_preloaded_skills_prompt()` resolves those identifiers immediately and appends the full skill content to the session prompt before conversation begins.

This is a different state from prompt indexing:

- a prompt-indexed skill is merely available to load
- a preloaded skill is already active session guidance

That is why preloading should be thought of as "forced activation at session start," not just another listing path.

### 8. Loading a skill is where setup and runtime side effects happen

`skill_view()` is the point where a skill stops being catalog metadata and starts affecting runtime behavior.

When Hermes loads a skill, it can:

- reject a skill that does not match the current OS platform
- refuse a user-disabled skill
- discover linked files and advertise them for follow-up loading
- surface setup-needed state for missing environment variables or credential files
- register available env vars for passthrough into `terminal` and `execute_code`
- expose tags, related skills, and setup hints

This is why "discoverable" and "ready to use" are different states. A skill may still appear in the catalog and prompt index even if it needs setup before it can fully function.

The setup behavior also changes by surface. On local interactive surfaces, Hermes can prompt securely when a required env var is missing. On messaging-style surfaces, it returns setup guidance instead of collecting secrets in-band.

### 9. One concrete example: from catalog to runtime effect

A representative example makes the mechanism clearer than another rule list.

Suppose a user has an installed skill at `~/.hermes/skills/fun/gif-search/SKILL.md`. Its frontmatter declares a description, a category, and a required environment variable such as `TENOR_API_KEY`.

The runtime flow looks like this:

1. Hermes starts and treats `~/.hermes/skills/` as the live catalog.
2. The prompt builder includes `gif-search` in the compact skill index if it is not disabled and passes platform or conditional filters.
3. The shell also exposes `/gif-search` because `scan_skill_commands()` found the same skill during command discovery.
4. The user types `/gif-search funny cats`.
5. `build_skill_invocation_message()` calls `skill_view("fun/gif-search")` under the hood.
6. `skill_view()` reads the full `SKILL.md`, sees that `TENOR_API_KEY` is required, and checks whether it is already configured.
7. If the value is missing and the session is local-interactive, Hermes can prompt for it securely. If the session is a messaging surface, the skill still loads but returns setup guidance instead of collecting the secret in chat.
8. Once the env var exists, `skill_view()` registers it for passthrough so later sandboxed terminal or code-execution work can see it.
9. The loaded skill instructions now shape the model's behavior for this request: how to search, which tools to prefer, which files or templates to inspect, and what output format to produce.

That is the whole subsystem in miniature. The catalog made the skill visible. The slash command or prompt index made it discoverable. `skill_view()` loaded it and resolved setup. Only then did the skill begin to change runtime behavior.

### 10. `skill_manage()` connects the subsystem to learning

`tools/skill_manager_tool.py` lets the agent create, patch, edit, and delete skills under `~/.hermes/skills/`, plus manage supporting files. It validates names and frontmatter, constrains writable paths, uses atomic writes, and runs the same security scanner used for external skill installs.

This is how Hermes turns successful procedures into reusable assets. The prompt layer reinforces the pattern by telling the agent to save hard-won workflows as skills and to patch a skill when the current run reveals missing steps or wrong commands.

That is where the subsystem meets learning, but it still does not collapse into memory. The agent may remember that a workflow worked. `skill_manage()` is what turns that lesson into a reusable procedural artifact.

## Source Files

The important source anchors fall into four groups:

| Group | Files | Why they matter |
| --- | --- | --- |
| Catalog and metadata | `tools/skills_tool.py`, `agent/skill_utils.py` | Show how skills are discovered, filtered, loaded, and given readiness or linked-file behavior. |
| Exposure paths | `agent/prompt_builder.py`, `agent/skill_commands.py`, `cli.py` | Show the four stable exposure paths: prompt index, slash commands, direct tool access, and CLI preloading. |
| Lifecycle and trust | `tools/skills_sync.py`, `tools/skill_manager_tool.py`, `tools/skills_guard.py`, `hermes_cli/skills_hub.py` | Show how skills arrive, evolve, and are scanned safely. |
| User-facing contract | `website/docs/user-guide/features/skills.md` | Mirrors the intended runtime model from a user perspective and helps confirm the implementation story. |

Taken together, these files reinforce the main mental model of the page: Hermes keeps one skill catalog, then exposes it in four different ways depending on whether the runtime is advertising, activating, loading, or mutating a skill.

## See Also

- [Tool Registry and Dispatch](tool-registry-and-dispatch.md)
- [Config and Profile System](config-and-profile-system.md)
- [Memory and Learning Loop](memory-and-learning-loop.md)
- [Plugin and Memory Provider System](plugin-and-memory-provider-system.md)
- [Toolset-Based Capability Governance](../concepts/toolset-based-capability-governance.md)
- [Self-Improving Agent Architecture](../concepts/self-improving-agent-architecture.md)
