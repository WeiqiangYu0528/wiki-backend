# Settings Hierarchy

## Overview

Claude Code resolves configuration through a layered settings hierarchy where multiple sources contribute settings that are deep-merged in a defined priority order. This allows enterprise administrators to enforce policy, users to set personal defaults, and projects to carry shared or local configuration -- all coexisting without conflict.

The hierarchy ensures that higher-priority sources override lower ones while still inheriting anything the lower source defined that the higher source did not. Array values are concatenated and deduplicated rather than replaced, preserving additive rules (e.g., permission allow-lists from multiple sources).

## Mechanism

### Source Priority (lowest to highest)

Settings are merged from lowest to highest priority. Later sources override earlier ones for scalar and object values:

| Priority | Source             | Identifier           | File / Origin                                                         |
|----------|--------------------|----------------------|-----------------------------------------------------------------------|
| 0        | Plugin settings    | (plugin base)        | Allowlisted keys from installed plugins                               |
| 1        | User settings      | `userSettings`       | `~/.claude/settings.json` (or `cowork_settings.json` in cowork mode)  |
| 2        | Project settings   | `projectSettings`    | `$PROJECT/.claude/settings.json` (shared, committed)                  |
| 3        | Local settings     | `localSettings`      | `$PROJECT/.claude/settings.local.json` (gitignored)                   |
| 4        | Flag settings      | `flagSettings`       | `--settings <path>` CLI flag + inline SDK settings                    |
| 5        | Policy settings    | `policySettings`     | Enterprise managed settings (see sub-hierarchy below)                 |

The constant `SETTING_SOURCES` in `constants.ts` defines this order. Policy and flag settings are always enabled; user, project, and local sources can be selectively disabled via the `--setting-sources` CLI flag.

### Policy Settings Sub-Hierarchy

Policy settings use a "first source wins" strategy rather than merging across sub-sources. The highest-priority sub-source that contains any content provides all policy settings:

1. **Remote managed settings** -- fetched from API, cached synchronously
2. **MDM / HKLM / plist** -- OS-level device management (macOS: `/Library/Managed Preferences/com.anthropic.claudecode`; Windows: `HKLM\SOFTWARE\Policies\ClaudeCode`)
3. **File-based managed settings** -- `managed-settings.json` plus `managed-settings.d/*.json` drop-in directory (systemd/sudoers convention; alphabetical merge order within drop-ins)
4. **HKCU registry** -- Windows user-writable registry key (`HKCU\SOFTWARE\Policies\ClaudeCode`), lowest priority, only used if nothing above exists

### Deep Merge Behavior

Merging uses `lodash.mergeWith` with a custom customizer (`settingsMergeCustomizer`):

- **Objects**: recursively deep-merged (keys from both sources survive).
- **Arrays**: concatenated and deduplicated via `uniq([...target, ...source])`. This means permission `allow` rules from user settings and project settings stack rather than one replacing the other.
- **Scalars**: higher-priority source wins outright.
- **Deletion**: setting a key to `undefined` in `updateSettingsForSource` deletes it from the merged result. Arrays supplied to update replace the entire array (caller computes final state).

### Caching

Settings are cached at two levels to avoid repeated filesystem I/O:

- **Per-file parse cache** -- `getCachedParsedFile` memoizes the parsed+validated result of each individual settings file.
- **Session settings cache** -- `getSessionSettingsCache` stores the fully merged result across all sources. Both caches are invalidated together by `resetSettingsCache()`, triggered by the file-change detector.

All cache reads return deep clones to prevent mutation leakage.

### Security Constraints

Certain settings are intentionally restricted by source to prevent malicious project configuration:

- `skipDangerousModePermissionPrompt` and `skipAutoPermissionPrompt` ignore `projectSettings` (only trusted from user, local, flag, or policy).
- `useAutoModeDuringPlan` only returns `false` if a trusted source (not project) explicitly sets it.
- `autoMode` classifier allow/deny rules exclude `projectSettings` to prevent RCE via injected rules.

## Involved Entities

- [Configuration System](../entities/configuration-system.md) -- primary owner of settings resolution
- [Permission System](../entities/permission-system.md) -- consumes merged `permissions.allow` / `permissions.deny` arrays
- [Plugin System](../entities/plugin-system.md) -- contributes plugin base settings at lowest priority

## Source Evidence

| File | Role |
|------|------|
| `utils/settings/constants.ts` | Defines `SETTING_SOURCES` order, `getEnabledSettingSources()`, source display names |
| `utils/settings/settings.ts` | `loadSettingsFromDisk()` merge loop, `settingsMergeCustomizer`, per-source resolution, policy sub-hierarchy |
| `utils/settings/types.ts` | `SettingsSchema` Zod definition, `PermissionsSchema`, `HooksSchema` |
| `utils/settings/mdm/settings.ts` | MDM read/parse/cache, `getMdmSettings()`, `getHkcuSettings()`, first-source-wins for MDM sub-sources |
| `utils/settings/settingsCache.ts` | Session cache and per-file parse cache management |
| `utils/settings/managedPath.ts` | Platform-specific managed-settings file and drop-in directory paths |
| `hooks/useSettings.ts` | React hook providing reactive `ReadonlySettings` from `AppState` |

## See Also

- [Hook System](./hook-system.md) -- hooks configuration is part of the settings schema
- [Permission System](../entities/permission-system.md) -- permission rules merge across settings sources
- [Plugin System](../entities/plugin-system.md) -- plugins inject base settings at lowest priority
- [Configuration System](../entities/configuration-system.md) -- broader configuration architecture
