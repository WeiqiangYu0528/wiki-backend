# Provider System

## Overview

The Provider System is OpenCode's provider-agnostic model layer. It bridges more than 20 AI SDK backends behind a single execution contract, resolves credentials from multiple sources, applies per-provider customization logic, and exposes a unified `Provider.Model` abstraction to the rest of the runtime. Every AI call that OpenCode makes passes through this subsystem.

The system is organized around a central orchestrator (`provider.ts`) backed by a ring of support modules that handle model metadata (`models.ts`), identifier schemas (`schema.ts`), and response post-processing (`transform.ts`). Provider and model state is scoped to an `Instance`, so different project directories can resolve different credentials and different model sets simultaneously.

## Key Types

### `ProviderID` and `ModelID` (`provider/schema.ts`)

Both are Effect `Schema.String` branded types with Zod companions for HTTP validation.

- `ProviderID` — branded string identifying a provider (e.g., `"anthropic"`, `"openai"`, `"github-copilot"`). Well-known values are exposed as static members: `ProviderID.anthropic`, `ProviderID.openrouter`, `ProviderID.gitlab`, etc.
- `ModelID` — branded string identifying a specific model within a provider. Created via `ModelID.make(id)`.

### `ModelsDev.Model` (`provider/models.ts`)

Zod schema representing one entry in the `models.dev` catalog. Key fields:

| Field | Type | Meaning |
|---|---|---|
| `id` | `string` | Canonical model ID |
| `cost` | `{ input, output, cache_read?, cache_write? }` | Token pricing in USD per million |
| `limit` | `{ context, input?, output }` | Token window sizes |
| `modalities` | `{ input[], output[] }` | Supported media types (`text`, `image`, `audio`, `video`, `pdf`) |
| `reasoning` | `boolean` | Whether the model produces chain-of-thought reasoning |
| `tool_call` | `boolean` | Function/tool calling support |
| `interleaved` | `true \| { field }` | Interleaved thinking output format |
| `experimental` | `boolean` | Gated behind `Flag.experimentalModels` |
| `status` | `"alpha" \| "beta" \| "deprecated"` | Model maturity |

### `ModelsDev.Provider` (`provider/models.ts`)

Catalog entry for one provider: `id`, `name`, `npm` package name, `env` (list of env var names used for auth), and a `models` record.

### `Provider.Info` and `Provider.Model` (`provider/provider.ts`)

Runtime provider descriptor. Built from the `ModelsDev.Provider` shape, merged with config overrides and auth state. Each provider carries the resolved SDK factory, the set of available models, and environment variable mappings.

### `BundledSDK` (`provider/provider.ts`)

Internal interface: `{ languageModel(modelId: string): LanguageModelV3 }`. Every bundled factory must satisfy this shape.

## Architecture

### Bundled Provider Registry

`BUNDLED_PROVIDERS` is a static record mapping npm package names to factory functions that are imported at build time rather than loaded dynamically. This eliminates network fetches for common providers:

```
"@ai-sdk/anthropic"            → createAnthropic
"@ai-sdk/openai"               → createOpenAI
"@ai-sdk/google"               → createGoogleGenerativeAI
"@ai-sdk/google-vertex"        → createVertex
"@ai-sdk/google-vertex/anthropic" → createVertexAnthropic
"@ai-sdk/azure"                → createAzure
"@ai-sdk/amazon-bedrock"       → createAmazonBedrock
"@ai-sdk/xai"                  → createXai
"@ai-sdk/mistral"              → createMistral
"@ai-sdk/groq"                 → createGroq
"@ai-sdk/deepinfra"            → createDeepInfra
"@ai-sdk/cerebras"             → createCerebras
"@ai-sdk/cohere"               → createCohere
"@ai-sdk/gateway"              → createGateway
"@ai-sdk/togetherai"           → createTogetherAI
"@ai-sdk/perplexity"           → createPerplexity
"@ai-sdk/vercel"               → createVercel
"@ai-sdk/openai-compatible"    → createOpenAICompatible
"@openrouter/ai-sdk-provider"  → createOpenRouter
"gitlab-ai-provider"           → createGitLab
"venice-ai-sdk-provider"       → createVenice
"@ai-sdk/github-copilot"       → createGitHubCopilotOpenAICompatible (custom copilot adapter)
```

Providers not in this list (e.g., user-installed plugins) are loaded via `Npm` at runtime.

### `ModelsDev` Catalog (`provider/models.ts`)

Model metadata is sourced from `https://models.dev` (configurable via `Flag.OPENCODE_MODELS_URL`). The catalog is cached under `Global.Path.cache/models.json` with a 5-minute TTL. Freshness is checked by comparing file `mtime` to `Date.now()`. A file-lock (`Flock`) prevents concurrent refreshes.

The catalog drives:
- Default model lists shown to the user
- Token cost estimates
- Capability flags (`reasoning`, `tool_call`, `attachment`)
- Experimental model gating via `Flag.experimentalModels`

### Fuzzy Model Search

`fuzzysort` is used to match user-supplied model name strings against the full model catalog. This allows partial or misspelled model names to resolve to the correct `ModelID` rather than failing with a hard error.

### Auth Integration (`Auth`)

Credentials are resolved in a defined precedence order per provider:

1. Environment variables listed in `provider.env` (checked via `Env.all()`)
2. Persisted auth from `Auth.get(providerID)` (stored credentials, e.g., OAuth tokens, API keys)
3. Explicit `apiKey` in the project `Config` under `provider.<id>.options.apiKey`

The `custom()` function in `provider.ts` encodes per-provider credential logic. For example, the `opencode` provider checks all three sources and, if none provide a paid key, removes paid models from the model list so only free models remain visible.

### Per-Provider Custom Loaders

`custom()` returns a `Record<string, CustomLoader>` with special handling for:

- **`anthropic`** — injects `anthropic-beta` headers enabling interleaved thinking and fine-grained tool streaming
- **`openai`** — uses `sdk.responses()` (Responses API) instead of `sdk.chat()`
- **`xai`** — same as OpenAI: routes to `sdk.responses()`
- **`github-copilot`** — calls `shouldUseCopilotResponsesApi(modelID)` to decide between `sdk.responses()` and `sdk.chat()`
- **`azure`** — reads `AZURE_RESOURCE_NAME` from config or env; routes between `sdk.responses()` and `sdk.chat()` based on `useCompletionUrls` option
- **`amazon-bedrock`** — resolves region and profile from config then env, sets up `fromNodeProviderChain` AWS credentials, handles bearer token auth
- **`google-vertex`** — uses `GoogleAuth` for service account resolution

### `shouldUseCopilotResponsesApi(modelID)` (`provider/provider.ts`)

Routes GitHub Copilot model calls through the newer Responses API instead of the Chat Completions API for GPT-5 and above (excluding `gpt-5-mini`):

```
/^gpt-(\d+)/.exec(modelID)  →  number >= 5 and not "gpt-5-mini"  →  use responses API
```

### `wrapSSE(res, ms, ctl)` (`provider/provider.ts`)

Wraps an SSE `Response` with a per-chunk timeout guard. If no chunk arrives within `ms` milliseconds:
1. The `AbortController` `ctl` is aborted with a timeout error.
2. The underlying reader is cancelled.
3. The downstream ReadableStream is closed with an error.

Returns the original response unchanged if: `ms <= 0`, the response has no body, or the content-type is not `text/event-stream`.

### `ProviderTransform` Post-processing (`provider/transform.ts`)

Applied after model responses are received. Responsibilities include:

- **SDK key mapping** — translates npm package names to the key the AI SDK expects for `providerOptions` (e.g., `"@ai-sdk/anthropic"` → `"anthropic"`)
- **Message normalization** — for Anthropic and Amazon Bedrock, filters empty string messages and removes empty text/reasoning parts from array content (the Anthropic API rejects empty content)
- **Output token cap** — enforces `OUTPUT_TOKEN_MAX` (default 32,000, overridable via `Flag.OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX`)
- **MIME-to-modality conversion** — maps `image/*`, `audio/*`, `video/*`, `application/pdf` to the modality enum used in the `ModelsDev.Model` schema

### `Flag.experimentalModels` Gate

When `Flag.experimentalModels` is false (the default), models with `experimental: true` in the `ModelsDev` catalog are excluded from the model list presented to users. Setting the flag exposes pre-release or preview models.

### `Instance` and `InstanceState` Scoping

Provider state is per-instance. `Instance.provide()` establishes the effect context for a project directory, and `InstanceState` carries provider-level mutable state (e.g., resolved credentials, loaded SDKs) within that scope. This means two concurrent project sessions can use different providers, different credentials, and different model subsets without interference.

### Config Integration

Provider config is read from `Config.Info` under `provider.<id>`:
- `options` — passed directly to the SDK factory (e.g., `apiKey`, `baseURL`, `region`, `resourceName`)
- Per-model overrides via `variants`

## Runtime Behavior

1. On first model access, `ModelsDev` loads (or refreshes) the catalog from the cache or `models.dev`.
2. `Provider.list()` merges catalog providers with config overrides and resolves which providers are enabled.
3. For each provider, the credential resolution chain runs (env → Auth store → Config).
4. The appropriate bundled factory (or npm-loaded factory) is called with resolved options to produce a provider SDK instance.
5. When a model is requested, the per-provider `getModel` logic decides which API surface to use (`languageModel`, `chat`, or `responses`).
6. Outgoing SSE streams are wrapped with `wrapSSE` if a stall timeout is configured.
7. `ProviderTransform` normalizes messages and applies provider-specific `providerOptions` before the request leaves the process.
8. `fuzzysort` is available for interactive model search (TUI, CLI completions).

## Source Files

| File | Purpose |
|---|---|
| `packages/opencode/src/provider/provider.ts` | Central orchestrator: bundled provider registry, credential resolution, model loading, SSE timeout, custom per-provider logic |
| `packages/opencode/src/provider/schema.ts` | `ProviderID` and `ModelID` branded types with Zod companions and well-known constants |
| `packages/opencode/src/provider/models.ts` | `ModelsDev` catalog: Zod schemas, cache management, TTL refresh, file locking |
| `packages/opencode/src/provider/transform.ts` | `ProviderTransform`: message normalization, SDK key mapping, output token cap, modality conversion |
| `packages/opencode/src/provider/sdk/copilot.ts` | Custom GitHub Copilot OpenAI-compatible adapter factory |

## See Also

- [Tool System](tool-system.md)
- [MCP and ACP Integration](mcp-and-acp-integration.md)
- [Provider Agnostic Model Routing](../concepts/provider-agnostic-model-routing.md)
- [Provider Tool Plugin Interaction Model](../syntheses/provider-tool-plugin-interaction-model.md)
- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [Request To Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
