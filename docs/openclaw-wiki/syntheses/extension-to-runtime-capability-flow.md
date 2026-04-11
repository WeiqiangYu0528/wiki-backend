# Extension to Runtime Capability Flow

## Overview

This synthesis traces the exact path a plugin travels from raw discovery on the filesystem to an active capability visible to the gateway, agent runtime, and connected channels. The pipeline is deterministic and staged: no plugin code executes until the manifest has been validated and the activation decision has been made. Only plugins that pass activation write into the `PluginRegistry`, and only what is in the active registry is visible to the rest of the runtime.

Understanding this flow explains why plugins appear or disappear in response to config changes, why model routing works before provider plugins are loaded, and how hot-reload avoids disrupting in-flight requests. It also shows where to look when a plugin fails silently: each stage has a distinct failure mode, and the pipeline continues past failed stages rather than stopping at the first error.

## Systems Involved

| System | Contribution |
|--------|-------------|
| [Plugin Platform](../entities/plugin-platform.md) | Discovery, manifest load, activation resolution, registry assembly, jiti isolation |
| [Pluginized Capability Delivery](../concepts/pluginized-capability-delivery.md) | Invariants governing how all capabilities flow through the registry |
| [Provider and Model System](../entities/provider-and-model-system.md) | Provider activation, model catalog assembly, manifest-level routing |
| [Channel Plugin Adapters](../entities/channel-plugin-adapters.md) | Channel registration through `registerChannel()`, account loop startup |

## Discovery and Manifest Load

The pipeline starts with `discoverOpenClawPlugins()` in `src/plugins/discovery.ts`. This function scans three locations:

1. **Bundled plugins** — shipped inside the OpenClaw package itself (channels, built-in providers, core tools).
2. **User-installed plugins** — located in `~/.openclaw/plugins/`, including anything installed from the ClaWHub marketplace.
3. **Workspace-local plugins** — plugins declared in the local project directory.

Discovery returns an ordered list of plugin records, sorted by activation priority. The sort order matters: higher-priority plugins win when two plugins attempt to register the same model prefix or channel ID.

After discovery, `loadPluginManifestRegistry()` reads each plugin's `openclaw.plugin.json` and parses it into a `PluginManifest` object. This is a pure IO and validation step — no plugin JavaScript or TypeScript executes. Plugins with unparseable or schema-invalid manifests are logged and excluded from the activation pipeline. The manifest type is:

```ts
export type PluginManifest = {
  id: string;
  configSchema: Record<string, unknown>;
  enabledByDefault?: boolean;
  legacyPluginIds?: string[];
  autoEnableWhenConfiguredProviders?: string[];
  kind?: PluginKind | PluginKind[];
  channels?: string[];
  providers?: string[];
  modelSupport?: PluginManifestModelSupport;  // { modelPrefixes, modelPatterns }
  providerAuthEnvVars?: Record<string, string[]>;
  providerAuthChoices?: PluginManifestProviderAuthChoice[];
  skills?: string[];
  name?: string;
  description?: string;
};
```

Several runtime decisions are made directly from manifest data, before any plugin code runs. The `modelPrefixes` and `modelPatterns` fields let the gateway route a model ID like `claude-sonnet-4-6` to the correct provider plugin without importing any provider SDK. The `providerAuthEnvVars` field drives the onboarding wizard's API key detection. This manifest-level pre-loading keeps startup cost low regardless of how many plugins are installed.

## Activation Decision

With manifests loaded, `resolveEffectivePluginActivationState()` in `src/plugins/config-state.ts` decides whether each plugin is active. It applies a priority chain:

1. **Hard-enable / hard-disable** — explicit overrides from gateway config. These cannot be overridden by anything else and are intended for operators who need to lock plugin state.
2. **Auto-enable triggers** — a plugin activates automatically if any of these conditions are true:
   - `enabledByDefault: true` in the manifest (the plugin opts in to being on without user action).
   - `autoEnableWhenConfiguredProviders` lists a provider ID that appears in the current auth config (e.g., the Anthropic provider plugin auto-enables when an Anthropic API key is configured).
   - The plugin's declared model prefix is referenced in agent config.
3. **User toggle** — explicit `plugins.enabled` or `plugins.disabled` entries in `openclaw.yml` override auto-enable but not hard overrides.

`createPluginActivationSource()` records which condition triggered activation. This source annotation is available for diagnostics: if a plugin is unexpectedly active or inactive, the activation source tells you exactly which rule won.

Plugins that are not active after this stage are never loaded. Their manifest fields remain available for cheap metadata lookups (model routing, auth detection), but their factory function is never called.

Version compatibility is also checked at this stage. `min-host-version.ts` reads the plugin's declared `minHostVersion` and compares it to the current gateway version. If the plugin requires a newer host, it is skipped with a diagnostic warning. The pipeline continues with the remaining plugins rather than failing entirely. This means a plugin that requires a newer API surface degrades gracefully instead of breaking the whole gateway startup.

## Registry Assembly

Once the set of active plugins is determined, `createPluginRegistry()` in `src/plugins/registry.ts` runs the assembly phase. For each active plugin, it:

1. Constructs a fresh `OpenClawPluginApi` instance using `buildPluginApi()` from `src/plugins/api-builder.ts`. Each plugin gets its own isolated API object; registrations from one plugin do not bleed into another's namespace.
2. Loads the plugin module from disk using the jiti-based loader in `src/plugins/loader.ts`.
3. Calls the plugin's factory function, passing the `OpenClawPluginApi` instance.
4. The plugin calls registration methods on the API to contribute capabilities.

The loader uses jiti (a TypeScript-aware require implementation) combined with an alias map produced by `buildPluginLoaderAliasMap()` in `src/plugins/sdk-alias.ts`. The alias map redirects all plugin imports of `@openclaw/plugin-sdk` and related SDK packages to the host's own module copies. This solves a fundamental problem in plugin architectures: if a plugin bundles its own copy of the SDK, type-level and runtime-level incompatibilities appear between the plugin's copy and the host's copy. By forcing all SDK imports through the host's module resolution, plugins share one copy of the SDK regardless of what version they declared in their own `package.json`. Path safety validation in `src/plugins/path-safety.ts` ensures the loaded module files are within allowed directories, preventing path traversal from untrusted plugin paths.

The full set of registration surfaces available through `OpenClawPluginApi` is:

```ts
api.registerChannel(channelPlugin)          // channel integration adapter
api.registerTool(toolFactory)               // agent tool
api.registerHook(hookName, handler)         // lifecycle hook
api.registerProvider(providerPlugin)        // AI model provider
api.registerMemoryRuntime(runtime)          // full memory runtime
api.registerMemoryCorpusSupplement(fn)      // extra retrieval content
api.registerMemoryPromptSupplement(fn)      // system prompt injection
api.registerMemoryEmbeddingProvider(p)      // semantic search backend
api.registerHttpRoute(path, handler, auth)  // gateway HTTP endpoint
api.registerGatewayHandler(method, fn)      // gateway method dispatch
api.registerImageGenerationProvider(p)      // image generation
api.registerMusicGenerationProvider(p)      // music generation
api.registerVideoGenerationProvider(p)      // video generation
api.registerSpeechProvider(p)              // TTS pipeline
api.registerRealtimeVoiceProvider(p)        // voice session pipeline
api.registerNodeHostCommand(cmd)            // node host invoke dispatch
api.registerInteractiveHandler(name, fn)    // CLI interactive flow
```

Each call appends a typed record to the registry being assembled. When all factory functions have run, `createPluginRegistry()` returns a frozen `PluginRegistry` object — an immutable snapshot of everything every active plugin contributed.

The active registry is then installed by `setActivePluginRegistry()` in `src/plugins/runtime.ts`:

```ts
export function setActivePluginRegistry(
  registry: PluginRegistry,
  cacheKey?: string,
  runtimeSubagentMode?: "default" | "explicit" | "gateway-bindable",
  workspaceDir?: string,
): void;
```

This swap is atomic. Callers that read `getActivePluginRegistry()` always see a complete, consistent registry — never a partially assembled one. The old registry is discarded after the swap.

## Hot Reload

`startGatewayConfigReloader()` watches `openclaw.yml` for changes. When a change is detected, it triggers `loadGatewayStartupPlugins()`, which re-runs the full discovery-to-assembly pipeline with the updated configuration and installs a new active registry via `setActivePluginRegistry()`.

Hot reload raises a practical problem: the gateway may have long-lived state tied to the previous registry. Channel accounts, for example, hold open connections to messaging networks that should not be torn down every time a config file changes. The http-route and channel sub-surfaces address this with a pinning mechanism. Setting `surface.pinned = true` on a sub-surface registry tells the reload logic to leave that surface in place rather than replacing it with the newly assembled version. This allows, for instance, a Discord account connection to survive a config reload that only changed an unrelated model setting.

The `installSurfaceRegistry(..., pinned: true)` call pattern appears in `src/plugins/runtime.ts` and is used by the channel manager after account startup to mark active channel sessions as stable. A pinned surface is only replaced when the reload explicitly unpins it, which happens when the channel configuration itself changes in a way that requires account restart.

## Version Compatibility

The `min-host-version.ts` module implements a version guard at the activation stage. Each plugin can declare a `minHostVersion` field indicating the oldest gateway version it is compatible with. The check compares this against the running gateway's version string using semver comparison.

When a plugin fails the version check, the behavior is:
- The plugin is excluded from the activation set.
- A diagnostic warning is emitted identifying the plugin and the version mismatch.
- The pipeline continues; other plugins are unaffected.

This design ensures that installing a plugin built for a newer API surface does not crash the gateway. The plugin simply becomes inactive until the gateway is upgraded. The warning makes the situation visible without requiring operator intervention.

## Extension Points Reference

All registration methods available through `OpenClawPluginApi` and their downstream consumers:

| Registration Method | Registry Field | Consumer |
|--------------------|---------------|---------|
| `registerChannel(plugin)` | `channels` | Gateway channel manager (`createChannelManager()`), account loop supervisor |
| `registerTool(factory)` | `tools` | Agent runtime tool set; tool-call dispatch |
| `registerHook(name, handler)` | `hooks` / `typedHooks` | Global hook runner (`hook-runner-global.ts`); fires at lifecycle points |
| `registerProvider(plugin)` | `providers` | Model catalog (`buildModelCatalog()`); agent runtime API call dispatch |
| `registerMemoryRuntime(rt)` | memory runtime slot | Context engine memory retrieval |
| `registerMemoryCorpusSupplement(fn)` | memory corpus list | Retrieval pipeline; appended to retrieval results |
| `registerMemoryPromptSupplement(fn)` | memory prompt list | System prompt builder; injected into agent context |
| `registerMemoryEmbeddingProvider(p)` | embedding backend | Semantic search backend; used for memory indexing and lookup |
| `registerHttpRoute(path, fn, auth)` | http routes | Gateway HTTP layer; matched against inbound HTTP requests |
| `registerGatewayHandler(method, fn)` | gateway handlers | Gateway method dispatch table |
| `registerImageGenerationProvider(p)` | image gen providers | Media generation pipeline |
| `registerMusicGenerationProvider(p)` | music gen providers | Media generation pipeline |
| `registerVideoGenerationProvider(p)` | video gen providers | Media generation pipeline |
| `registerSpeechProvider(p)` | TTS providers | TTS pipeline |
| `registerRealtimeVoiceProvider(p)` | realtime voice providers | Voice session pipeline |
| `registerNodeHostCommand(cmd)` | node host commands | Node host invoke dispatch |
| `registerInteractiveHandler(name, fn)` | interactive handlers | CLI interactive flow |

## Concrete Example: Installing an Anthropic Provider Plugin

This walkthrough traces what happens when a user installs an Anthropic provider plugin from ClaWHub.

**Discovery.** After installation, the plugin directory appears under `~/.openclaw/plugins/anthropic-provider/`. On the next gateway startup (or config reload), `discoverOpenClawPlugins()` finds it and includes it in the plugin record list.

**Manifest load.** `loadPluginManifestRegistry()` reads `openclaw.plugin.json`. The manifest contains:
- `kind: "provider"`
- `modelSupport: { modelPrefixes: ["claude-"] }` — tells the gateway that any model ID starting with `claude-` belongs to this provider
- `autoEnableWhenConfiguredProviders: ["anthropic"]` — the plugin activates automatically when an Anthropic API key is detected
- `providerAuthEnvVars: { anthropic: ["ANTHROPIC_API_KEY"] }` — tells the onboarding wizard which env var to look for

**Activation decision.** `resolveEffectivePluginActivationState()` checks whether an Anthropic API key is present in config. If it is, the `autoEnableWhenConfiguredProviders` trigger fires and the plugin is marked active without the user having to explicitly enable it. The activation source is recorded as `auto-provider`.

**Version check.** `min-host-version.ts` confirms the plugin's declared minimum host version is satisfied by the running gateway. The plugin proceeds.

**Registry assembly.** `createPluginRegistry()` calls `buildPluginApi()` to construct an `OpenClawPluginApi` for the Anthropic plugin. The jiti loader imports the plugin module with `buildPluginLoaderAliasMap()` redirecting `@openclaw/plugin-sdk` imports to the host's copy. The plugin's factory function runs and calls `api.registerProvider(anthropicProviderPlugin)`. The provider is appended to the `providers` array in the registry under construction.

**Active registry swap.** `setActivePluginRegistry()` atomically installs the new registry. `getActivePluginRegistry()` now returns a registry that includes the Anthropic provider.

**Model catalog.** `buildModelCatalog()` calls `augmentModelCatalogWithProviderPlugins()`, which invokes the Anthropic provider's `listModels()`. The returned models (`claude-opus-4-6`, `claude-sonnet-4-6`, etc.) are added to the catalog. Any agent configured with `model: claude-sonnet-4-6` will now resolve to this provider.

**Routing.** When the agent runtime sends a request, the `claude-` prefix in the model ID is matched against `modelPrefixes` in the manifest. The Anthropic provider handles the call. No other provider plugins are consulted.

## Source Evidence

| File | Purpose |
|------|---------|
| `src/plugins/discovery.ts` | `discoverOpenClawPlugins()` — filesystem scan for bundled, user, and workspace plugins |
| `src/plugins/manifest.ts` | `PluginManifest` type, manifest parsing and validation |
| `src/plugins/manifest-registry.ts` | `loadPluginManifestRegistry()` — load all manifests without running plugin code |
| `src/plugins/config-state.ts` | `resolveEffectivePluginActivationState()`, `createPluginActivationSource()` |
| `src/plugins/min-host-version.ts` | Version compatibility gate; skips plugins requiring newer host |
| `src/plugins/registry.ts` | `PluginRegistry` type, `createPluginRegistry()` — registry assembly |
| `src/plugins/runtime.ts` | `setActivePluginRegistry()`, `getActivePluginRegistry()` — atomic registry swap |
| `src/plugins/api-builder.ts` | `buildPluginApi()` — constructs per-plugin `OpenClawPluginApi` instance |
| `src/plugins/loader.ts` | `loadPlugin()` — jiti-based module loading |
| `src/plugins/sdk-alias.ts` | `buildPluginLoaderAliasMap()` — SDK isolation alias map |
| `src/plugins/path-safety.ts` | Path traversal prevention for plugin file loading |
| `src/plugins/hook-runner-global.ts` | Global hook runner; fires registered hooks at lifecycle points |
| `src/agents/model-catalog.ts` | `buildModelCatalog()`, `augmentModelCatalogWithProviderPlugins()` |
| `src/gateway/server-channels.ts` | `createChannelManager()` — account loop supervisor consuming channel registrations |
| `src/channels/plugins/types.plugin.ts` | `ChannelPlugin` type; all adapter interfaces |

## See Also

- [Pluginized Capability Delivery](../concepts/pluginized-capability-delivery.md) — invariants governing the capability delivery model
- [Plugin Platform](../entities/plugin-platform.md) — full entity reference for the plugin platform
- [Provider and Model System](../entities/provider-and-model-system.md) — provider plugin details and model catalog
- [Channel Plugin Adapters](../entities/channel-plugin-adapters.md) — channel adapter type definitions and account loop
- [Inbound Message to Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md) — what happens after a channel plugin delivers a message
- [Channel Binding and Session Identity Flow](../syntheses/channel-binding-and-session-identity-flow.md)
- [Gateway as Control Plane](../concepts/gateway-as-control-plane.md)
