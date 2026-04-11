# Frontmatter Conventions

## Overview

Claude Code uses YAML frontmatter in markdown files to define agents and skills (slash commands). This frontmatter acts as a declarative configuration layer: it specifies metadata, tool restrictions, model selection, permission modes, hooks, and other behavioral parameters without requiring code changes. The same frontmatter format is shared across user settings, project settings, managed policy settings, and plugin-provided definitions, with a consistent parsing pipeline and validation rules.

## Mechanism

### Agent Frontmatter Fields

Agent definitions are parsed from markdown files in `.claude/agents/` directories (user, project, managed) by `loadAgentsDir.ts`. The following fields are recognized in YAML frontmatter:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | Yes | The agent type identifier. Used as the `subagent_type` parameter in Agent tool invocations. |
| `description` | `string` | Yes | When-to-use text that tells the model when to invoke this agent. Newlines escaped as `\n` in YAML are unescaped during parsing. |
| `tools` | `string[]` | No | Allowlist of tool names the agent can use. Parsed via `parseAgentToolsFromFrontmatter()`. When omitted, the agent inherits the parent's full tool pool. |
| `disallowedTools` | `string[]` | No | Denylist of tool names the agent cannot use. Applied after `tools` resolution. |
| `model` | `string` | No | Model to use. The special value `'inherit'` (case-insensitive) uses the parent's model. Any other string is treated as a model identifier. |
| `effort` | `string \| number` | No | Effort level. Accepts string levels (`'low'`, `'medium'`, `'high'` from `EFFORT_LEVELS`) or an integer. Parsed via `parseEffortValue()`. |
| `permissionMode` | `string` | No | One of `PERMISSION_MODES` (e.g., `'default'`, `'bypassPermissions'`, `'acceptEdits'`, `'auto'`, `'bubble'`). Overrides the parent's mode unless the parent is in `bypassPermissions`, `acceptEdits`, or `auto` mode. |
| `maxTurns` | `number` | No | Maximum agentic turns before the agent stops. Must be a positive integer. Parsed via `parsePositiveIntFromFrontmatter()`. |
| `color` | `string` | No | Display color for the agent in the UI. Must be one of `AGENT_COLORS`. |
| `mcpServers` | `array` | No | MCP servers specific to this agent. Each element is either a string (reference to existing server by name) or an object `{ name: McpServerConfig }` (inline definition). Validated via `AgentMcpServerSpecSchema`. |
| `hooks` | `object` | No | Session-scoped hooks registered when the agent starts. Validated via `HooksSchema`. |
| `skills` | `string[]` | No | Skill names to preload. Parsed from comma-separated frontmatter via `parseSlashCommandToolsFromFrontmatter()`. |
| `initialPrompt` | `string` | No | Text prepended to the first user turn. Slash commands within it are expanded. |
| `background` | `boolean` | No | When `true`, the agent always runs as a background task. Accepts `'true'`/`'false'` strings or boolean values. |
| `memory` | `string` | No | Persistent memory scope: `'user'`, `'project'`, or `'local'`. When enabled, `FileWrite`, `FileEdit`, and `FileRead` tools are auto-injected if not already in the tool list. |
| `isolation` | `string` | No | Isolation mode: `'worktree'` (all builds) or `'remote'` (ant-only). Runs the agent in a separate git worktree or remote CCR session. |

The markdown body (below the frontmatter `---` delimiters) becomes the agent's system prompt, accessed via `getSystemPrompt()`. When memory is enabled, the memory prompt is appended.

### Agent JSON Schema

Agents can also be defined via JSON (for flag/remote settings). The `AgentJsonSchema` validates the same fields with Zod:
- `description`: Non-empty string (required)
- `prompt`: Non-empty string (required, replaces the markdown body)
- `tools`, `disallowedTools`: Optional string arrays
- `model`: Optional string, trimmed, `'inherit'` normalized
- `effort`: Union of `EFFORT_LEVELS` enum and integer
- `permissionMode`: Enum of `PERMISSION_MODES`
- `mcpServers`: Array of `AgentMcpServerSpecSchema`
- `hooks`: `HooksSchema`
- `maxTurns`: Positive integer
- `skills`: String array
- `initialPrompt`: String
- `background`: Boolean
- `memory`: Enum of `'user' | 'project' | 'local'`
- `isolation`: Enum of `'worktree'` (or `'worktree' | 'remote'` for ant)

### Skill Frontmatter Fields

Skill definitions are parsed from markdown files in `.claude/skills/` (or legacy `.claude/commands/`) directories by `loadSkillsDir.ts`. Shared field parsing lives in `parseSkillFrontmatterFields()`:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `string` | Display name override. If omitted, the filename (without `.md`) is used. |
| `description` | `string` | Human-readable description. Falls back to extracting from the markdown body via `extractDescriptionFromMarkdown()`. |
| `allowed-tools` | `string[]` | Tools the skill is allowed to use during execution. |
| `argument-hint` | `string` | Hint text shown in autocomplete for the skill's argument. |
| `arguments` | `string \| string[]` | Named argument placeholders for substitution in the prompt body via `substituteArguments()`. |
| `when_to_use` | `string` | Trigger description for model-initiated invocation. |
| `version` | `string` | Skill version string. |
| `model` | `string` | Model override. `'inherit'` means use the current session model. Parsed via `parseUserSpecifiedModel()`. |
| `effort` | `string \| number` | Effort level, same parsing as agents. |
| `disable-model-invocation` | `boolean` | When true, the model cannot invoke this skill autonomously (user-only). |
| `user-invocable` | `boolean` | When false, the skill is hidden from the user and only model-invocable. Defaults to `true`. |
| `hooks` | `object` | Skill-scoped hooks. Validated via `HooksSchema`. |
| `context` | `string` | Execution context: `'fork'` runs the skill in a forked agent. |
| `agent` | `string` | Agent type to delegate execution to. |
| `paths` | `string \| string[]` | File path patterns (glob-style) scoping when this skill is relevant. Patterns ending in `/**` have the suffix stripped. Match-all patterns (`**`) are treated as no filter. |
| `shell` | `string \| object` | Shell configuration for the skill. Parsed via `parseShellFrontmatter()`. |

### Boolean Flag Parsing

Boolean frontmatter values are parsed via `parseBooleanFrontmatter()`:
- String values `'true'` and `'false'` are accepted
- Native boolean `true`/`false` values are accepted
- For the `background` field specifically, invalid values log a warning but do not fail parsing -- the field defaults to `undefined` (not background)

### Validation Rules

1. **Required fields**: Agents must have both `name` and `description`. Files missing `name` are silently skipped (assumed to be co-located reference documentation). Files with `name` but missing `description` are reported as parse errors.
2. **Invalid enum values**: Invalid `permissionMode`, `effort`, `memory`, `isolation`, or `color` values log debug warnings but do not prevent the agent from loading (the invalid field is simply omitted).
3. **MCP server specs**: Each element in the `mcpServers` array is individually validated via Zod. Invalid items are logged and filtered out; valid items are preserved.
4. **Hooks validation**: The `hooks` field is validated against `HooksSchema()` via `safeParse()`. Invalid hooks log a warning and are omitted.
5. **Source priority**: When the same agent type is defined at multiple levels, the override order is: built-in < plugin < userSettings < projectSettings < flagSettings < policySettings. The `getActiveAgentsFromList()` function resolves this by iterating groups in order, with later entries overwriting earlier ones in a Map keyed by `agentType`.
6. **Plugin-only restriction**: When `isRestrictedToPluginOnly('mcp')` is true, frontmatter MCP servers are skipped for user-controlled agents but allowed for admin-trusted sources.
7. **Memory tool injection**: When `memory` is set and `tools` is specified, `FileWrite`, `FileEdit`, and `FileRead` are auto-injected into the tool list if not already present.

### Skill Deduplication

Skills loaded from multiple directories are deduplicated by resolving symlinks via `realpath()` (`getFileIdentity()`). This prevents the same skill file accessed through different paths (e.g., symlinks or overlapping parent directories) from appearing twice.

## Involved Entities

- [loadAgentsDir.ts](../claude_code/src/tools/AgentTool/loadAgentsDir.ts) -- agent frontmatter parsing, JSON schema, source priority
- [loadSkillsDir.ts](../claude_code/src/skills/loadSkillsDir.ts) -- skill frontmatter parsing, deduplication, command creation
- [frontmatterParser.ts](../claude_code/src/utils/frontmatterParser.ts) -- low-level YAML frontmatter extraction and type coercion
- [markdownConfigLoader.ts](../claude_code/src/utils/markdownConfigLoader.ts) -- shared markdown file loading for both agents and skills
- [settings/types.ts](../claude_code/src/utils/settings/types.ts) -- `HooksSchema` definition
- [effort.ts](../claude_code/src/utils/effort.ts) -- `EFFORT_LEVELS` and `parseEffortValue()`
- [PermissionMode.ts](../claude_code/src/utils/permissions/PermissionMode.ts) -- `PERMISSION_MODES` constant

## Source Evidence

- `loadAgentsDir.ts:73-99` defines `AgentJsonSchema` with all validated fields including `isolation`, `memory`, `background`, `hooks`, `mcpServers`.
- `loadAgentsDir.ts:549-563` validates `name` (required, string) and `description` (required, string) as the minimum agent frontmatter.
- `loadAgentsDir.ts:577-591` parses `background` with explicit `'true'`/`'false'` string and boolean handling, logs warning for invalid values.
- `loadAgentsDir.ts:608-621` parses `isolation` with build-time gating: `['worktree', 'remote']` for ant, `['worktree']` for external.
- `loadAgentsDir.ts:196-221` `getActiveAgentsFromList()` implements source priority via ordered group iteration.
- `loadSkillsDir.ts:185-265` `parseSkillFrontmatterFields()` extracts all skill fields including `model`, `effort`, `shell`, `hooks`, `context`, `agent`.
- `loadSkillsDir.ts:217-219` `user-invocable` defaults to `true` when undefined.
- `loadSkillsDir.ts:159-178` `parseSkillPaths()` strips `/**` suffix and treats match-all patterns as no filter.

## See Also

- [Agent Isolation](./agent-isolation.md) -- how `isolation`, `mcpServers`, and `permissionMode` fields are applied at runtime
- [Session Lifecycle](./session-lifecycle.md) -- hooks and initialPrompt execute during session start
- [Compaction and Context Management](./compaction-and-context-management.md) -- skill content survives compaction
