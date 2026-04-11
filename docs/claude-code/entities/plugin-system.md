# Plugin System

## Overview

The plugin architecture extends Claude Code with additional capabilities. Two plugin types exist: built-in (shipped with the CLI) and marketplace (loaded from the filesystem). Plugins can provide skills, hooks, MCP servers, LSP servers, agents, commands, and output styles.

Built-in plugins differ from bundled skills (`src/skills/bundled/`) in that they appear in the `/plugin` UI under a "Built-in" section, users can enable/disable them (persisted to user settings), and they can provide multiple components (skills, hooks, MCP servers). Marketplace plugins are installed from git repositories via a marketplace registry and managed through the `PluginInstallationManager`.

## Key Types

### BuiltinPluginDefinition

Defined in `types/plugin.ts`, describes a plugin that ships with the CLI:

```typescript
type BuiltinPluginDefinition = {
  name: string
  description: string
  version?: string
  skills?: BundledSkillDefinition[]
  hooks?: HooksSettings
  mcpServers?: Record<string, McpServerConfig>
  isAvailable?: () => boolean
  defaultEnabled?: boolean
}
```

`isAvailable()` gates whether the plugin is shown at all (e.g., based on system capabilities). `defaultEnabled` controls the initial state before the user sets a preference (defaults to `true`).

### LoadedPlugin

The runtime representation of any plugin (built-in or marketplace) after loading:

```typescript
type LoadedPlugin = {
  name: string
  manifest: PluginManifest
  path: string
  source: string
  repository: string
  enabled?: boolean
  isBuiltin?: boolean
  sha?: string
  commandsPath?: string
  commandsPaths?: string[]
  commandsMetadata?: Record<string, CommandMetadata>
  agentsPath?: string
  agentsPaths?: string[]
  skillsPath?: string
  skillsPaths?: string[]
  outputStylesPath?: string
  outputStylesPaths?: string[]
  hooksConfig?: HooksSettings
  mcpServers?: Record<string, McpServerConfig>
  lspServers?: Record<string, LspServerConfig>
  settings?: Record<string, unknown>
}
```

For built-in plugins, `path` is set to the sentinel string `'builtin'` and `isBuiltin` is `true`.

### PluginError

A discriminated union of error types for type-safe error handling. Currently 20+ variants including:

- `generic-error` -- catch-all with an error string
- `plugin-not-found` -- plugin missing from marketplace
- `path-not-found`, `git-auth-failed`, `git-timeout`, `network-error` -- installation failures
- `manifest-parse-error`, `manifest-validation-error` -- invalid plugin manifests
- `marketplace-not-found`, `marketplace-load-failed`, `marketplace-blocked-by-policy` -- marketplace issues
- `mcp-config-invalid`, `mcp-server-suppressed-duplicate` -- MCP configuration problems
- `lsp-config-invalid`, `lsp-server-start-failed`, `lsp-server-crashed`, `lsp-request-timeout`, `lsp-request-failed` -- LSP server errors
- `hook-load-failed`, `component-load-failed` -- component loading failures
- `mcpb-download-failed`, `mcpb-extract-failed`, `mcpb-invalid-manifest` -- MCPB bundle errors
- `dependency-unsatisfied`, `plugin-cache-miss` -- dependency and cache errors

The helper `getPluginErrorMessage(error)` converts any variant to a human-readable string.

### PluginLoadResult

```typescript
type PluginLoadResult = {
  enabled: LoadedPlugin[]
  disabled: LoadedPlugin[]
  errors: PluginError[]
}
```

### Plugin ID Format

- Built-in: `{name}@builtin`
- Marketplace: `{name}@{marketplace}`

The function `isBuiltinPluginId(pluginId)` checks whether an ID ends with `@builtin`.

## Plugin Types

### 1. Built-in Plugins

Shipped with the CLI and toggled by users. Registered via `registerBuiltinPlugin()` during `initBuiltinPlugins()` at startup. Built-in plugins are stored in a module-level `Map<string, BuiltinPluginDefinition>`. The `getBuiltinPlugins()` function returns them split into enabled/disabled lists based on user settings (with `defaultEnabled` as fallback). Plugins whose `isAvailable()` returns `false` are omitted entirely.

Skills from built-in plugins are converted to `Command` objects via `getBuiltinPluginSkillCommands()`. These commands use `source: 'bundled'` (not `'builtin'`) so they integrate with the Skill tool's listing, analytics, and prompt-truncation exemption logic.

### 2. Marketplace Plugins

Loaded from the filesystem after being installed from git repositories. Managed through:

- `PluginInstallationManager` -- handles background installation of plugins and marketplaces from trusted sources without blocking startup. Tracks installation status (`pending`, `installing`, `installed`, `failed`) in app state.
- `pluginOperations.ts` -- core library functions for install, uninstall, enable, disable, and update operations. Returns result objects (no `process.exit()` or console writes).
- `pluginCliCommands.ts` -- thin CLI wrappers around core operations that handle console output and process exit.

## What Plugins Provide

Plugins can contribute any combination of the following components (tracked by the `PluginComponent` type):

| Component       | Type                                | Description                                         |
|-----------------|-------------------------------------|-----------------------------------------------------|
| **Commands**    | via `commandsPath`/`commandsPaths`  | Slash commands loaded from filesystem                |
| **Agents**      | via `agentsPath`/`agentsPaths`      | Agent definitions loaded from filesystem             |
| **Skills**      | `BundledSkillDefinition[]`          | Prompt packages (built-in) or via `skillsPath`       |
| **Hooks**       | `HooksSettings`                     | Lifecycle hooks injected into the session            |
| **MCP Servers** | `Record<string, McpServerConfig>`   | Model Context Protocol servers                       |
| **LSP Servers** | `Record<string, LspServerConfig>`   | Language Server Protocol servers                     |
| **Output Styles** | via `outputStylesPath`/`outputStylesPaths` | Custom output formatting                      |

## Plugin Lifecycle

1. **Registration** -- built-in plugins call `registerBuiltinPlugin()` during `initBuiltinPlugins()` at startup
2. **Availability check** -- `isAvailable()` is evaluated; unavailable plugins are hidden entirely
3. **Loading** -- `getBuiltinPlugins()` reads user settings to determine enabled/disabled state; marketplace plugins are loaded from disk via `loadInstalledPluginsFromDisk()` / `loadInstalledPluginsV2()`
4. **Merging** -- built-in and marketplace plugins are combined; duplicate MCP servers are detected and suppressed
5. **Component delivery** -- hooks are active during the session; skills become available as commands; MCP/LSP servers are initialized on demand
6. **Background installation** -- `PluginInstallationManager` reconciles declared marketplaces and installs missing plugins without blocking the session

## Source Files

| File | Purpose |
|------|---------|
| `src/plugins/builtinPlugins.ts` | Built-in plugin registry: register, query, enable/disable logic |
| `src/plugins/bundled/index.ts` | `initBuiltinPlugins()` entry point for registering built-in plugins at startup |
| `src/types/plugin.ts` | Core type definitions: `BuiltinPluginDefinition`, `LoadedPlugin`, `PluginError`, `PluginLoadResult` |
| `src/services/plugins/PluginInstallationManager.ts` | Background installation of plugins and marketplaces from trusted sources |
| `src/services/plugins/pluginOperations.ts` | Core operations: install, uninstall, enable, disable, update |
| `src/services/plugins/pluginCliCommands.ts` | CLI wrappers for plugin operations with console output |
| `src/utils/plugins/pluginLoader.ts` | Plugin loading from filesystem |
| `src/utils/plugins/marketplaceManager.ts` | Marketplace configuration and plugin lookup |
| `src/utils/plugins/reconciler.ts` | Marketplace diffing and reconciliation |
| `src/utils/plugins/installedPluginsManager.ts` | Installed plugin persistence on disk |
| `src/utils/plugins/pluginIdentifier.ts` | Plugin identifier parsing |
| `src/utils/plugins/dependencyResolver.ts` | Inter-plugin dependency resolution |
| `src/utils/plugins/cacheUtils.ts` | Plugin cache management |
| `src/utils/plugins/pluginDirectories.ts` | Plugin data directory management |

## See Also

- [Skill System](skill-system.md)
- [MCP System](mcp-system.md)
- [Agent System](agent-system.md)
- [Plugin Extension Model](../syntheses/plugin-extension-model.md)
