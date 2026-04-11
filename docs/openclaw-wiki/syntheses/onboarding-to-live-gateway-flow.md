# Onboarding to Live Gateway Flow

## Overview

This synthesis traces the complete path from a freshly installed OpenClaw binary to a live, message-ready local assistant. It spans two distinct phases: **Phase 1 (Setup)**, where the CLI wizard collects credentials and writes configuration, and **Phase 2 (Gateway Startup)**, where the gateway process boots, activates plugins, wires authentication surfaces, and starts channel account loops.

Understanding this path end-to-end matters because failures at any stage produce very different symptoms. A missing API key surfaces during Phase 1 as a wizard prompt failure. A misconfigured plugin surfaces during Phase 2 as a registry activation error. A missing channel credential surfaces only when the channel account loop attempts its first connection. By following the sequence below, a developer can locate the exact subsystem responsible for a given failure rather than searching the full codebase.

This is also where the local-first design becomes structurally visible. No configuration is stored remotely; no credential transits an OpenClaw server. Every durable artifact — `openclaw.yml`, keychain entries, state directories — lives on the user's own machine and is managed by the local process.

## Systems Involved

| System | Contribution |
|--------|-------------|
| [CLI and Onboarding](../entities/cli-and-onboarding.md) | Entry point, route dispatch, setup wizard, config guard |
| [Gateway Control Plane](../entities/gateway-control-plane.md) | Gateway startup sequence, auth evaluation, channel management |
| [Plugin Platform](../entities/plugin-platform.md) | Plugin discovery, manifest loading, activation, registry assembly |
| [Local-First Personal Assistant Architecture](../concepts/local-first-personal-assistant-architecture.md) | Design rationale: credentials in keychain, config on filesystem, no cloud relay |
| [Auth and Approval Boundaries](../concepts/auth-and-approval-boundaries.md) | Gateway auth surfaces, secrets snapshot, rate limiting |

## Phase 1: Setup (CLI Wizard)

### Entry and Route Dispatch

When the user runs `openclaw setup` (or `openclaw` with no recognized subcommand on first run), the process begins in `src/entry.ts`. The startup sequence is:

1. `normalizeEnv()` — sets runtime environment variables and paths.
2. `ensureOpenClawExecMarkerOnProcess()` — marks the process so child processes can detect they are running inside an OpenClaw invocation.
3. `installProcessWarningFilter()` — suppresses noisy Node.js runtime warnings.
4. `enableCompileCache()` — activates V8 code caching on Node.js 22+ for faster subsequent starts.
5. `buildCliRespawnPlan()` — checks whether a container or privilege boundary requires a process respawn before continuing.
6. `tryRouteCli(argv)` — fast-path dispatch.

`tryRouteCli()` in `src/cli/route.ts` is the critical branch point. It checks whether the invoked command path matches a registered route descriptor before building the full Commander program:

```ts
export async function tryRouteCli(argv: string[]): Promise<boolean> {
  if (hasHelpOrVersion(argv)) return false;
  const path = getCommandPathWithRootOptions(argv, 2);
  const route = findRoutedCommand(path);
  if (!route) return false;
  await prepareRoutedCommand({ argv, commandPath: path, loadPlugins: route.loadPlugins });
  return route.run(argv);
}
```

Routes that declare `loadPlugins: false` (such as `gateway status`) skip plugin registry loading entirely, keeping startup latency minimal. The setup wizard route does not require the plugin registry for its core flow — it reads only plugin manifests, not plugin code — so it can proceed without a full registry load. If no route matches, control falls back to `buildProgram()` and the full Commander program.

### The Setup Wizard

`runSetupWizard()` in `src/wizard/setup.ts` drives a `WizardFlow` via `WizardPrompter`. The wizard proceeds through these steps:

1. **Config check** — detects whether `openclaw.yml` already exists. If it does, the wizard offers to reset it or augment it with new providers or channels. This prevents accidental re-initialization of a working install.

2. **Provider selection** — presents a list of available AI providers. The wizard reads provider options directly from plugin manifests (`providerAuthChoices` and `providerAuthEnvVars` fields in `PluginManifest`) without loading any plugin code. This is intentional: manifests are cheap to parse; booting plugin runtimes is not.

   ```ts
   // From src/plugins/manifest.ts
   providerAuthEnvVars?: Record<string, string[]>;
   providerAuthChoices?: PluginManifestProviderAuthChoice[];
   ```

   `providerAuthChoices` describes the human-readable options the wizard presents (for example, "Enter API key", "Use environment variable", "Authenticate via OAuth"). `providerAuthEnvVars` maps provider IDs to the environment variable names the plugin expects, so the wizard can tell the user which variable to set as an alternative to keychain storage.

3. **API key collection** — for the chosen provider, the wizard prompts for an API key or OAuth credential. Input is collected through `WizardPrompter`, which abstracts the terminal prompt interface. `WizardCancelledError` is thrown on Ctrl-C, ensuring the wizard exits cleanly without writing partial config.

4. **Keychain storage** — the collected credential is written to the OS keychain via `src/secrets/`. The keychain entry is keyed by provider ID. The credential is never written to `openclaw.yml` — that file holds only non-sensitive configuration. This is a hard invariant in the local-first design.

5. **Port and optional channel setup** — the wizard resolves the gateway port and writes it to config. The user can optionally configure a first channel (e.g., Telegram, Slack) during setup; channel credentials also go to the keychain, not the config file.

6. **Config write** — `writeConfigFile()` serializes the completed configuration to `openclaw.yml` in the user's home directory.

### Files Created After Phase 1

After a successful wizard run, the following filesystem artifacts exist:

| Path | Contents |
|------|----------|
| `openclaw.yml` | Main configuration: agents, channels, bindings, plugins, model preferences, gateway port |
| `~/.openclaw/state/` | State directory, created on first run; holds SQLite databases, session transcripts, exec approval records |
| `~/.openclaw/skills/` | User's personal skill files (Markdown); populated on first run or by `skills install` |
| OS keychain | Provider API keys and channel OAuth tokens, keyed by provider/channel ID |

No credentials appear in `openclaw.yml`. The wizard writes only structural configuration there.

## Phase 2: Gateway Startup

### Starting the Server

`openclaw gateway start` dispatches to `startGatewayServer()` in `src/gateway/server.impl.ts`. This is the composition root for the entire gateway. It runs a sequential 7-step startup:

1. **Config load and validation** — `loadConfig()` reads and validates `openclaw.yml`. If the file is absent, malformed, or fails schema validation, startup aborts and reports a structured error. This is the same schema checked by `ensureConfigReady()` in the CLI config guard.

2. **Auth surface resolution** — `evaluateGatewayAuthSurfaceStates()` computes the effective authentication policy for every HTTP and WebSocket path, using `GATEWAY_AUTH_SURFACE_PATHS` as the policy definition. The result determines which paths require bearer tokens, which are open to loopback clients, and which require Tailscale identity. Rate limiters (`createAuthRateLimiter()`) are also constructed here, constraining brute-force credential attempts.

3. **Plugin discovery and startup set** — `resolveGatewayStartupPluginIds()` determines which plugins load eagerly at startup versus on-demand. This distinction keeps startup fast: heavy plugins that are only needed for specific capabilities can be deferred until first use.

4. **Plugin activation** — `createPluginRuntime()` drives the full plugin pipeline:
   - `discoverOpenClawPlugins()` scans bundled plugins, `~/.openclaw/plugins/`, and workspace-local plugins.
   - `loadPluginManifestRegistry()` loads and validates every discovered `openclaw.plugin.json` manifest.
   - `resolveEffectivePluginActivationState()` runs the priority chain: hard-enables and hard-disables from config take precedence; auto-enable triggers (configured provider, model prefix, `enabledByDefault: true`) come next; user toggles from `openclaw.yml` apply last.
   - `createPluginRegistry()` calls each active plugin's factory function with a constructed `OpenClawPluginApi` instance, collecting registrations for channels, providers, tools, hooks, memory supplements, and HTTP routes.
   - `setActivePluginRegistry()` atomically installs the assembled registry as the live runtime state. The registry is immutable once set; hot-reload rebuilds and swaps it without disrupting in-flight requests.

5. **Channel account loops** — `createChannelManager()` in `src/gateway/server-channels.ts` enumerates all enabled channel accounts from the active plugin registry and starts a supervised per-account loop for each. Each loop calls the channel plugin's `gateway.startAccount(ctx)` adapter — a long-running async function that receives inbound messages and feeds them into the reply dispatch pipeline. Crashes restart automatically via a backoff policy (`initialMs: 5_000`, `maxMs: 5 * 60_000`, `factor: 2`) up to ten attempts.

6. **MCP loopback server** — `startMcpLoopbackServer()` starts the Model Context Protocol integration endpoint, enabling tool use by the agent runtime.

7. **WebSocket handler attachment** — `attachGatewayWsHandlers()` opens the gateway's WebSocket surface and `server-methods.ts` registers all control-plane method handlers. The gateway is now reachable.

### Secrets Snapshot

Concurrent with or immediately after plugin activation, `activateSecretsRuntimeSnapshot()` loads all keychain entries into a runtime snapshot in memory. This single load avoids repeated OS keychain I/O on every provider API call or channel operation. Provider credentials are resolved at request time from this snapshot via `resolveCommandSecretsFromActiveRuntimeSnapshot()`.

## First Message

After Phase 2 completes, the assistant is reachable. The path for the first inbound message is:

1. A message arrives on a configured channel (for example, a Telegram message).
2. The channel account loop for that account, started in step 5 above, receives the message via the plugin's `startAccount` adapter.
3. The adapter emits the message into the gateway's reply dispatch pipeline.
4. The gateway routes the message to the appropriate session, creating a new session if none exists for the sender.
5. The agent runtime receives the session input, resolves the active provider from the plugin registry, loads the API key from the secrets snapshot, and dispatches the request to the AI provider directly — no OpenClaw relay.
6. The agent reply is emitted back through the channel plugin to the channel.

The critical dependency for this path is that Phase 2 must have completed successfully: the plugin registry must be active (so the channel plugin is registered), the secrets snapshot must be loaded (so the provider key is available), and the channel account loop must be running (so inbound messages are received).

## Config Guard and Prerequisites

Before most CLI commands run — including `gateway start` — `ensureConfigReady()` performs pre-flight validation:

- **Schema check** — `openclaw.yml` must parse and conform to the expected schema. Unknown top-level keys are rejected.
- **Doctor check** — checks for missing binaries, port conflicts, and plugin compatibility issues. Results are formatted by `formatConfigIssueLines()` and emitted to stderr.
- **Missing provider config** — if no provider is configured or no API key is findable (keychain or environment variable), the doctor emits a warning identifying which `providerAuthEnvVars` are unset.

If the config guard fails with a blocking error, the command exits before attempting gateway startup. This prevents the gateway from starting in a state where it would immediately fail to handle any agent request.

The guard is bypassed for commands that declare `skipConfigGuard: true` — for example, `gateway status --json`, which needs to report status even when config is broken.

### What Goes Wrong Without Setup

If a user runs `openclaw gateway start` without completing setup:

- No `openclaw.yml` exists → config load in `startGatewayServer()` fails immediately.
- `openclaw.yml` exists but no provider configured → gateway starts but the secrets snapshot contains no provider key; the first agent request fails with an auth error from the provider.
- `openclaw.yml` exists but channel credentials missing from keychain → the channel account loop starts but the plugin's `startAccount` call fails authentication with the channel's API; the backoff supervisor retries up to ten times then stops.

Each failure mode is distinct and points to a specific remediation: run `openclaw setup` to fix missing config or credentials, or use `openclaw secrets set` to add individual keychain entries without re-running the full wizard.

## Rollback and Reconfiguration

Users can redo any part of setup without reinstalling:

- **Full re-setup** — `openclaw setup` again. The wizard detects existing config and offers a reset path, which clears `openclaw.yml` and re-runs the full flow. Keychain entries from the previous run persist unless explicitly removed.
- **Provider change** — `openclaw config set` can update the provider field in `openclaw.yml` directly. The gateway's `startGatewayConfigReloader()` watches `openclaw.yml` for changes and rebuilds the plugin registry on save, so a provider change takes effect without restarting the gateway.
- **API key rotation** — `openclaw secrets set <provider>` writes a new keychain entry for the specified provider. The new value takes effect at the next gateway restart or secrets snapshot refresh.
- **Channel re-authentication** — per-channel login flows (`openclaw channels setup`) re-run the channel's OAuth or token auth without touching the provider configuration.
- **Plugin toggle** — plugins can be enabled or disabled via `openclaw.yml` `plugins.enabled` / `plugins.disabled` lists. The gateway reloads the registry on config change; no restart required.

The local-first design makes reconfiguration safe: every change touches local files or the local keychain. There is no remote state to synchronize and no risk of credential leakage through a config update.

## Source Evidence

| File | Contribution |
|------|-------------|
| `src/entry.ts` | Process entry point; startup sequence including `tryRouteCli()` |
| `src/cli/route.ts` | `tryRouteCli()` — fast-path route dispatch before Commander build |
| `src/cli/program.ts` | `buildProgram()` — full Commander program builder |
| `src/cli/program/config-guard.js` | `ensureConfigReady()` — pre-flight config validation and doctor check |
| `src/wizard/setup.ts` | `runSetupWizard()` — interactive setup flow |
| `src/wizard/prompts.ts` | `WizardPrompter`, `WizardCancelledError` |
| `src/plugins/manifest.ts` | `PluginManifest`, `providerAuthChoices`, `providerAuthEnvVars` |
| `src/plugins/discovery.ts` | `discoverOpenClawPlugins()` — filesystem plugin scan |
| `src/plugins/manifest-registry.ts` | `loadPluginManifestRegistry()` — manifest load and validation |
| `src/plugins/config-state.ts` | `resolveEffectivePluginActivationState()` — activation priority chain |
| `src/plugins/registry.ts` | `createPluginRegistry()` — registry assembly from active plugins |
| `src/plugins/runtime.ts` | `setActivePluginRegistry()`, `getActivePluginRegistry()` — atomic registry swap |
| `src/gateway/server.impl.ts` | `startGatewayServer()` — composition root; 7-step startup sequence |
| `src/gateway/server-channels.ts` | `createChannelManager()` — supervised per-account channel loops |
| `src/gateway/server-plugin-bootstrap.ts` | `resolveGatewayStartupPluginIds()`, deferred plugin loading |
| `src/secrets/runtime.ts` | `activateSecretsRuntimeSnapshot()`, `resolveCommandSecretsFromActiveRuntimeSnapshot()` |
| `src/secrets/runtime-gateway-auth-surfaces.ts` | `GATEWAY_AUTH_SURFACE_PATHS`, `evaluateGatewayAuthSurfaceStates()` |
| `src/gateway/auth-rate-limit.ts` | `createAuthRateLimiter()` — brute-force protection on auth surfaces |
| `src/config/paths.ts` | `resolveStateDir()` — local state directory resolution |

## See Also

- [CLI and Onboarding](../entities/cli-and-onboarding.md)
- [Gateway Control Plane](../entities/gateway-control-plane.md)
- [Plugin Platform](../entities/plugin-platform.md)
- [Local-First Personal Assistant Architecture](../concepts/local-first-personal-assistant-architecture.md)
- [Auth and Approval Boundaries](../concepts/auth-and-approval-boundaries.md)
- [Inbound Message to Agent Reply Flow](inbound-message-to-agent-reply-flow.md)
- [Extension to Runtime Capability Flow](extension-to-runtime-capability-flow.md)
- [Gateway As Control Plane](../concepts/gateway-as-control-plane.md)
