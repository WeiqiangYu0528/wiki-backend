# Skill System

## Overview

Skills are reusable prompt packages that extend Claude Code's capabilities. They can execute **inline** (injecting content into the current conversation) or **fork** (spawning an isolated sub-agent via `runAgent()`). Skills come from four sources: bundled with the CLI, user-defined in `.claude/skills/`, plugin-provided, or remote (experimental).

The `SkillTool` is the single entry point through which the model invokes skills. Users can also invoke skills directly with slash commands (e.g., `/commit`, `/simplify`). Available skills are listed in system-reminder messages so the model can discover and match them to user requests.

## Key Types

### BundledSkillDefinition

Defined in `bundledSkills.ts`, this type describes skills that ship compiled into the CLI binary:

```typescript
type BundledSkillDefinition = {
  name: string
  description: string
  aliases?: string[]
  whenToUse?: string
  argumentHint?: string
  allowedTools?: string[]
  model?: string
  disableModelInvocation?: boolean
  userInvocable?: boolean
  isEnabled?: () => boolean
  hooks?: HooksSettings
  context?: 'inline' | 'fork'
  agent?: string
  files?: Record<string, string>   // Reference files extracted to disk on first invocation
  getPromptForCommand: (args: string, context: ToolUseContext) => Promise<ContentBlockParam[]>
}
```

When `files` is populated, reference files are lazily extracted to a deterministic directory under `getBundledSkillsRoot()` on first invocation. The skill prompt is prefixed with a `Base directory for this skill: <dir>` line so the model can `Read`/`Grep` those files on demand.

### Command (Skill representation at runtime)

Both bundled and file-based skills are normalized into the `Command` type (with `type: 'prompt'`). Key fields include `source` (bundled, user, plugin), `loadedFrom` (bundled, skills, plugin, managed, mcp), `context` (inline or fork), `allowedTools`, `model`, `effort`, `hooks`, `skillRoot`, and `getPromptForCommand()`.

### SkillTool Input/Output

```typescript
// Input
{ skill: string; args?: string }

// Output (union)
{ success: boolean; commandName: string; allowedTools?: string[]; model?: string; status: 'inline' }
  | { success: boolean; commandName: string; status: 'forked'; agentId: string; result: string }
```

## Skill Sources

### 1. Bundled Skills

Shipped with the CLI binary, registered at module initialization via `registerBundledSkill()`. Current bundled skills include: `batch`, `claude-api`, `debug`, `keybindings`, `loop`, `lorem-ipsum`, `remember`, `schedule-remote-agents`, `simplify`, `skillify`, `stuck`, `update-config`, and `verify`.

Bundled skills are stored in `skills/bundled/` and compiled into the binary. They always get full descriptions in the skill listing prompt (never truncated for budget).

### 2. Skill Directories (User/Project)

User-created skills loaded from markdown files. The loader (`loadSkillsDir.ts`) scans:

- **User skills**: `~/.claude/skills/<skill-name>/SKILL.md`
- **Project skills**: `.claude/skills/<skill-name>/SKILL.md`
- **Policy/managed skills**: `<managed-path>/.claude/skills/<skill-name>/SKILL.md`

Only the directory format (`skill-name/SKILL.md`) is supported in `/skills/` directories. Legacy `/commands/` directories also support single `.md` files. The skill name is derived from the directory name, with nested directories producing colon-separated namespaces (e.g., `review:frontend` from `review/frontend/SKILL.md`).

Deduplication uses `realpath()` to resolve symlinks, preventing the same physical file from appearing multiple times when accessed through overlapping parent directories.

### 3. Plugin Skills

Plugin-provided skills are namespaced as `pluginName:skillName`. They follow the same `Command` structure but have `source: 'plugin'` and carry `pluginInfo` metadata for telemetry. Official marketplace plugins are identified via `isOfficialMarketplaceName()` for trust-level decisions.

### 4. Remote/Canonical Skills (Experimental)

Ant-only experimental feature behind the `EXPERIMENTAL_SKILL_SEARCH` feature flag. Remote skills use `_canonical_<slug>` naming, are loaded from AKI/GCS with local caching, and auto-granted permissions since their content is curated. They bypass local command lookup entirely.

### 5. MCP Skills

MCP servers can expose skills (not just tools). The `mcpSkillBuilders.ts` module provides a write-once registry that breaks import cycles between MCP client code and `loadSkillsDir.ts`. MCP skills have `loadedFrom: 'mcp'` and are merged into the command list at runtime. Security note: MCP skills are remote and untrusted, so inline shell commands (`!...`) in their markdown body are never executed.

## Frontmatter Schema

Skills defined as markdown files use YAML frontmatter for configuration. Fields parsed by `parseSkillFrontmatterFields()`:

| Field | Type | Description |
|---|---|---|
| `name` | `string` | Display name (defaults to directory name) |
| `description` | `string` | Human-readable description; falls back to first paragraph of markdown body |
| `when_to_use` | `string` | Extended description shown in skill listings to help the model match skills |
| `model` | `string` | Model override (`"inherit"` means use caller's model) |
| `effort` | `string \| number` | Effort level override (valid: effort level names or integer) |
| `allowed-tools` | `string[]` | Tools the skill is allowed to use |
| `context` | `"fork" \| "inline"` | Execution context; `fork` spawns a sub-agent, default is inline |
| `agent` | `string` | Agent type for forked execution |
| `disable-model-invocation` | `boolean` | If true, the model cannot invoke this skill via SkillTool |
| `user-invocable` | `boolean` | If false, skill is hidden from user slash-command listings (default: true) |
| `argument-hint` | `string` | Hint text for argument completion |
| `arguments` | `string \| string[]` | Named argument placeholders for `${ARG}` substitution in skill body |
| `hooks` | `object` | Hook definitions (validated against `HooksSchema`) |
| `shell` | `object` | Shell configuration for inline `!command` execution in skill body |
| `paths` | `string \| string[]` | Glob patterns restricting when the skill is relevant (uses ignore-library format) |
| `version` | `string` | Skill version identifier |

## Execution Path

### 1. Discovery

Skills are listed in system-reminder messages. The listing budget is 1% of the context window (in characters, `SKILL_BUDGET_CONTEXT_PERCENT = 0.01`). When the total listing exceeds the budget, non-bundled skill descriptions are truncated progressively -- first to a proportional max length, then to names-only in extreme cases. Bundled skills always retain full descriptions.

### 2. Validation (`validateInput`)

- Normalizes the skill name (strips leading `/`)
- Checks remote canonical prefix (experimental)
- Looks up the command in `getAllCommands()` (local + MCP commands)
- Rejects if: not found, `disableModelInvocation` is set, or not a `prompt` type

### 3. Permission Check (`checkPermissions`)

Evaluated in order:

1. **Deny rules** -- if any deny rule matches (exact or prefix), execution is blocked
2. **Remote canonical skills** -- auto-granted (curated content)
3. **Allow rules** -- if any allow rule matches, execution is permitted
4. **Safe property allowlist** -- skills with only safe properties are auto-allowed (no user prompt)
5. **Default** -- ask user, offering suggestions for exact-match and prefix rules

Rule matching supports:
- **Exact match**: rule content equals the skill name (e.g., `commit`)
- **Prefix match**: rule ends with `:*` (e.g., `review:*` matches `review:frontend`)

### 4. Inline Execution (default)

1. `processPromptSlashCommand()` processes the skill with arguments
2. Skill body undergoes: argument substitution (`${ARG}`), `${CLAUDE_SKILL_DIR}` replacement, `${CLAUDE_SESSION_ID}` replacement, and inline shell execution (`!command`)
3. Resulting messages are tagged with `sourceToolUseID` and injected into the conversation
4. Allowed tools and model override are propagated via `contextModifier`

### 5. Fork Execution (`context: 'fork'`)

1. `prepareForkedCommandContext()` builds the system prompt and agent definition
2. `runAgent()` spawns an isolated sub-agent with its own token budget
3. Progress events (tool uses) are reported back to the parent via `onProgress`
4. Result text is extracted from agent messages via `extractResultText()`
5. Invoked skill state is cleaned up via `clearInvokedSkillsForAgent()`

## Permission Model

### Safe Skill Allowlist

The `SAFE_SKILL_PROPERTIES` set defines which `Command` properties are considered safe. If a skill has only properties in this set (or empty/undefined values for others), it is auto-allowed without user confirmation:

```
type, progressMessage, contentLength, argNames, model, effort, source,
pluginInfo, disableNonInteractive, skillRoot, context, agent,
getPromptForCommand, frontmatterKeys, name, description,
hasUserSpecifiedDescription, isEnabled, isHidden, aliases, isMcp,
argumentHint, whenToUse, paths, version, disableModelInvocation,
userInvocable, loadedFrom
```

Properties NOT in this set (e.g., `allowedTools`, `hooks`) trigger a permission prompt. This allowlist design means newly added properties default to requiring permission.

### Permission Rule Storage

Permission suggestions are offered as:
- Exact match: `Skill(commit)` -- allows this specific skill
- Prefix match: `Skill(commit:*)` -- allows skill and any sub-variants

Rules are stored in `localSettings` (`.claude/settings.json`).

## Skill Listing Budget

The prompt system manages skill listing size to avoid consuming excessive context:

- Budget: 1% of context window tokens, converted to characters (4 chars/token)
- Default fallback: 8,000 characters (1% of 200k context)
- Per-entry hard cap: 250 characters for description + whenToUse
- Truncation cascade: full descriptions -> proportionally trimmed -> names-only (extreme)
- Bundled skills are exempt from truncation

## Source Files

| File | Description |
|---|---|
| `skills/bundledSkills.ts` | `BundledSkillDefinition` type, `registerBundledSkill()`, bundled skill registry |
| `skills/loadSkillsDir.ts` | Skill directory loader, frontmatter parser, `createSkillCommand()`, legacy commands loader |
| `skills/mcpSkillBuilders.ts` | Write-once registry bridging MCP client code and skill creation functions |
| `skills/bundled/*.ts` | Individual bundled skill implementations (verify, simplify, commit, etc.) |
| `tools/SkillTool/SkillTool.ts` | `SkillTool` definition: validation, permission checking, inline/fork execution |
| `tools/SkillTool/prompt.ts` | Skill listing prompt generation, budget management, `formatCommandsWithinBudget()` |
| `tools/SkillTool/constants.ts` | `SKILL_TOOL_NAME = 'Skill'` |
| `tools/SkillTool/UI.tsx` | UI rendering for skill tool use, results, progress, errors |
| `utils/frontmatterParser.ts` | YAML frontmatter parsing and validation utilities |
| `utils/forkedAgent.ts` | `prepareForkedCommandContext()`, `extractResultText()` for fork execution |
| `tools/AgentTool/runAgent.ts` | `runAgent()` used by forked skill execution |

## See Also

- [Agent System](agent-system.md)
- [Tool System](tool-system.md)
- [Command System](command-system.md)
- [Agent-Tool-Skill Triad](../syntheses/agent-tool-skill-triad.md)
