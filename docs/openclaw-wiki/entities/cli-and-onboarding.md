# CLI and Onboarding

## Overview

The CLI is the primary operator surface for OpenClaw. It handles the complete lifecycle of running the assistant locally: first-time setup via the `openclaw setup` wizard, gateway start/stop/status operations, channel authentication, cron job management, secrets management, agent messaging, skill management, plugin management, and maintenance commands. The CLI does not shell out to separate binaries — it imports the same runtime modules used by the gateway and constructs commands using the `commander` library against a programmatic API.

The CLI architecture follows a route-first dispatch model: `tryRouteCli()` in `src/cli/route.ts` checks whether the invoked command path matches a registered route before falling back to the full Commander program build. This means fast-path commands (like `gateway status`) skip plugin registry loading entirely, which keeps startup latency minimal for health checks and scripted automation. Slower commands that need the plugin registry declare `loadPlugins: true` (or a function that decides per-argv) in their route descriptor.

The onboarding flow is driven by `runSetupWizard()` in `src/wizard/setup.ts`, which walks the user through provider/auth selection, port configuration, and optional channel setup. Wizard state is managed by `WizardPrompter` and `WizardFlow`; the wizard writes config directly to `openclaw.yml` via `writeConfigFile()`.

## Key Types

| Type / Function | Source | Role |
|-----------------|--------|------|
| `tryRouteCli(argv)` | `src/cli/route.ts` | Fast-path dispatch before building full Commander program |
| `buildProgram()` | `src/cli/program.ts` | Builds the full Commander program with all subcommands |
| `runSetupWizard(opts)` | `src/wizard/setup.ts` | Interactive onboarding flow for first-time users |
| `ensureConfigReady()` | `src/cli/program/config-guard.js` | Pre-flight: validates config, emits doctor warnings |
| `ensurePluginRegistryLoaded({ scope })` | `src/cli/plugin-registry.js` | Lazy-loads plugin registry; scope `"channels"` or `"all"` |
| `WizardPrompter` | `src/wizard/prompts.ts` | Abstracted prompt interface used by setup flows |
| `GatewayAuthChoice` | `src/commands/onboard-types.ts` | Union of auth choices: API key, OAuth, etc. |

### Route Dispatch

```ts
// src/cli/route.ts
export async function tryRouteCli(argv: string[]): Promise<boolean> {
  if (hasHelpOrVersion(argv)) return false;
  const path = getCommandPathWithRootOptions(argv, 2);
  const route = findRoutedCommand(path);
  if (!route) return false;
  await prepareRoutedCommand({ argv, commandPath: path, loadPlugins: route.loadPlugins });
  return route.run(argv);
}
```

Routes that set `loadPlugins: true` trigger `ensurePluginRegistryLoaded()`, which performs the full plugin discovery and activation before the command runs. Routes that set `loadPlugins: false` (or a function returning false) skip it, keeping execution lean.

## Architecture

### CLI Command Surface

CLI commands are organized by domain:

| CLI File | Commands |
|----------|---------|
| `gateway-cli/` | `gateway start`, `gateway stop`, `gateway status`, `gateway restart` |
| `daemon-cli/` | `daemon start`, `daemon stop`, `daemon status` |
| `channels-cli.ts` | `channels list`, `channels setup`, `channels status` |
| `channel-auth.ts` | Per-channel login/logout/QR auth flows |
| `cron-cli/` | `cron add`, `cron list`, `cron run`, `cron remove` |
| `secrets-cli.ts` | `secrets set`, `secrets get`, `secrets audit` |
| `skills-cli.ts` | `skills list`, `skills install`, `skills update` |
| `config-cli.ts` | `config get`, `config set`, `config unset` |
| `send-runtime/` | `send` — direct message to a channel/session |
| `tui-cli.ts` | `tui` — opens interactive text UI |
| `devices-cli.ts` | `devices list`, `devices pair`, `devices remove` |
| `acp-cli.ts` | `acp` — ACP bridge server |
| `update-cli/` | `update` — self-update mechanism |

### Startup Sequence

The CLI entry point is `src/entry.ts`. On launch:

1. `normalizeEnv()` sets up environment.
2. `ensureOpenClawExecMarkerOnProcess()` marks the process.
3. `installProcessWarningFilter()` suppresses noisy warnings.
4. `enableCompileCache()` (Node.js 22+) accelerates subsequent starts.
5. `buildCliRespawnPlan()` checks whether a container respawn is needed.
6. `tryRouteCli(argv)` — fast-path dispatch.
7. If no route matches, falls back to `buildProgram()` / Commander dispatch.

### Config Guard

Before most commands run, `ensureConfigReady()` performs:
- Config file validation (schema check)
- Doctor check: missing binaries, port conflicts, plugin compatibility
- `formatConfigIssueLines()` output to stderr if issues exist

The guard is skipped for commands that explicitly set `skipConfigGuard: true` (e.g., `gateway status` with `--json`).

### Setup Wizard

`runSetupWizard()` drives a `WizardFlow` that:
1. Detects existing config and offers to reset or augment it.
2. Presents auth choices (API key, OAuth, provider auto-select).
3. Calls `resolveAuthChoiceModelSelectionPolicy()` to pick a model.
4. Resolves gateway port and sets it in config.
5. Optionally walks the user through first channel setup.
6. Writes the final config via `writeConfigFile()`.

The wizard uses `WizardCancelledError` to handle clean exit on Ctrl-C.

## Source Files

| File | Purpose |
|------|---------|
| `src/entry.ts` | Process entry point; startup sequence |
| `src/cli/run-main.ts` | `rewriteUpdateFlagArgv()`, `shouldRegisterPrimarySubcommand()`, path guard helpers |
| `src/cli/route.ts` | `tryRouteCli()` — fast-path route dispatch |
| `src/cli/program.ts` | `buildProgram()` — Commander program builder |
| `src/cli/argv.ts` | `getCommandPathWithRootOptions()`, `hasHelpOrVersion()`, `isRootHelpInvocation()` |
| `src/cli/gateway-cli/` | Gateway lifecycle commands |
| `src/cli/daemon-cli/` | Daemon management commands |
| `src/cli/channels-cli.ts` | Channel listing and status commands |
| `src/cli/channel-auth.ts` | Channel login/logout flows |
| `src/cli/cron-cli/` | Cron job management commands |
| `src/cli/secrets-cli.ts` | Secrets management commands |
| `src/cli/skills-cli.ts` | Skills management commands |
| `src/cli/send-runtime/` | `send` command implementation |
| `src/wizard/setup.ts` | `runSetupWizard()` — interactive onboarding |
| `src/wizard/prompts.ts` | `WizardPrompter`, `WizardCancelledError` |

## See Also

- [Gateway Control Plane](gateway-control-plane.md) — CLI starts and controls the gateway
- [Plugin Platform](plugin-platform.md) — CLI loads the plugin registry before plugin-aware commands
- [Session System](session-system.md) — `send` command uses session routing
- [Onboarding to Live Gateway Flow](../syntheses/onboarding-to-live-gateway-flow.md)
- [Local-First Personal Assistant Architecture](../concepts/local-first-personal-assistant-architecture.md)
