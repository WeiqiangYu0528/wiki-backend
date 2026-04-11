# Provider and Model System

## Overview

The provider and model system manages which AI backends OpenClaw can route requests to, how those backends authenticate, and which models are available per agent or session. Providers are delivered as plugins; the provider runtime activates them, manages their auth state, and exposes them to the agent runtime for model selection. The model catalog (`src/agents/model-catalog.ts`) aggregates available models from all active providers and the Pi SDK's model registry.

Provider selection is not a static config lookup. At runtime, `resolveAuthChoiceModelSelectionPolicy()` (called during onboarding and config updates) chooses a preferred provider from the set of configured auth choices, consulting each provider plugin's `providerAuthChoices` manifest metadata before loading any plugin runtime. This enables cheap provider routing (e.g., recognizing a Claude API key format) without importing heavy provider SDKs.

## Key Types

```ts
// src/agents/model-catalog.ts
export type ModelInputType = "text" | "image" | "document";

export type ModelCatalogEntry = {
  id: string;
  name: string;
  provider: string;
  contextWindow?: number;
  reasoning?: boolean;       // supports extended thinking
  input?: ModelInputType[];
};
```

```ts
// src/plugins/manifest.ts
export type PluginManifestModelSupport = {
  modelPrefixes?: string[];   // cheap prefix match: "claude-", "gpt-"
  modelPatterns?: string[];   // regex for complex model ID patterns
};
```

Provider manifests also carry:
- `providerAuthEnvVars` — maps provider IDs to env var names for API key detection
- `providerAuthChoices` — structured auth option descriptions for the wizard
- `autoEnableWhenConfiguredProviders` — auto-activates plugin when trigger provider appears in config

## Architecture

### Manifest-Level Routing

Before any provider plugin is loaded, the manifest registry provides cheap metadata for model ID resolution:
- `modelPrefixes` — e.g., `["claude-"]` lets OpenClaw route `claude-sonnet-4-6` to the Anthropic plugin without booting it.
- `modelPatterns` — regex patterns for model IDs that don't fit a simple prefix.

This enables the runtime to identify which provider owns a model shorthand (e.g., `gpt-5.4`, `claude-opus-4-6`) at routing time, before incurring plugin startup cost.

### Model Catalog

`buildModelCatalog()` in `src/agents/model-catalog.ts`:
1. Calls `augmentModelCatalogWithProviderPlugins()` — each active provider plugin's `listModels()` contributes entries.
2. Overlays models from `models.json` in the agent directory (user-defined overrides).
3. Filters via model suppression (`src/agents/model-suppression.runtime.ts`) to hide models not applicable for the current configuration.

The catalog is built lazily (`modelCatalogPromise`) and shared across the gateway session. Non-Pi-native providers (`deepseek`, `kilocode`, `ollama`) use a separate code path tracked in `NON_PI_NATIVE_MODEL_PROVIDERS`.

### Auth System

Provider authentication is layered:

| Auth Method | Source | Notes |
|-------------|--------|-------|
| API key (env) | `providerAuthEnvVars` manifest | Detected without loading plugin |
| API key (keychain) | `src/agents/auth-profiles.ts` | Named profile, stored in OS keychain |
| OAuth | `src/plugins/provider-oauth-flow.ts` | Browser-based flow; tokens in secrets store |
| Key rotation | `src/agents/api-key-rotation.ts` | Key pool cycling for high-throughput |
| Auth profiles | `src/agents/auth-profiles.ts` | Named multi-provider configurations |

`src/plugins/provider-auth-choice.ts` manages which auth option was selected and persists that preference for future sessions.

### Provider Discovery

`discoverProviders()` in `src/plugins/provider-discovery.ts` scans for provider plugins. Providers with `enabledByDefault: true` activate without explicit config. Providers with `autoEnableWhenConfiguredProviders` auto-enable when their trigger providers appear in auth config.

### Model Selection at Runtime

When the agent runtime constructs a request:
1. `resolveSessionAgentIds()` identifies the agent.
2. The agent's `model` config field specifies a model ID or shorthand (e.g., `claude-sonnet-4-6`).
3. The provider is resolved using manifest `modelPrefixes` or the explicit `provider` field.
4. The provider plugin's `resolveModel()` produces a fully-qualified model reference.
5. `resolveAgentModelFallbackValues()` applies configured defaults when the model field is absent.

### Thinking and Reasoning

Models marked `reasoning: true` in the catalog support extended thinking. Agents with `thinkingDefault: true` or `reasoningDefault: true` in config enable model-side reasoning. `src/agents/provider-request-config.ts` attaches thinking parameters to the API request payload.

## Source Files

| File | Purpose |
|------|---------|
| `src/agents/model-catalog.ts` | `ModelCatalogEntry`, `buildModelCatalog()`, provider augmentation |
| `src/agents/model-suppression.runtime.ts` | Hides non-applicable models from catalog |
| `src/agents/api-key-rotation.ts` | Key pool rotation for high-throughput configurations |
| `src/agents/auth-profiles.ts` | Named auth profile management |
| `src/agents/provider-request-config.ts` | Builds provider-level request params including thinking |
| `src/plugins/provider-runtime.ts` | Provider plugin activation; `listProviders()` |
| `src/plugins/provider-discovery.ts` | `discoverProviders()` — scan and activate provider plugins |
| `src/plugins/provider-auth-choice.ts` | Auth choice selection and preference persistence |
| `src/plugins/provider-auth-choices.ts` | `ProviderAuthChoice` type; structured auth option definitions |
| `src/plugins/provider-model-defaults.ts` | Default model selection helpers |
| `src/plugins/provider-oauth-flow.ts` | OAuth browser flow for provider authentication |
| `src/plugins/manifest.ts` | `PluginManifestModelSupport`, `providerAuthEnvVars`, manifest metadata |

## See Also

- [Plugin Platform](plugin-platform.md) — providers are registered as plugins
- [Agent Runtime](agent-runtime.md) — consumes model catalog and provider auth for API calls
- [CLI and Onboarding](cli-and-onboarding.md) — wizard uses auth choices during setup
- [Tool-Augmented Agent Execution](../concepts/tool-augmented-agent-execution.md)
- [Extension to Runtime Capability Flow](../syntheses/extension-to-runtime-capability-flow.md)
