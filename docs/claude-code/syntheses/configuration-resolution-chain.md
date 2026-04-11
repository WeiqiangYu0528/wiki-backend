# Configuration Resolution Chain

## Overview

This synthesis describes the full configuration story in Claude Code: how settings from multiple JSON sources merge into a single effective configuration, how CLAUDE.md memory files are loaded from multiple scopes with `@include` directive resolution, and how the resulting configuration drives tool availability, permission modes, and model selection.

## Systems Involved

- [Configuration System](../entities/configuration-system.md) -- settings file paths and loading
- [Memory System](../entities/memory-system.md) -- CLAUDE.md file loading and memory prompts
- [Permission System](../entities/permission-system.md) -- permission rules from settings
- [Tool System](../entities/tool-system.md) -- tool deny lists and allowed tools from settings
- [State Management](../entities/state-management.md) -- `AppState.settings` and reactive updates
- [Settings Hierarchy](../concepts/settings-hierarchy.md) -- source ordering and override semantics
- [Permission Model](../concepts/permission-model.md) -- how settings-driven rules interact with runtime permissions

## Interaction Model

### Settings Sources and Merge Order

Settings are loaded from five sources, listed in increasing priority (later sources override earlier ones):

| Priority | Source | File Path | Scope |
|---|---|---|---|
| 1 (lowest) | `userSettings` | `~/.claude/settings.json` | Global, all projects |
| 2 | `projectSettings` | `<project>/.claude/settings.json` | Shared, committed to repo |
| 3 | `localSettings` | `<project>/.claude/settings.local.json` | Private, gitignored |
| 4 | `flagSettings` | `--settings <path>` CLI flag | Session-scoped |
| 5 (highest) | `policySettings` | Managed settings (see below) | Enterprise/admin |

**Policy settings** have the highest priority and use a first-source-wins resolution among four sub-sources:
1. **Remote managed settings** -- fetched from Anthropic API, cached locally
2. **MDM settings** -- macOS plist (`/Library/Preferences/`) or Windows HKLM registry
3. **File-based managed settings** -- `/etc/claude-code/managed-settings.json` plus drop-in files from `/etc/claude-code/managed-settings.d/*.json` (sorted alphabetically, later files win within this tier)
4. **HKCU settings** -- Windows current-user registry (lowest policy tier)

**`policySettings` and `flagSettings` are always enabled.** The other three sources can be selectively disabled via the `--setting-sources` CLI flag (e.g., `--setting-sources user,local` omits project settings).

### Settings Merge Semantics

Settings are merged using `lodash-es/mergeWith` with a custom `settingsMergeCustomizer`:
- Object properties are deep-merged recursively.
- Arrays are replaced wholesale (not concatenated).
- Setting a key to `undefined` in a higher-priority source deletes it from the merged result.
- Permission rules (arrays of `{ tool, allow/deny }`) from different sources are all collected and evaluated in priority order.

### Settings File Validation

Each settings file goes through:
1. **Symlink safety** -- `safeResolvePath()` resolves the path and verifies it is safe.
2. **JSON parsing** -- `safeParseJSON()` with error recovery.
3. **Permission rule filtering** -- `filterInvalidPermissionRules()` removes malformed rules before schema validation.
4. **Zod schema validation** -- `SettingsSchema().safeParse(data)` validates against the full settings type.
5. **Caching** -- parsed results are cached per file path, cloned on read to prevent mutation.

### The Merged Settings Object

`getInitialSettings()` merges all enabled sources into a single `SettingsJson` object that is stored as `AppState.settings`. This merged object drives:

- **Tool availability**: `allowedTools`, `disallowedTools` filter the tool pool
- **Permission mode**: `permissions` array defines per-tool allow/deny rules
- **Model selection**: `model` sets the default model, `smallModelMap` configures model routing
- **MCP servers**: `mcpServers` defines server connections
- **Hooks**: `hooks` configures lifecycle event handlers
- **Plugin state**: `enabledPlugins` controls which plugins are active
- **Memory**: `autoMemoryEnabled`, `autoMemoryDirectory` control memory features
- **Behavior flags**: `thinkingEnabled`, `verboseEnabled`, various feature toggles

### CLAUDE.md Memory File Resolution

Memory files (CLAUDE.md) are loaded separately from settings and injected into the system prompt. They follow a four-tier scoping model, loaded in order from lowest to highest priority:

**1. Managed memory** (`/etc/claude-code/CLAUDE.md`):
Global instructions for all users on the machine, set by administrators.

**2. User memory** (`~/.claude/CLAUDE.md`):
Private global instructions that apply to all projects for the current user.

**3. Project memory** (multiple locations per directory):
- `CLAUDE.md` in directory root
- `.claude/CLAUDE.md`
- `.claude/rules/*.md` -- all markdown files in the rules directory

Project memory is discovered by traversing from the current working directory up to the filesystem root. Files closer to the current directory have higher priority (loaded later in the prompt, which means the model pays more attention to them).

**4. Local memory** (`CLAUDE.local.md` in project roots):
Private project-specific instructions, intended to be gitignored.

Additionally, when auto-memory is enabled, the system loads `MEMORY.md` from the auto-memory directory (`~/.claude/projects/<sanitized-git-root>/memory/MEMORY.md`). This file is truncated at 200 lines or 25,000 bytes, whichever is hit first.

### The @include Directive

Memory files support an `@include` directive for composing instructions from multiple files:

**Syntax**:
- `@path` or `@./relative/path` -- relative to the including file's directory
- `@~/home/path` -- relative to the user's home directory
- `@/absolute/path` -- absolute path

**Resolution rules**:
- Only works in leaf text nodes (not inside code blocks or inline code spans)
- Included files are added as separate `MemoryFileInfo` entries *before* the including file in the prompt
- Circular references are prevented by tracking processed file paths
- Non-existent files are silently ignored
- Only text file extensions are allowed (a comprehensive allowlist of ~80 extensions) -- binary files are rejected
- The `instructions_loaded` hook fires for each included file, enabling external processing

**Frontmatter in memory files**:
Memory files support YAML frontmatter with a `paths` field containing glob patterns. When present, the file's instructions only apply when the current conversation involves files matching those patterns. The `paths` field uses picomatch glob syntax.

### Auto-Memory Path Resolution

The auto-memory directory path is resolved through a priority chain:

1. `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` env var -- full-path override for Cowork/SDK callers
2. `autoMemoryDirectory` in settings.json (trusted sources only: policy, local, user -- **not** project settings for security)
3. `<memoryBaseDir>/projects/<sanitized-git-root>/memory/` -- the default, where `memoryBaseDir` is `CLAUDE_CODE_REMOTE_MEMORY_DIR` or `~/.claude`

**Security**: Project settings are excluded from `autoMemoryDirectory` because a malicious repository could set it to `~/.ssh` and gain write access via the auto-memory write carve-out in the filesystem permission layer.

### How Configuration Drives Runtime Behavior

**Tool availability**:
```
settings.allowedTools + settings.disallowedTools
  -> assembleToolPool() applies deny rules
    -> useMergedTools() merges with MCP tools
      -> final tool list available to the model
```

**Permission mode**:
```
settings.permissions (per-source rules)
  -> merged into toolPermissionContext
    -> AppState.toolPermissionContext.mode: 'default' | 'plan' | 'bypassPermissions'
      -> drives PermissionRequest dialog behavior
```

**Model selection**:
```
--model CLI flag > AppState.mainLoopModelForSession > AppState.mainLoopModel > settings.model > default
```

### Settings Reactivity

Settings files are watched for changes via `useSettingsChange()`. When a file changes:

1. `applySettingsChange(source, setState)` is called.
2. The changed source is re-parsed and re-merged.
3. `AppState.settings` is updated.
4. All components consuming settings-derived state re-render.
5. The `onChangeAppState` callback can trigger side effects (e.g., persisting state).

The settings cache (`settingsCache.ts`) is invalidated on detected changes. File-level caching ensures that re-parsing is only done when the file content has actually changed.

## Key Interfaces

```typescript
// Setting sources (in priority order)
const SETTING_SOURCES = [
  'userSettings',      // ~/.claude/settings.json
  'projectSettings',   // .claude/settings.json
  'localSettings',     // .claude/settings.local.json
  'flagSettings',      // --settings <path>
  'policySettings',    // managed-settings.json or remote/MDM
] as const

type SettingSource = (typeof SETTING_SOURCES)[number]

// Core settings functions
function getSettingsForSource(source: SettingSource): SettingsJson | null
function getSettingsFilePathForSource(source: SettingSource): string | undefined
function getInitialSettings(): SettingsJson  // merged from all sources
function updateSettingsForSource(source: EditableSettingSource, settings: SettingsJson): { error: Error | null }

// Memory file types
type MemoryFileInfo = {
  path: string
  type: MemoryType           // 'managed' | 'user' | 'project' | 'local'
  content: string
  parent?: string            // path of including file
  globs?: string[]           // glob patterns for scoped rules
  contentDiffersFromDisk?: boolean
  rawContent?: string
}

// Memory loading
function getMemoryFiles(cache?: FileStateCache): MemoryFileInfo[]

// Auto-memory path resolution
function getAutoMemPath(): string           // memoized
function isAutoMemPath(absolutePath: string): boolean
function isAutoMemoryEnabled(): boolean

// Settings reactivity
function useSettingsChange(callback: (source: SettingSource) => void): void
function applySettingsChange(source: SettingSource, setState: SetAppState): void
```

## See Also

- [Configuration System](../entities/configuration-system.md) -- settings file paths and parsing
- [Memory System](../entities/memory-system.md) -- CLAUDE.md loading and auto-memory
- [Permission System](../entities/permission-system.md) -- permission rules from settings
- [Settings Hierarchy](../concepts/settings-hierarchy.md) -- detailed source ordering
- [Permission Model](../concepts/permission-model.md) -- how permission rules are evaluated
- [Tool Permission Gating](../concepts/tool-permission-gating.md) -- how settings filter tools
- [Plugin Extension Model](./plugin-extension-model.md) -- how plugins interact with settings
- [State-Driven Rendering](./state-driven-rendering.md) -- how settings changes trigger re-renders
