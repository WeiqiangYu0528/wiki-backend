# Provider Agnostic Model Routing

## Overview

OpenCode presents every AI provider through the same `@ai-sdk/*` interface, so the session execution layer never needs to know which vendor it is talking to. More than 20 provider SDKs are bundled — Anthropic, OpenAI, Google, Azure, AWS Bedrock, Mistral, Groq, Cohere, Perplexity, xAI, and many more — and the correct SDK client is selected at runtime from configuration. The model catalog comes from `ModelsDev`, credentials from `Auth`, and post-processing from `ProviderTransform`. A single `fuzzysort` lookup resolves ambiguous model name strings to a canonical `ModelID`.

This design means adding a new provider requires only a new `@ai-sdk/*` package and a matching config entry; no session or tool code changes.

## Mechanism

### Provider registration

Provider definitions live in `provider/provider.ts`. Each provider is identified by a `ProviderID` and has a factory function that receives its merged config object and returns a Vercel AI SDK `Provider` instance. The factories are direct wrappers around the `create*` functions imported from each `@ai-sdk/*` package:

```
createAnthropic, createOpenAI, createAzure, createGoogleGenerativeAI,
createVertex, createVertexAnthropic, createOpenRouter, createXai,
createMistral, createGroq, createDeepInfra, createCerebras,
createCohere, createGateway, createTogetherAI, createPerplexity,
createVercel, createVenice, createGitLab, createAmazonBedrock,
createGitHubCopilotOpenAICompatible, createOpenAICompatible
```

Custom providers declared in `opencode.json` with `type: "openai-compatible"` are handled by `createOpenAICompatible`, making any OpenAI-compatible endpoint a first-class citizen.

### Model catalog and fuzzy matching

`ModelsDev` maintains the canonical model catalog. When a user supplies a model name string (for example `claude-3.5` or `gpt4o`), the system calls `fuzzysort.go()` against the catalog to find the closest match. This means partial, abbreviated, or slightly misspelled model names resolve without requiring an exact match. The resolved `ModelID` is then used for all downstream operations.

### Credential resolution

`Auth` handles per-provider credential lookup. Each provider has a declared auth strategy (API key from environment variable, OAuth flow, device code, etc.). When the provider factory is called, `Auth.resolve(providerID)` runs first and injects credentials into the provider config. For AWS Bedrock, `fromNodeProviderChain()` from the AWS SDK credential chain is used. For Google Vertex, `GoogleAuth` handles application default credentials. This keeps credential logic isolated from model routing logic.

### Config layering

Provider configuration is read from `Config` (the `opencode.json` file) and merged with defaults. The merge uses `mergeDeep` from `remeda`, so a user only needs to specify the fields they want to override. The final merged config object is passed to the provider factory. `mapValues` and `pickBy` from `remeda` are used to filter and transform the provider map before instantiation.

### ProviderTransform

`ProviderTransform` is a post-processing layer applied after the provider client is constructed. It can modify the model call parameters (for example injecting system prompt additions, changing sampling settings, or applying token limits) without the session layer knowing. This is where provider-specific quirks are normalized away.

### Flag-gated experimental models

`Flag` gates access to experimental or beta models. When `Flag.experimentalModels` is set, the model catalog query includes models that are not yet generally available. Without the flag, those models are filtered out of fuzzy matching results. This prevents accidental use of unstable APIs in production without requiring separate provider configurations.

### Concrete routing decision: Copilot Responses API

`shouldUseCopilotResponsesApi(modelID)` illustrates how provider-level routing decisions are expressed. The function checks whether the model ID matches `gpt-(\d+)` and whether the version number is 5 or greater (excluding `gpt-5-mini`). If both conditions hold, the call is routed to the GitHub Copilot Responses API endpoint instead of the standard Chat Completions endpoint. This logic lives entirely within the provider layer; the session and tool layers are unaware of it.

### OPENCODE_PURE bypass

Setting `OPENCODE_PURE=1` (or passing `--pure` on the CLI) disables all external plugin loading. Because provider plugins (such as custom model catalog extensions) are loaded through the plugin system, `OPENCODE_PURE=1` also restricts the available provider set to the bundled implementations only. Internal plugins (Codex, Copilot, GitLab, Poe) are not affected.

## Invariants

1. All model invocations go through the Vercel AI SDK `LanguageModelV3` interface. No session or tool code calls a vendor SDK directly.
2. `fuzzysort` resolution always produces a `ModelID` that exists in the catalog at the time of resolution. If no match is found, `NoSuchModelError` from the `ai` package is thrown.
3. Credentials are resolved before the provider factory is called. A missing credential raises an error at provider construction time, not at the first model call.
4. `ProviderTransform` cannot change the identity of the provider or model; it can only modify call parameters within the bounds of the `LanguageModelV3` interface.
5. Config-level provider overrides (from `opencode.json`) always take precedence over defaults. The merge order is: defaults -> `ModelsDev` catalog -> user config.

## Source Evidence

| File | What it confirms |
| --- | --- |
| `packages/opencode/src/provider/provider.ts` | All `create*` imports, `shouldUseCopilotResponsesApi()`, `fuzzysort` import, `ProviderTransform` import, `Flag` import, `Auth` import |
| `packages/opencode/src/provider/models.ts` | `ModelsDev` catalog; model list and metadata |
| `packages/opencode/src/provider/transform.ts` | `ProviderTransform` post-processing implementation |
| `packages/opencode/src/provider/schema.ts` | `ModelID` and `ProviderID` branded types |
| `packages/opencode/src/auth/index.ts` | Per-provider credential resolution strategies |
| `packages/opencode/src/flag/flag.ts` | `Flag.experimentalModels` gating experimental model visibility |

## See Also

- [Client Server Agent Architecture](client-server-agent-architecture.md)
- [Plugin Driven Extensibility](plugin-driven-extensibility.md)
- [Tool and Agent Composition](tool-and-agent-composition.md)
- [Provider System](../entities/provider-system.md)
- [Provider Tool Plugin Interaction Model](../syntheses/provider-tool-plugin-interaction-model.md)
- [Request to Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
