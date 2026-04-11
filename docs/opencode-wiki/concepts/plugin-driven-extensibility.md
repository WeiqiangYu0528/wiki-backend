# Plugin Driven Extensibility

## Overview

OpenCode's plugin system is a hook-based extension mechanism loaded at startup. A plugin is a function that, when called with the current runtime context, returns a `Hooks` object. Each field of `Hooks` is an optional async callback invoked at a named lifecycle point — auth resolution, model selection, tool contribution, session start, and more. The system distinguishes between internal plugins (Codex, Copilot, GitLab, Poe) bundled directly into the binary and external plugins loaded from npm packages at runtime. The `--pure` flag (or `OPENCODE_PURE=1`) disables external plugin loading while keeping internal plugins active. Plugin errors are reported through the session `Bus` rather than crashing the server.

## Mechanism

### Plugin.Interface

`Plugin.Interface` is the service type that the rest of the application interacts with:

```typescript
interface Interface {
  trigger: <Name extends TriggerName, Input, Output>(
    name: Name,
    input: Input,
    output: Output
  ) => Effect.Effect<Output>
  list:    () => Effect.Effect<Hooks[]>
  init:    () => Effect.Effect<void>
}
```

`trigger()` is the call site used everywhere in the application that wants to run plugin hooks. It accepts a `TriggerName` (a key from `Hooks` whose value is `(input, output) => Promise<void>`), the input value, and the current output value. Each registered hook can mutate the output in place. The final output after all hooks have run is returned to the caller.

`TriggerName` is a mapped type computed from `Hooks`:

```typescript
type TriggerName = {
  [K in keyof Hooks]-?: NonNullable<Hooks[K]> extends
    (input: any, output: any) => Promise<void> ? K : never
}[keyof Hooks]
```

This ensures `trigger()` is only callable with hook names that follow the `(input, output) => Promise<void>` shape, giving compile-time safety for all plugin call sites.

### Hooks type

`Hooks` (from `@opencode-ai/plugin`) defines the complete set of named extension points. Each field is an optional async function. Examples include hooks for authentication credential injection, model list augmentation, tool list augmentation, and session lifecycle events. Because each field is optional, a plugin only needs to implement the hooks relevant to its purpose.

### Internal plugins

`INTERNAL_PLUGINS` is a constant array defined in `plugin/index.ts`:

```typescript
const INTERNAL_PLUGINS: PluginInstance[] = [
  CodexAuthPlugin,
  CopilotAuthPlugin,
  GitlabAuthPlugin,
  PoeAuthPlugin,
]
```

These four plugins are imported directly (not resolved from npm) and are always loaded regardless of the `--pure` flag or any config setting. They handle authentication flows for the Amazon Bedrock Codex endpoint, GitHub Copilot, GitLab AI integration, and Poe. Because they are bundled, they are available even in air-gapped or restricted environments.

### External plugin loading

External plugins are discovered and loaded by `PluginLoader` (from `./loader`). The loader reads the `plugins` array from `Config` (the `opencode.json` file). Each entry is a plugin specifier string that can be:

- An npm package name (`my-opencode-plugin`)
- A scoped npm package (`@myorg/opencode-plugin`)
- A local path (`./plugins/my-plugin`)

`parsePluginSpecifier()` and `resolvePluginId()` from `./shared` normalize these strings to a canonical plugin identifier. `readPluginId()` extracts the plugin ID from the resolved package. `readV1Plugin()` handles the v1 plugin format where the export is a plain function. `getLegacyPlugins()` handles older plugin formats that export multiple named entries.

For npm-based plugins, `PluginLoader` calls `Npm` to install the package before importing it, ensuring the plugin is available locally even if it was not previously installed.

### Server plugin detection

`getServerPlugin()` checks whether a module export is a server-side plugin (as opposed to a client-side or UI plugin). It accepts either a direct function export or an object with a `.server` property. Only server plugins are registered with `Plugin.Service`; client-side plugin exports are ignored by the server.

### --pure flag bypass

`Flag` provides `Flag.pure` (set by `--pure` or `OPENCODE_PURE=1`). When this flag is active, `Plugin.Service.init()` skips the `PluginLoader` entirely and only registers `INTERNAL_PLUGINS`. This is useful for reproducible testing, minimal deployments, or security-sensitive environments where loading arbitrary npm packages at runtime is undesirable.

### Error reporting via Bus

`publishPluginError()` is called whenever a plugin hook throws or a plugin fails to load:

```typescript
function publishPluginError(bus: Bus.Interface, message: string) {
  Effect.runFork(
    bus.publish(Session.Event.Error, {
      error: new NamedError.Unknown({ message }).toObject()
    })
  )
}
```

This publishes a `Session.Event.Error` on the bus, which flows through the SSE stream to connected clients as a visible error message. The server does not crash; the plugin that failed is skipped and the session continues with the remaining plugin hooks. This makes plugin failures observable without being fatal.

### Plugin lifecycle within an instance

Plugins are initialized during `InstanceBootstrap` (called from `Instance.provide()` via the `init` callback). This means plugins are scoped to the project instance: each project directory gets its own plugin initialization, and plugin state is not shared between instances. When an instance is disposed, plugin state for that instance is cleaned up as part of `disposal.all`.

## Invariants

1. `INTERNAL_PLUGINS` are always loaded. The `--pure` flag suppresses external plugins only; internal plugins are unconditional.
2. Plugin hooks are called in registration order. If two plugins register the same hook, both are called sequentially; the output of the first is the input to the second.
3. A plugin hook that throws does not abort the hook chain. `publishPluginError()` is called and the chain continues with the remaining plugins.
4. External plugins are loaded once per instance initialization. Hot-reloading a plugin without restarting the server (or reloading the instance) is not supported.
5. `trigger()` is type-safe at the call site. Only `TriggerName`-valid hook names can be passed; passing an unsupported name is a compile-time error.
6. Plugin-contributed tools appear in the tool registry only after `Plugin.Service.init()` completes. Tools contributed by plugins that fail to load are not available.

## Source Evidence

| File | What it confirms |
| --- | --- |
| `packages/opencode/src/plugin/index.ts` | `Plugin.Interface`, `TriggerName` mapped type, `INTERNAL_PLUGINS` array, `publishPluginError()`, `getLegacyPlugins()`, `getServerPlugin()`, `Flag` import for pure mode check |
| `packages/opencode/src/plugin/loader.ts` | `PluginLoader` implementation; npm install and import logic |
| `packages/opencode/src/plugin/shared.ts` | `parsePluginSpecifier()`, `resolvePluginId()`, `readPluginId()`, `readV1Plugin()` |
| `packages/opencode/src/flag/flag.ts` | `Flag.pure` definition |
| `packages/opencode/src/project/bootstrap.ts` | `InstanceBootstrap` calling `Plugin.Service.init()` during instance startup |
| `packages/opencode/src/bus/index.ts` | `Bus.Interface` and `publish()` used by `publishPluginError()` |

## See Also

- [Client Server Agent Architecture](client-server-agent-architecture.md)
- [Project Scoped Instance Lifecycle](project-scoped-instance-lifecycle.md)
- [Tool and Agent Composition](tool-and-agent-composition.md)
- [Plugin System](../entities/plugin-system.md)
- [Provider Tool Plugin Interaction Model](../syntheses/provider-tool-plugin-interaction-model.md)
- [Multi Client Product Architecture](../syntheses/multi-client-product-architecture.md)
- [Request to Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
