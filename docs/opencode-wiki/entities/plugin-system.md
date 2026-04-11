# Plugin System

## Overview

The OpenCode plugin system provides a structured extension mechanism that allows both first-party and third-party code to hook into the AI assistant lifecycle. Plugins observe and transform the inputs and outputs of LLM interactions, register authentication providers, and can inject additional tools or context into sessions. The system distinguishes between internal (bundled) plugins that are always loaded and external plugins resolved at runtime from npm packages or local paths.

The plugin subsystem is implemented in `src/plugin/index.ts` and organized under the `Plugin` namespace. It depends on the `@opencode-ai/plugin` package for the shared plugin contract types (`Hooks`, `PluginInput`, `Plugin`, `PluginModule`). Plugin state is scoped to a workspace instance via `InstanceState`.

## Key Types

### `Plugin.Interface`

The service interface exposed to the rest of the application has three methods:

- `trigger(name, input, output)` — fires all registered hooks for a given `TriggerName`. Each hook matching the name receives the mutable input and output objects and can modify them before the next hook runs.
- `list()` — returns the array of currently active `Hooks[]` objects, one per successfully loaded plugin.
- `init()` — performs initial loading of all internal and external plugins.

### `Plugin.Service`

`Plugin.Service` extends `ServiceMap.Service` with the tag `"@opencode/Plugin"`. It is provided through the Effect layer system as `Plugin.layer` and accessed by other services via dependency injection. The Effect runtime manages the service lifecycle automatically.

### `TriggerName`

`TriggerName` is a compile-time mapped type that filters `Hooks` property keys to only those whose value type satisfies `(input: any, output: any) => Promise<void>`. This prevents callers from attempting to trigger hooks that do not follow the two-argument async pattern, providing type-level safety for all hook dispatch.

### `Hooks`

The `Hooks` type (from `@opencode-ai/plugin`) is the central plugin contract. Each loaded plugin factory is called once and returns a `Hooks` object registering its callback functions. The `Hooks` array stored in `State.hooks` is iterated on every `trigger()` call.

### `Plugin.Event`

Plugin load errors are published as `Session.Event.Error` events onto the `Bus`. This surfaces failures to connected clients (TUI, web) as session warnings without halting initialization. The `publishPluginError()` helper forks a fire-and-forget effect for each error.

## Architecture

### Internal Plugins

Four built-in authentication plugins are hardcoded in the `INTERNAL_PLUGINS` array and are always loaded regardless of configuration or flags:

| Exported Symbol | Package |
|---|---|
| `CodexAuthPlugin` | `./codex` (local source) |
| `CopilotAuthPlugin` | `./github-copilot/copilot` (local source) |
| `GitlabAuthPlugin` | `opencode-gitlab-auth` (npm dependency) |
| `PoeAuthPlugin` | `opencode-poe-auth` (npm dependency) |

These plugins handle OAuth and API-key authentication flows for their respective AI providers. They receive the `PluginInput` object and return `Hooks` objects that intercept requests to inject credentials.

### External Plugins

External plugins are declared in the project configuration under `plugin_origins`. The system reads this array and passes it to `PluginLoader.loadExternal()`. External plugin loading is **skipped entirely** when the `OPENCODE_PURE` flag (`Flag.OPENCODE_PURE`) is set — this is the `--pure` mode bypass. When pure mode is active and `plugin_origins` contains entries, a log message is emitted at info level but no error is raised.

When external plugins are to be loaded, `config.waitForDependencies()` is called first to ensure the configuration layer has fully settled (for example, waiting for remote workspace config to arrive) before resolution begins.

### Plugin Versioning and Module Formats

The plugin loader handles both v1 (modern) and legacy plugin module formats:

- `readV1Plugin(mod, spec, "server", "detect")` attempts to detect a modern plugin module with a typed `server` export.
- `getLegacyPlugins(mod)` iterates all named exports of an older module and locates plugin functions via `getServerPlugin()`.

`isServerPlugin(value)` checks whether an export is a plain callable function. `getServerPlugin(value)` extends this to also accept objects with a `.server` property that is a function, handling the dual-export pattern common in packages that provide both `server` and `client` entry points for the same plugin.

### `PluginLoader`

`PluginLoader` in `src/plugin/loader.ts` manages the full lifecycle of resolving, installing, and loading an external plugin. Its main types are:

- `PluginLoader.Plan` — parsed specifier, options, and deprecation flag.
- `PluginLoader.Resolved` — plan plus resolved source, target path, entry file path, and optional package metadata.
- `PluginLoader.Missing` — plan plus diagnostic info for when the plugin cannot be located.
- `PluginLoader.Loaded` — resolved plus the dynamically imported module object (`mod`).

The `resolve(plan, kind)` function drives the resolution pipeline:

1. `resolvePluginTarget(spec)` — locates the plugin in the npm store or local filesystem.
2. `createPluginEntry(spec, target, kind)` — determines the correct `server` or `client` entry file.
3. `checkPluginCompatibility(...)` — verifies the plugin is compatible with the running OpenCode version.
4. Dynamic `import()` of the resolved entry path.

### `parsePluginSpecifier()`

`parsePluginSpecifier()` in `src/plugin/shared.ts` normalizes plugin origin strings into canonical specifier form. Plugin origins can be:

- A bare npm package name: `opencode-my-plugin`
- A scoped package: `@org/opencode-plugin`
- A local path: `./plugins/myplugin`
- A versioned package: `opencode-my-plugin@1.2.3`

Normalization ensures consistent cache key generation and deduplication when the same plugin is referenced multiple ways.

### Plugin ID Resolution

`resolvePluginId()` and `readPluginId()` work together to establish a stable identifier for each loaded plugin. The identifier is written to disk alongside the plugin installation, allowing the system to detect changes across restarts and invalidate cached entry points when a plugin is updated.

## Runtime Behavior

Plugin initialization occurs inside `InstanceState.make()`, which means plugins are initialized once per workspace instance and re-initialized when the instance is recycled. The initialization sequence is:

1. Create an `OpencodeClient` pointed at `http://localhost:4096` (the local server). If `Flag.OPENCODE_SERVER_PASSWORD` is set, HTTP Basic auth headers are injected using `Flag.OPENCODE_SERVER_USERNAME` (defaulting to `"opencode"`).
2. Build a `PluginInput` object that captures: the resolved project directory, worktree root, a lazy `serverUrl` getter, and a `Bun.$` shell reference for subprocess execution.
3. Iterate `INTERNAL_PLUGINS`, calling each factory function with `PluginInput`. Errors are caught per-plugin via `Effect.tryPromise` wrapped in `Effect.option` so a single failing internal plugin does not block the others.
4. If `OPENCODE_PURE` is false, read `cfg.plugin_origins`, then call `PluginLoader.loadExternal()` with a `Report` callback for progress events (displayed in the TUI during startup).
5. For each successfully loaded module, call `applyPlugin()`. This attempts v1 detection first, then falls back to legacy multi-export traversal. `resolvePluginId()` is called to persist the plugin's identity.
6. All collected `Hooks` objects are stored in `State.hooks`. Every subsequent `trigger()` call iterates this array.

### `applyPlugin()` Detail

`applyPlugin(load, input, hooks)` is the internal function that bridges a `PluginLoader.Loaded` result to the hooks array. For v1 plugins it calls `plugin.server(input, load.options)` and awaits the result. For legacy plugins it iterates all identified server exports and calls each one.

## Source Files

- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/plugin/index.ts` — main `Plugin` namespace, `Plugin.Service`, layer, `INTERNAL_PLUGINS`, `applyPlugin`, `getLegacyPlugins`, `isServerPlugin`, `getServerPlugin`
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/plugin/loader.ts` — `PluginLoader` namespace with `resolve()`, `loadExternal()`, and plan/resolved/missing/loaded types
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/plugin/shared.ts` — `parsePluginSpecifier()`, `resolvePluginId()`, `readPluginId()`, `readV1Plugin()`, `resolvePluginTarget()`, shared type definitions
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/plugin/codex.ts` — `CodexAuthPlugin` implementation
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/plugin/github-copilot/copilot.ts` — `CopilotAuthPlugin` implementation

## See Also

- [Provider System](./provider-system.md) — authentication plugins register credentials consumed by providers
- [Session System](./session-system.md) — `Session.Event.Error` bus events surfaced by plugin errors
- [Tool System](./tool-system.md) — plugins may extend the tool registry via the Hooks interface
- [CLI Runtime](./cli-runtime.md) — `--pure` flag is exposed as `Flag.OPENCODE_PURE`
- [Server API](./server-api.md) — the `OpencodeClient` used in `PluginInput` points at the local server
