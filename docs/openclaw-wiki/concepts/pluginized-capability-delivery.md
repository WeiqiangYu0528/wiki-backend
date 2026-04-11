# Pluginized Capability Delivery

## Overview

OpenClaw delivers the majority of its value through plugins: model providers, channel integrations, memory systems, media generation, voice, web search, MCP servers, and more are all contributed by plugins rather than hardcoded into the host. The plugin platform's key design invariant is that this extensibility is not ad-hoc — every plugin goes through the same discovery, manifest validation, activation, and registry assembly pipeline, and only capabilities in the active `PluginRegistry` are visible to the runtime.

This concept explains why the gateway, channels, providers, and runtime capabilities can evolve or be swapped independently. Each plugin isolates its implementation behind a shared API surface; the host never imports plugin internals.

## Mechanism

### Plugin Lifecycle

```
Discovery → Manifest Load → Activation Decision → Registry Assembly → Active Registry
```

1. **Discovery** — `discoverOpenClawPlugins()` scans bundled, user, and workspace plugin paths.
2. **Manifest load** — each plugin's `openclaw.plugin.json` is parsed into `PluginManifest`. No plugin code runs yet.
3. **Activation decision** — `resolveEffectivePluginActivationState()` applies: hard enables/disables from config, `enabledByDefault`, `autoEnableWhenConfiguredProviders`, and user toggles.
4. **Registry assembly** — `createPluginRegistry()` runs each active plugin's factory function with a fresh `OpenClawPluginApi` instance. The plugin calls `api.registerChannel()`, `api.registerTool()`, `api.registerHook()`, etc.
5. **Active registry swap** — `setActivePluginRegistry()` installs the new registry atomically. Old registry is discarded.

### Manifest-Gated Cheap Routing

Several decisions happen without loading any plugin runtime:
- Model ID routing: `modelPrefixes` and `modelPatterns` in the manifest identify which provider owns a model shorthand.
- Auto-enable: `autoEnableWhenConfiguredProviders` activates a plugin when a referenced provider appears in auth config.
- Auth options: `providerAuthChoices` and `providerAuthEnvVars` power the onboarding wizard without booting provider plugins.

This separation keeps startup cost low even with many installed plugins.

### Registration Surface

Plugins can register into any of these runtime surfaces via `OpenClawPluginApi`:

| Surface | Registration Method | Consumer |
|---------|--------------------|-----------------------|
| Channel integration | `registerChannel(plugin)` | Gateway channel manager |
| Agent tool | `registerTool(factory)` | Agent runtime tool set |
| Lifecycle hook | `registerHook(name, handler)` | Global hook runner |
| Model provider | `registerProvider(plugin)` | Model catalog, agent runtime |
| Memory runtime | `registerMemoryRuntime(rt)` | Context engine |
| Memory corpus supplement | `registerMemoryCorpusSupplement(fn)` | Retrieval pipeline |
| Memory prompt supplement | `registerMemoryPromptSupplement(fn)` | System prompt builder |
| HTTP route | `registerHttpRoute(path, handler, auth)` | Gateway HTTP layer |
| Gateway method handler | `registerGatewayHandler(method, fn)` | Gateway method dispatch |
| Image/Music/Video generation | `register*GenerationProvider(p)` | Media generation pipeline |
| TTS provider | `registerSpeechProvider(p)` | TTS pipeline |
| Realtime voice provider | `registerRealtimeVoiceProvider(p)` | Voice session pipeline |
| Memory embedding provider | `registerMemoryEmbeddingProvider(p)` | Semantic search backend |
| Node host command | `registerNodeHostCommand(cmd)` | Node host invoke dispatch |
| Interactive handler | `registerInteractiveHandler(name, fn)` | CLI interactive flow |

### Isolation Mechanism

Plugins are loaded with `jiti` (a TypeScript-aware require) using a custom alias map (`buildPluginLoaderAliasMap()`). The alias map redirects all plugin-SDK imports (e.g., `@openclaw/plugin-sdk`) to the host's own module copies. This prevents version conflicts: the plugin uses the host's API without bundling its own copy.

`path-safety.ts` validates that plugin files are within allowed directories, preventing path traversal from untrusted plugin paths.

### Hot Reload

`startGatewayConfigReloader()` triggers plugin reload when `openclaw.yml` changes. `loadGatewayStartupPlugins()` and `reloadDeferredGatewayPlugins()` re-run the full discovery → assembly pipeline. The http-route and channel sub-surfaces can be pinned (`surface.pinned = true`) to survive reload without disruption — useful for long-lived channel account connections.

### Version Compatibility

`min-host-version.ts` checks whether a plugin's declared `minHostVersion` is satisfied by the current gateway version. Plugins that require a newer host are skipped with a diagnostic warning rather than crashing the activation pipeline.

## Invariants

1. **No runtime capability is injected outside the plugin API.** All tools, hooks, channels, and providers flow through `PluginRegistry`.
2. **Activation is always decided before loading plugin code.** Manifests gate activation; plugin factories run only for active plugins.
3. **The active registry is immutable once installed.** Callers read `getActivePluginRegistry()` safely without locking.
4. **Plugin loading is isolated.** Alias maps prevent plugin dependencies from leaking into host module resolution.

## Involved Entities

- [Plugin Platform](../entities/plugin-platform.md) — implements the full lifecycle
- [Channel Plugin Adapters](../entities/channel-plugin-adapters.md) — most complex plugin type
- [Provider and Model System](../entities/provider-and-model-system.md) — provider plugins
- [Skills Platform](../entities/skills-platform.md) — plugins contribute skill directories
- [Agent Runtime](../entities/agent-runtime.md) — consumes tools and hooks from the active registry

## Source Evidence

| File | Contribution |
|------|-------------|
| `src/plugins/loader.ts` | `loadPlugin()` — jiti loading, alias map construction |
| `src/plugins/discovery.ts` | `discoverOpenClawPlugins()` |
| `src/plugins/registry.ts` | `PluginRegistry` type, `createPluginRegistry()` |
| `src/plugins/runtime.ts` | `setActivePluginRegistry()`, `getActivePluginRegistry()` |
| `src/plugins/config-state.ts` | `resolveEffectivePluginActivationState()` |
| `src/plugins/api-builder.ts` | `buildPluginApi()` — constructs `OpenClawPluginApi` |
| `src/plugins/sdk-alias.ts` | `buildPluginLoaderAliasMap()` — isolation mechanism |
| `src/plugins/min-host-version.ts` | Version compatibility check |
| `src/plugins/path-safety.ts` | Path traversal prevention |

## See Also

- [Plugin Platform](../entities/plugin-platform.md)
- [Extension to Runtime Capability Flow](../syntheses/extension-to-runtime-capability-flow.md)
- [Channel Binding and Session Identity Flow](../syntheses/channel-binding-and-session-identity-flow.md)
- [Gateway as Control Plane](gateway-as-control-plane.md) — gateway manages plugin lifecycle
