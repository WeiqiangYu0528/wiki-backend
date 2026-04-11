# Plugin Platform

## Overview

The plugin platform is the main extensibility substrate in OpenClaw. It discovers plugins from the filesystem and marketplace (`ClaWHub`), validates manifests, resolves activation rules, constructs per-plugin runtime API instances (`OpenClawPluginApi`), manages install/uninstall state, and maintains the active `PluginRegistry` — the single source of truth for which channels, providers, tools, hooks, memory supplements, and gateway method handlers are live at any moment.

Every channel integration, AI provider, and capability extension (image generation, voice, web search, MCP) is delivered as a plugin. The gateway consults the active plugin registry for routing decisions, channel management, tool availability, and hook execution.

## Key Types

```ts
// src/plugins/registry.ts
export type PluginRegistry = {
  plugins: PluginRecord[];
  tools: PluginToolRegistration[];
  hooks: PluginHookRegistration[];
  typedHooks: TypedPluginHookRegistration[];
  channels: PluginChannelRegistration[];
  providers: ProviderPlugin[];
  // ... memory supplements, http routes, etc.
};
```

The registry is immutable once built; the active registry is swapped atomically by `setActivePluginRegistry()`.

```ts
// src/plugins/runtime.ts
export function setActivePluginRegistry(
  registry: PluginRegistry,
  cacheKey?: string,
  runtimeSubagentMode?: "default" | "explicit" | "gateway-bindable",
  workspaceDir?: string,
): void;

export function getActivePluginRegistry(): PluginRegistry | null;
```

Two sub-surfaces track the http-route registry and channel registry independently, each versioned and optionally pinned to prevent hot-reload from clobbering them mid-request.

### Plugin Manifest

Each plugin ships an `openclaw.plugin.json` manifest:

```ts
// src/plugins/manifest.ts
export type PluginManifest = {
  id: string;
  configSchema: Record<string, unknown>;
  enabledByDefault?: boolean;
  legacyPluginIds?: string[];
  autoEnableWhenConfiguredProviders?: string[];
  kind?: PluginKind | PluginKind[];  // "channel" | "provider" | "extension" | ...
  channels?: string[];
  providers?: string[];
  modelSupport?: PluginManifestModelSupport;
  providerAuthEnvVars?: Record<string, string[]>;
  providerAuthChoices?: PluginManifestProviderAuthChoice[];
  skills?: string[];
  name?: string;
  description?: string;
};
```

The manifest enables cheap pre-load decisions: model prefix ownership, auto-enable triggers, and auth env lookups all read from the manifest without booting the plugin runtime.

## Architecture

### Discovery and Loading

`discoverOpenClawPlugins()` in `src/plugins/discovery.ts` scans standard plugin directories: bundled plugins in the package, user-installed plugins in `~/.openclaw/plugins/`, and workspace-local plugins. Discovery returns plugin records sorted by activation priority.

`loadPluginManifestRegistry()` loads and validates all discovered manifests. Only plugins with valid manifests enter the activation pipeline.

The loader (`src/plugins/loader.ts`) uses `jiti` (a TypeScript-aware require) to import plugin modules from disk. It builds an alias map (`buildPluginLoaderAliasMap()`) that redirects plugin-SDK imports to the host's own copies, preventing version conflicts between the plugin and the host.

### Activation Pipeline

Plugin activation follows a priority chain managed by `resolveEffectivePluginActivationState()`:

1. **Hard-enable / hard-disable** from config — cannot be overridden.
2. **Auto-enable** triggers: configured provider, model prefix, `enabledByDefault: true`.
3. **User toggle** from `openclaw.yml` `plugins.enabled` / `plugins.disabled`.

`createPluginActivationSource()` tracks which source triggered activation for diagnostics.

### Registry Assembly

`createPluginRegistry()` assembles the registry by calling each active plugin's factory function with a constructed `OpenClawPluginApi` instance. The plugin API (`src/plugins/api-builder.ts`) exposes registration methods:

```ts
api.registerChannel(channelPlugin)
api.registerTool(toolFactory)
api.registerHook(hookName, handler)
api.registerProvider(providerPlugin)
api.registerMemoryRuntime(runtime)
api.registerHttpRoute(path, handler, auth)
// ...and ~20 more surface registrations
```

After all plugins run their factory functions, the registry is frozen and installed as the active registry via `setActivePluginRegistry()`.

### Hot Reload

`startGatewayConfigReloader()` watches `openclaw.yml` for changes. On change, it calls `loadGatewayStartupPlugins()` to rebuild the registry with the updated config. The http-route and channel sub-surfaces can be independently pinned (`installSurfaceRegistry(..., pinned: true)`) to survive reload without disruption.

### Hook System

Plugin hooks fire at defined lifecycle points. Hook names include `before-agent-reply`, `before-agent-start`, `before-tool-call`, `after-tool-call`, `before-install`, and prompt mutation hooks. The global hook runner (`src/plugins/hook-runner-global.ts`) runs all registered hooks in registration order, collecting results for the gateway.

### Memory Supplements

Memory plugins can register:
- `registerMemoryRuntime(runtime)` — a full memory runtime
- `registerMemoryCorpusSupplement(fn)` — extra content for memory retrieval
- `registerMemoryPromptSupplement(fn)` — text injected into the system prompt
- `registerMemoryEmbeddingProvider(provider)` — embedding backend for semantic search

## Source Files

| File | Purpose |
|------|---------|
| `src/plugins/registry.ts` | `PluginRegistry` type, `createPluginRegistry()` — registry assembly |
| `src/plugins/runtime.ts` | `setActivePluginRegistry()`, `getActivePluginRegistry()` — active registry swap |
| `src/plugins/runtime-state.ts` | `PLUGIN_REGISTRY_STATE` global state container |
| `src/plugins/loader.ts` | `loadPlugin()` — jiti-based module loading with SDK alias resolution |
| `src/plugins/discovery.ts` | `discoverOpenClawPlugins()` — filesystem plugin scan |
| `src/plugins/manifest.ts` | `PluginManifest` type, manifest parsing and validation |
| `src/plugins/manifest-registry.ts` | `loadPluginManifestRegistry()` — load all manifests |
| `src/plugins/api-builder.ts` | `buildPluginApi()` — constructs `OpenClawPluginApi` per-plugin |
| `src/plugins/config-state.ts` | Activation state resolution, `resolveEffectivePluginActivationState()` |
| `src/plugins/types.ts` | All plugin type exports: `OpenClawPluginDefinition`, `PluginKind`, hook names |
| `src/plugins/hooks.ts` | Hook registration, validation, and execution helpers |
| `src/plugins/hook-runner-global.ts` | Global hook runner for gateway-lifetime hooks |
| `src/plugins/install.ts` | Plugin install/uninstall logic |
| `src/plugins/marketplace.ts` | ClaWHub marketplace integration |
| `src/plugins/sdk-alias.ts` | SDK alias resolution for isolated plugin loading |
| `src/plugins/memory-state.ts` | Memory runtime registration and lookup |
| `src/plugins/clawhub.ts` | ClaWHub plugin catalog and install flow |

## See Also

- [Channel Plugin Adapters](channel-plugin-adapters.md) — channel plugins registered through this platform
- [Provider and Model System](provider-and-model-system.md) — provider plugins registered here
- [Skills Platform](skills-platform.md) — skill files contributed by plugins
- [Agent Runtime](agent-runtime.md) — consumes tools and hooks from the active registry
- [Pluginized Capability Delivery](../concepts/pluginized-capability-delivery.md)
- [Extension to Runtime Capability Flow](../syntheses/extension-to-runtime-capability-flow.md)
