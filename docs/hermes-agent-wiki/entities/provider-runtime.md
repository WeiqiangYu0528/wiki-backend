# Provider Runtime

## Overview

The provider runtime is the routing layer that turns a user-facing provider or model choice into something Hermes can actually call. Its job is not to run the conversation loop. Its job is to answer a narrower question first:

> given the current request, config, environment, and saved credentials, which provider should Hermes talk to, with which base URL, which API mode, and which credential set?

That resolver matters because Hermes is not tied to one transport. A session might use OpenRouter, a named custom OpenAI-compatible endpoint, native Anthropic, Codex Responses, Copilot, or another API-key provider. Auxiliary work such as compression summaries or vision analysis may use the same runtime or a different one. Fallback may later swap the active provider again after failures.

So this page should be read as a routing-and-failover page. It explains how Hermes picks a runtime, how it keeps credentials scoped to the right endpoint, how auxiliary clients reuse the same decisions, and where the boundary sits between provider setup and the [Agent Loop Runtime](agent-loop-runtime.md).

## Key Types / Key Concepts

| Anchor | Role in the runtime |
| --- | --- |
| `resolve_requested_provider()` in `hermes_cli/runtime_provider.py` | Decides the starting provider request from explicit args, `config.yaml`, then environment fallback. |
| `resolve_runtime_provider()` in `hermes_cli/runtime_provider.py` | Produces the primary runtime bundle: `provider`, `api_mode`, `base_url`, `api_key`, `source`, and provider-specific metadata. |
| `resolve_provider()` in `hermes_cli/auth.py` | Maps aliases and auth rules onto a concrete provider family before runtime resolution continues. |
| `resolve_provider_client()` in `agent/auxiliary_client.py` | Builds concrete clients for auxiliary work and for agent-loop fallback activation. |
| `api_mode` | Transport shape used later by the loop: `chat_completions`, `codex_responses`, or `anthropic_messages`. |
| credential pool | Shared credential store used when a provider has refreshable or multiple runtime credentials. |
| named custom provider | A saved `custom_providers` entry in `config.yaml`, distinct from the generic `provider: custom` path. |
| fallback chain | Agent-loop-owned list of backup `(provider, model)` entries that can be activated after primary runtime failures. |

The important distinction is that `resolve_runtime_provider()` returns routing facts, while `resolve_provider_client()` returns a usable client object. Hermes needs both layers because the main loop and auxiliary calls do not use exactly the same transports.

## Architecture

Provider runtime behavior is split across three collaborating modules.

| Module | Owns | Why it exists |
| --- | --- | --- |
| `hermes_cli/auth.py` | provider registry, aliases, auth strategy selection | Hermes supports many provider families, so provider identity and credential rules need one shared registry. |
| `hermes_cli/runtime_provider.py` | primary runtime resolution for CLI, gateway, cron, and fresh sessions | Converts a requested provider into a safe runtime bundle with the right base URL, key, and `api_mode`. |
| `agent/auxiliary_client.py` | auxiliary routing and concrete client construction | Lets side tasks and fallback reuse the same provider logic without rebuilding auth and transport rules in every caller. |

This split keeps the system honest.

The shells, such as the [CLI Runtime](cli-runtime.md), [Gateway Runtime](gateway-runtime.md), cron entrypoints, and ACP sessions, can decide which provider or model to request. But they do not each invent their own credential lookup rules. They all come back to the same resolver.

The agent loop depends on this setup, but it does not own it. Once the runtime resolver has produced a provider, base URL, key, and `api_mode`, the loop can format messages correctly, stream responses, retry, compress, or fall back. That later execution logic belongs to [Agent Loop Runtime](agent-loop-runtime.md), not to the provider runtime itself.

## Runtime Behavior

The easiest way to understand this subsystem is to follow the routing flow in order.

### 1. Hermes resolves the requested provider first

`resolve_requested_provider()` applies a stable precedence rule:

1. explicit runtime request
2. saved `config.yaml` provider
3. `HERMES_INFERENCE_PROVIDER`
4. `auto`

That ordering is deliberate. Hermes treats the saved model/provider choice as the normal source of truth, so an old shell export does not silently override the provider the user last selected through Hermes commands.

Model configuration is loaded alongside that provider request. `_get_model_config()` also normalizes a few cases that matter later:

- `model.model` can stand in for `model.default`
- local endpoints can auto-detect a model name when only one model is loaded
- persisted `api_mode` is parsed once and then applied only when it still matches the provider family

In other words, Hermes usually treats the model slug as an explicit or persisted choice, while the provider runtime is responsible for pairing that model with the correct transport and credential path. It only fills in a model automatically in narrower cases, such as single-model local endpoints or provider-specific auxiliary defaults.

That last point is easy to miss. Hermes explicitly guards against stale transport settings leaking across model switches. A saved `api_mode` from one provider should not accidentally force a different provider into the wrong transport.

### 2. The runtime resolver turns that request into a safe bundle

`resolve_runtime_provider()` is the main router for primary sessions. It does more than pick a provider name.

It resolves, in order:

- named custom providers from `custom_providers`
- explicit runtime overrides such as a direct `base_url` or `api_key`
- credential-pool entries for providers with pooled or refreshable credentials
- provider-specific runtime credentials such as Nous, Codex, Anthropic, Copilot ACP, or API-key providers
- OpenRouter or generic custom OpenAI-compatible routing as the fallback path

The output is a runtime dict, not yet the full conversation client. That dict includes:

- `provider`
- `api_mode`
- `base_url`
- `api_key`
- `source`
- provider-specific fields such as expiry, refresh time, external-process command data, or the selected credential pool

This layer is where Hermes enforces endpoint hygiene.

For example, `_resolve_openrouter_runtime()` distinguishes between real OpenRouter routing and a user-selected custom OpenAI-compatible endpoint. That prevents Hermes from sending the wrong credential to the wrong host:

- OpenRouter URLs prefer `OPENROUTER_API_KEY`
- custom endpoints prefer `OPENAI_API_KEY` or a saved custom-provider key
- local endpoints can use the placeholder `no-key-required` because the OpenAI SDK still expects a non-empty key string

The same safety rule appears in the native Anthropic path. Hermes only applies a configured Anthropic base URL when the configured provider is actually `anthropic`. That stops a stale non-Anthropic base URL from leaking into native Messages API calls.

### 3. Hermes chooses an API mode before the loop starts

Provider resolution is also where Hermes decides which transport family the rest of the runtime must honor.

| API mode | Typical routing cases | Why it matters later |
| --- | --- | --- |
| `chat_completions` | OpenRouter, most custom OpenAI-compatible endpoints, most API-key providers | The loop formats normal chat-completions requests and tool calls. |
| `codex_responses` | `openai-codex`, direct `api.openai.com` GPT-5-style endpoints | The loop must use the Responses API path instead of pretending the backend is ordinary chat completions. |
| `anthropic_messages` | native Anthropic, Anthropic-compatible `/anthropic` endpoints | The loop must translate through the Anthropic adapter and use native message semantics. |

Some of these decisions come from provider identity. Others come from URL heuristics:

- direct `api.openai.com` URLs force `codex_responses`
- endpoints ending in `/anthropic` can force `anthropic_messages`
- OpenCode Zen and Go can compute mode from the selected model, then strip trailing `/v1` when the Anthropic SDK would otherwise duplicate the path

This is one of the clearest boundaries in Hermes. Provider runtime decides *which* transport to use. The agent loop later decides *how* to format and execute calls for that transport.

### 4. Auxiliary tasks reuse the same routing logic, but with their own policy

`agent/auxiliary_client.py` exists because side-channel work has different needs from the main conversation. Compression summaries, session-search summarization, memory flushes, vision analysis, and web extraction do not always need the same model as the primary turn.

`resolve_provider_client()` is the central router here. It accepts a provider and optional model, then returns a client that always exposes `.chat.completions.create()`, even when the real backend is not a chat-completions API:

- Codex is wrapped by a Responses-to-chat adapter
- Anthropic is wrapped by a Messages-to-chat adapter
- async wrappers preserve the same interface for background tasks

This gives Hermes one stable auxiliary calling shape even though the backends differ.

Auxiliary routing also has its own selection rules:

- `provider="main"` resolves to the user's actual main provider, not a hard-coded aggregator
- `provider="auto"` first prefers the main provider when it is a non-aggregator provider, then falls through an ordered chain
- task-specific overrides can force provider, model, base URL, or API key for one auxiliary task
- payment or credit exhaustion can trigger an auxiliary-only fallback across the auto-detection chain

That means auxiliary routing is related to the primary runtime, but it is not identical to it. It shares the same provider knowledge while still allowing cheaper or more specialized models for non-primary work.

### 5. Fallback activation belongs to the agent loop, but it depends on this runtime

Fallback is the main place where readers often blur subsystem boundaries.

The provider runtime does **not** decide when to fall back. That decision belongs to `AIAgent` inside `run_agent.py`. The loop triggers `_try_activate_fallback()` after certain invalid responses, non-retryable errors, or exhausted retries.

What the provider runtime contributes is the machinery to make fallback safe and consistent.

When `_try_activate_fallback()` runs, it:

1. pulls the next configured `(provider, model)` from the fallback chain
2. asks `resolve_provider_client()` to build the replacement client, including custom endpoint hints when present
3. re-derives `api_mode` from provider identity and base URL
4. swaps the active `model`, `provider`, `base_url`, `api_mode`, client, and client kwargs in place
5. rebuilds native Anthropic state when the new fallback uses `anthropic_messages`
6. re-evaluates prompt-caching rules for the new provider/model
7. refreshes context-compressor limits using `agent/model_metadata.py` so the fallback does not inherit the primary model's context window by mistake

That last step is a real runtime constraint, not a detail. A fallback model may have a much smaller context window than the primary model. If Hermes kept the old limits, the fallback could immediately overflow on the next request.

The loop also restores the primary runtime at the start of the next turn, so fallback is turn-scoped in long-lived sessions instead of permanently pinning the conversation to the backup provider.

## Variants, Boundaries, and Runtime Constraints

The cleanest way to avoid confusion is to separate provider setup from turn execution.

| Concern | Provider runtime owns | Agent loop owns |
| --- | --- | --- |
| provider selection | resolving requested provider, aliases, saved custom providers, credential pools, base URL choice | deciding when a turn should continue, retry, or fail |
| transport choice | selecting `api_mode` and building the right client family | formatting messages and tool calls for the selected transport |
| credentials | choosing the right secret for the resolved endpoint and preventing key leakage | refreshing, retrying, or replacing the active runtime after call failures |
| auxiliary work | routing side tasks to `main`, `auto`, or task-specific providers | deciding when to invoke compression, memory flush, or other auxiliary tasks |
| fallback | supplying the routing logic used by fallback activation | deciding when to activate fallback and swapping the live runtime during a turn |

Several runtime constraints follow from those boundaries:

- Fallback is not universal. The main loop supports it, but auxiliary tasks use their own routing chain, cron runs with a fixed provider, and subagent delegation does not inherit the parent's fallback chain.
- Custom endpoints are first-class, but they are treated carefully. Hermes distinguishes a real saved custom endpoint from the OpenRouter fallback path, so saved local or third-party endpoints keep working without pretending they are OpenRouter.
- `api_mode` is sticky only when it is still valid. Hermes rejects stale persisted modes when the provider family has changed.
- Base URL choice has downstream effects. It changes transport mode, credential selection, and even context-length estimation through `agent/model_metadata.py`.
- Provider runtime does not own prompt content, tool visibility, or session persistence. Those belong to [Prompt Assembly System](prompt-assembly-system.md), [Tool Registry and Dispatch](tool-registry-and-dispatch.md), and [Session Storage](session-storage.md).

## Source Files

| File | Why it matters for this page |
| --- | --- |
| `hermes-agent/hermes_cli/runtime_provider.py` | Primary runtime resolver for provider selection, custom endpoints, credential pools, and `api_mode` choice. |
| `hermes-agent/hermes_cli/auth.py` | Provider registry, alias resolution, and provider-specific credential lookup rules. |
| `hermes-agent/agent/auxiliary_client.py` | Auxiliary routing, transport adapters for Codex and Anthropic, and the shared client builder used by fallback activation. |
| `hermes-agent/agent/model_metadata.py` | Context-length and provider-from-URL utilities used when fallback changes the active model or endpoint. |
| `hermes-agent/run_agent.py` | Owns `_try_activate_fallback()` and `_restore_primary_runtime()`, which show where provider routing ends and turn execution begins. |
| `hermes-agent/website/docs/developer-guide/provider-runtime.md` | Maintainer-facing description of resolution precedence, API modes, auxiliary routing, and supported fallback behavior. |

## See Also

- [Agent Loop Runtime](agent-loop-runtime.md)
- [Prompt Assembly System](prompt-assembly-system.md)
- [Session Storage](session-storage.md)
- [CLI Runtime](cli-runtime.md)
- [Gateway Runtime](gateway-runtime.md)
- [Tool Registry and Dispatch](tool-registry-and-dispatch.md)
- [CLI to Agent Loop Composition](../syntheses/cli-to-agent-loop-composition.md)
