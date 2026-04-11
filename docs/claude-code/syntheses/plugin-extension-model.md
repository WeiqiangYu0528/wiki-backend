# Plugin Extension Model

## Overview

This synthesis describes how plugins extend Claude Code's capabilities. A plugin is a bundle that can provide any combination of tools, commands (slash commands/skills), agents, hooks, and MCP servers. Plugins are loaded from marketplaces (Git repositories) or ship as built-in plugins. The system merges plugin-provided components into the active session through hooks like `useMergedTools`, `useMergedCommands`, and `useManagePlugins`, with error isolation ensuring one broken plugin does not take down the session.

## Systems Involved

- [Plugin System](../entities/plugin-system.md) -- loading, caching, marketplace management
- [Tool System](../entities/tool-system.md) -- built-in tool registry and tool pool assembly
- [Command System](../entities/command-system.md) -- slash commands and skill commands
- [Agent System](../entities/agent-system.md) -- agent definitions from plugin markdown files
- [MCP System](../entities/mcp-system.md) -- MCP server connections from plugin manifests
- [Hook System](../concepts/hook-system.md) -- lifecycle hooks from plugin configuration
- [State Management](../entities/state-management.md) -- `AppState.plugins` and `AppState.mcp`

## Interaction Model

### Plugin Identity and Sources

Plugins are identified by a composite ID: `{name}@{marketplace}`. Two special sources exist:

- **Built-in plugins** use `{name}@builtin` -- these ship with the CLI binary, appear in the `/plugin` UI, and can be enabled/disabled by the user. Their availability can be gated by `isAvailable()` (e.g., platform-specific features). Enabled state is persisted to user settings with `defaultEnabled` as the fallback.
- **Marketplace plugins** use `{name}@{marketplace-url}` -- these are cloned from Git repositories and cached locally. Version pinning uses Git commit SHAs.

### What a Plugin Provides

A `LoadedPlugin` carries paths to optional extension directories and metadata:

| Extension | Source | Merging Mechanism |
|---|---|---|
| **Commands** (slash commands) | `commandsPath`, `commandsPaths` | `getPluginCommands()` -> `AppState.plugins.commands` -> `useMergedCommands()` |
| **Skills** (prompt commands) | `skillsPath`, `skillsPaths` | Loaded as `Command` objects with `type: 'prompt'` |
| **Agents** | `agentsPath`, `agentsPaths` | `loadPluginAgents()` -> `AppState.agentDefinitions` |
| **Hooks** | `hooksConfig` on `LoadedPlugin` | `loadPluginHooks()` -> merged into session hook handlers |
| **MCP servers** | `mcpServers` on `LoadedPlugin` | `loadPluginMcpServers()` -> `AppState.mcp.clients` |
| **LSP servers** | Via plugin manifest | `loadPluginLspServers()` -> language server integration |

### Loading Lifecycle

The plugin loading lifecycle has three layers:

**Layer 1 -- Discovery and Caching** (`loadAllPlugins()`):
1. Read enabled marketplaces from merged settings (`enabledPlugins`, `extraKnownMarketplaces`).
2. For each marketplace, clone or update the Git repository to the local cache.
3. Parse each plugin's `manifest.json` (validated against `PluginManifest` schema).
4. Resolve extension paths (`commands/`, `agents/`, `skills/` directories).
5. Split into `enabled` and `disabled` lists based on user settings.
6. Return `{ enabled, disabled, errors }`.

**Layer 2 -- Built-in Injection** (`getBuiltinPlugins()`):
1. Walk the `BUILTIN_PLUGINS` registry (populated by `registerBuiltinPlugin()` at startup).
2. Filter by `isAvailable()`.
3. Check user preference -> `defaultEnabled` -> `true` for each plugin.
4. Convert skills to `Command` objects via `skillDefinitionToCommand()`.

**Layer 3 -- Component Loading** (`useManagePlugins` hook on mount):
1. Call `loadAllPlugins()` (Layer 1).
2. Run `detectAndUninstallDelistedPlugins()` -- remove plugins flagged on the blocklist.
3. Surface flagged-plugin notifications.
4. Load each component type with individual error handling:
   - `getPluginCommands()` -- parse markdown files in commands directories
   - `loadPluginAgents()` -- parse markdown files in agents directories with frontmatter
   - `loadPluginHooks()` -- register hook handlers from plugin hook configuration
   - `loadPluginMcpServers()` -- start MCP server connections
   - `loadPluginLspServers()` -- start LSP server connections
5. Populate `AppState.plugins` with `{ enabled, disabled, commands, errors }`.

**Refresh** (`/reload-plugins`):
When `AppState.plugins.needsRefresh` is set (by background reconciliation, `/plugin` menu install, or external settings edit), the user runs `/reload-plugins` to trigger `refreshActivePlugins()`. This bumps `mcp.pluginReconnectKey` to trigger MCP effect re-runs and reloads all Layer 3 components.

### Tool and Command Merging

**`useMergedTools(initialTools, mcpTools, toolPermissionContext)`**:
1. Calls `assembleToolPool()` -- the shared function used by both REPL and `runAgent` -- which combines `getTools()` (built-in tools) with MCP tools, applies deny rules, and deduplicates.
2. Calls `mergeAndFilterTools()` to merge `initialTools` on top, applying permission mode filtering.
3. The result is memoized on the tool inputs plus bridge state.

**`useMergedCommands(initialCommands, mcpCommands)`**:
1. Concatenates initial commands with MCP-sourced commands.
2. Deduplicates by name using `uniqBy`, with initial commands taking precedence.

### Agent Loading from Plugins

`loadPluginAgents()` (memoized) processes each enabled plugin in parallel:

1. Walk markdown files in the plugin's `agentsPath` and `agentsPaths` directories.
2. Parse frontmatter for agent metadata: `name`, `description`/`when-to-use`, `tools`, `skills`, `color`, `model`, `background`, `memory`, `isolation`, `effort`, `maxTurns`, `disallowedTools`.
3. Apply namespace prefixing: `{pluginName}:{namespace}:{agentName}` as the `agentType`.
4. Substitute `${CLAUDE_PLUGIN_ROOT}` and `${user_config.X}` variables in the system prompt.
5. **Security boundary**: `permissionMode`, `hooks`, and `mcpServers` frontmatter fields are intentionally ignored for plugin agents. These fields could escalate privileges beyond what the user approved at install time. For that level of control, agents must be defined in `.claude/agents/`.

### Error Handling

Plugin errors are captured as typed `PluginError` discriminated unions:

- `path-not-found` -- a declared path does not exist on disk
- `git-auth-failed` -- SSH or HTTPS authentication failed during clone
- `git-clone-failed` -- Git clone failed for other reasons
- `manifest-invalid` -- manifest.json failed schema validation
- `manifest-not-found` -- no manifest.json in the plugin directory
- `load-failed` -- generic loading failure with error message
- `marketplace-not-found` -- marketplace URL is unreachable
- `components-failed` -- individual component (commands, agents, hooks) failed to load

Errors are accumulated in `AppState.plugins.errors` and surfaced in the Doctor UI. Individual component loading failures do not prevent other components from the same plugin from loading.

## Key Interfaces

```typescript
// What the plugin system produces after loading
type LoadedPlugin = {
  name: string
  manifest: PluginManifest
  path: string
  source: string              // "{name}@{marketplace}" identifier
  repository: string
  enabled?: boolean
  isBuiltin?: boolean
  commandsPath?: string
  commandsPaths?: string[]
  agentsPath?: string
  agentsPaths?: string[]
  skillsPath?: string
  skillsPaths?: string[]
  hooksConfig?: HooksSettings
  mcpServers?: Record<string, McpServerConfig>
}

// Built-in plugin definition (ships with the CLI)
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

// Plugin state in AppState
AppState.plugins: {
  enabled: LoadedPlugin[]
  disabled: LoadedPlugin[]
  commands: Command[]
  errors: PluginError[]
  installationStatus: { marketplaces: [...], plugins: [...] }
  needsRefresh: boolean
}

// Tool merging hook
function useMergedTools(
  initialTools: Tools,
  mcpTools: Tools,
  toolPermissionContext: ToolPermissionContext,
): Tools

// Command merging hook
function useMergedCommands(
  initialCommands: Command[],
  mcpCommands: Command[],
): Command[]

// Agent loading (memoized)
function loadPluginAgents(): Promise<AgentDefinition[]>
```

## See Also

- [Plugin System](../entities/plugin-system.md) -- plugin loading, caching, and marketplace management
- [Tool System](../entities/tool-system.md) -- built-in tools and tool pool assembly
- [Command System](../entities/command-system.md) -- slash command definitions and routing
- [Agent System](../entities/agent-system.md) -- agent definitions and spawning
- [MCP System](../entities/mcp-system.md) -- Model Context Protocol server connections
- [Hook System](../concepts/hook-system.md) -- lifecycle hooks and event handlers
- [Configuration Resolution Chain](./configuration-resolution-chain.md) -- how plugin settings merge with other configuration
- [Settings Hierarchy](../concepts/settings-hierarchy.md) -- where plugin enable/disable state is persisted
