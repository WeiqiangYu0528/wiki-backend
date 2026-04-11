# Configuration System

## Overview

Claude Code uses a layered configuration system where settings from multiple sources merge with defined priority. The system handles both structured settings (JSON) and memory files (CLAUDE.md markdown). Configuration drives tool availability, permission modes, model selection, and feature flags.

## Key Types

### SettingsJson

The validated shape of a settings file, defined by `SettingsSchema` in `utils/settings/types.ts`. Key fields include:

- `permissions` -- allow / deny / ask rule lists, `defaultMode`, `additionalDirectories`, `disableBypassPermissionsMode`
- `hooks` -- lifecycle hooks (pre/post tool use, notification, etc.)
- `env` -- environment variable overrides (`Record<string, string>`)
- `agent` -- agent/model configuration
- `skipDangerousModePermissionPrompt`, `skipAutoPermissionPrompt` -- UI bypass flags

All settings files are validated against the Zod `SettingsSchema` on load; invalid files surface `ValidationError` objects but do not crash the process.

### SettingSource

A union of the five canonical sources, defined in `utils/settings/constants.ts`:

```typescript
const SETTING_SOURCES = [
  'userSettings',
  'projectSettings',
  'localSettings',
  'flagSettings',
  'policySettings',
] as const
```

`policySettings` and `flagSettings` are read-only; the three editable sources are `userSettings`, `projectSettings`, and `localSettings`.

### MemoryType

Discriminates CLAUDE.md entries by origin: `managed`, `user`, `project`, `local`. Used throughout the memory loading pipeline in `utils/claudemd.ts`.

## Settings Hierarchy (lowest to highest priority)

Settings are deep-merged in order using `lodash.mergeWith` with a custom array-replacing customizer (arrays are replaced, not concatenated). Plugin settings form the lowest base; each subsequent source overrides earlier values.

| Priority | Source | File path | Notes |
|----------|--------|-----------|-------|
| 0 (lowest) | Plugin settings | (in-memory from plugins) | Only allowlisted keys like `agent` |
| 1 | Policy settings | First non-empty wins: remote > MDM (HKLM/plist) > `managed-settings.json` + `managed-settings.d/*.json` > HKCU | systemd drop-in convention for file-based; alphabetical merge within drop-in dir |
| 2 | User settings | `~/.claude/settings.json` | Global personal preferences |
| 3 | Project settings | `.claude/settings.json` | Checked into VCS, shared with team |
| 4 | Local settings | `.claude/settings.local.json` | Gitignored, per-developer overrides |
| 5 (highest) | Flag settings | `--settings <path>` CLI flag + SDK inline settings | Merged together; inline overrides file |

The enabled source set is controlled by `--setting-sources` (accepts `user`, `project`, `local`). Policy and flag sources are always included regardless of this flag.

### Managed settings path by platform

| Platform | Base directory |
|----------|---------------|
| macOS | `/Library/Application Support/ClaudeCode` |
| Linux | `/etc/claude-code` |
| Windows | `C:\Program Files\ClaudeCode` |

Within the base directory: `managed-settings.json` is the base file, and `managed-settings.d/*.json` files are drop-ins merged alphabetically on top.

### Policy settings cascade

Policy settings use a "first source wins" strategy rather than merging across sub-sources:

1. **Remote** -- synced from claude.ai via `getRemoteManagedSettingsSyncFromCache()`
2. **MDM** -- HKLM (Windows) or macOS configuration profile (plist)
3. **File-based** -- `managed-settings.json` + `managed-settings.d/` drop-ins
4. **HKCU** -- Windows current-user registry (lowest, user-writable)

Only the first sub-source that produces non-empty settings is used.

## CLAUDE.md Memory Files

Memory files are loaded by `utils/claudemd.ts` and injected into the system prompt. They follow a separate priority chain from JSON settings.

### Load order (lowest to highest priority)

| Priority | Type | Paths |
|----------|------|-------|
| 1 (lowest) | Managed | `<managed-path>/CLAUDE.md` |
| 2 | User | `~/.claude/CLAUDE.md` |
| 3 | Project | `./CLAUDE.md`, `./.claude/CLAUDE.md`, `./.claude/rules/*.md` (all `.md` files in rules dir) |
| 4 (highest) | Local | `./CLAUDE.local.md` |

For project and local files, the loader traverses from the current working directory upward to the filesystem root. Files closer to the current directory have higher priority (loaded later in the prompt). The model pays more attention to later entries.

### @include directive

Memory files can reference other files using `@` notation:

- `@path` or `@./relative/path` -- relative to the including file
- `@~/home/path` -- relative to user home
- `@/absolute/path` -- absolute path

Constraints:
- Only works in leaf text nodes (not inside code blocks or inline code)
- Included files are inserted as separate entries before the including file
- Circular references are prevented by tracking already-processed file paths
- Non-existent files are silently ignored
- Only text file extensions are allowed (a large allowlist of `.md`, `.txt`, `.json`, `.ts`, `.py`, `.go`, `.rs`, etc.); binary files like images and PDFs are excluded
- Maximum recommended memory file size: 40,000 characters (`MAX_MEMORY_CHARACTER_COUNT`)

### Frontmatter support

Memory files support YAML frontmatter, parsed by `utils/frontmatterParser.ts`. Frontmatter can contain path-scoping metadata via `splitPathInFrontmatter()`, allowing rules to apply only to specific subdirectories.

## Configuration resolution flow

1. On startup, `loadSettingsFromDisk()` iterates over `getEnabledSettingSources()` in priority order
2. Each source is loaded via `getSettingsForSourceUncached()` -- file sources are parsed and Zod-validated; policy sources go through the cascade
3. Sources are deep-merged with `mergeWith` using a customizer that replaces arrays rather than concatenating them
4. The result is cached for the session in `settingsCache.ts`; changes require a restart (or explicit `resetSettingsCache()`)
5. `getInitialSettings()` returns the final merged `SettingsJson`
6. Memory files are loaded separately via `claudemd.ts` and assembled into the system prompt

## Source Files

| File | Description |
|------|-------------|
| `utils/settings/settings.ts` | Core settings loading, merging, per-source resolution, `getInitialSettings()`, `loadSettingsFromDisk()` |
| `utils/settings/types.ts` | `SettingsSchema` Zod schema, `SettingsJson` type, `PermissionsSchema`, `EnvironmentVariablesSchema` |
| `utils/settings/constants.ts` | `SETTING_SOURCES` array, source name helpers, `getEnabledSettingSources()`, `EditableSettingSource` |
| `utils/settings/managedPath.ts` | Platform-specific managed settings directory resolution |
| `utils/settings/settingsCache.ts` | Per-source and session-level caching for parsed settings |
| `utils/settings/validation.ts` | Zod error formatting, `filterInvalidPermissionRules()`, `SettingsWithErrors` |
| `utils/settings/mdm/settings.ts` | MDM (HKLM/plist) and HKCU registry-based settings reading |
| `utils/claudemd.ts` | CLAUDE.md discovery, loading, @include expansion, frontmatter parsing, memory prompt assembly |
| `utils/config.ts` | Global and project config management, `getCurrentProjectConfig()`, `getMemoryPath()` |
| `utils/configConstants.ts` | Standalone constants (`NOTIFICATION_CHANNELS`, `EDITOR_MODES`, `TEAMMATE_MODES`) |
| `utils/frontmatterParser.ts` | YAML frontmatter extraction and path-scoping logic |

## See Also

- [Memory System](memory-system.md)
- [Permission System](permission-system.md)
- [Settings Hierarchy](../concepts/settings-hierarchy.md)
- [Configuration Resolution Chain](../syntheses/configuration-resolution-chain.md)
