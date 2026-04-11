# CLI Runtime

## Overview

The CLI runtime is the primary entry point for the OpenCode binary. It is implemented in `src/index.ts` and owns the complete lifecycle from process startup through command dispatch to final process exit. The runtime is responsible for constructing the yargs command tree, initializing the logging subsystem, starting heap telemetry, setting process-level environment markers, running one-time JSON-to-SQLite database migration on first launch, and dispatching to one of roughly twenty named commands.

The CLI is also the sole location where global error handlers for `unhandledRejection` and `uncaughtException` are installed, and where top-level yargs parsing failures are routed to structured error output rather than raw stack traces.

## Key Types

### Global CLI options (yargs)

These options apply to every subcommand and are evaluated in the middleware phase before any command handler runs.

| Option | Type | Description |
|--------|------|-------------|
| `--print-logs` | `boolean` | Pipes structured log output to stderr in addition to the log file |
| `--log-level` | `"DEBUG" \| "INFO" \| "WARN" \| "ERROR"` | Overrides default log level (default is `DEBUG` for local/dev installs, `INFO` otherwise) |
| `--pure` | `boolean` | Sets `OPENCODE_PURE=1` in the environment; suppresses loading of external plugins |
| `--version` / `-v` | — | Prints `Installation.VERSION` and exits |
| `--help` / `-h` | — | Renders help via a custom `show()` function that prepends the logo to stderr |

### Installation.Info (from `installation/index.ts`)

```typescript
// Zod schema: InstallationInfo
{
  version: string,   // current binary version (semver)
  latest:  string,   // latest published version (from remote check)
}
```

Additional statics on the `Installation` namespace:

| Export | Value |
|--------|-------|
| `Installation.VERSION` | Current semver string sourced from `meta.ts` at build time |
| `Installation.CHANNEL` | Release channel (`stable`, `beta`, etc.) |
| `Installation.Method` | Union: `"curl" \| "npm" \| "yarn" \| "pnpm" \| "bun" \| "brew" \| "scoop" \| "choco" \| "unknown"` |
| `Installation.ReleaseType` | Union: `"patch" \| "minor" \| "major"` |
| `Installation.isLocal()` | Returns true when the binary is running from a local checkout |

## Architecture

The entry point file (`src/index.ts`) is deliberately thin. It constructs a single yargs instance, attaches one middleware block, registers all commands, and runs. All non-trivial logic lives in the modules imported by each command file under `src/cli/cmd/`.

```
src/index.ts          <-- yargs construction, middleware, error boundary
  |
  +-- cli/bootstrap.ts          -- Instance.provide() wrapper for project-scoped commands
  |
  +-- cli/cmd/
  |     run.ts                  -- RunCommand
  |     generate.ts             -- GenerateCommand
  |     tui/thread.ts           -- TuiThreadCommand
  |     tui/attach.ts           -- AttachCommand
  |     acp.ts                  -- AcpCommand
  |     mcp.ts                  -- McpCommand
  |     account.ts              -- ConsoleCommand
  |     providers.ts            -- ProvidersCommand
  |     agent.ts                -- AgentCommand
  |     upgrade.ts              -- UpgradeCommand
  |     uninstall.ts            -- UninstallCommand
  |     serve.ts                -- ServeCommand
  |     web.ts                  -- WebCommand
  |     models.ts               -- ModelsCommand
  |     stats.ts                -- StatsCommand
  |     export.ts               -- ExportCommand
  |     import.ts               -- ImportCommand
  |     github.ts               -- GithubCommand
  |     pr.ts                   -- PrCommand
  |     session.ts              -- SessionCommand
  |     plug.ts                 -- PluginCommand
  |     db.ts                   -- DbCommand
  |     debug.ts                -- DebugCommand
  |
  +-- installation/index.ts     -- VERSION, isLocal(), update events
  +-- storage/json-migration.ts -- JsonMigration.run() with progress callback
  +-- storage/db.ts             -- Database.Client() — used during migration check
  +-- cli/heap.ts               -- Heap.start() telemetry
  +-- util/log.ts               -- Log.init(), Log.Default, Log.file()
```

The `bootstrap()` helper in `cli/bootstrap.ts` is a thin wrapper around `Instance.provide()`. Commands that require a project context (a working directory, loaded config, initialized filesystem) call `bootstrap(directory, async () => { ... })` to ensure `InstanceBootstrap` runs and `Instance.dispose()` is called on exit.

## Runtime Behavior

The following steps happen in order every time the `opencode` binary runs:

1. **Global error handlers installed.** Before any argument parsing, `process.on("unhandledRejection")` and `process.on("uncaughtException")` are registered. Both log via `Log.Default.error` and allow execution to continue; fatal errors are caught in the top-level `try/catch`.

2. **yargs instance built.** `yargs(hideBin(process.argv))` is called with `.parserConfiguration({ "populate--": true })` so that `--` passthrough arguments are preserved for commands such as `run` that forward flags to subprocesses.

3. **`--pure` flag processed first in middleware.** If `--pure` is present, `process.env.OPENCODE_PURE = "1"` is set before any other initialization so that plugin loading code (which runs after this point) can observe the flag.

4. **`Log.init()` called.** The log subsystem is initialized with `print`, `dev`, and `level` options derived from global flags and `Installation.isLocal()`. All subsequent log calls are valid after this point.

5. **`Heap.start()` called.** Lightweight heap-size telemetry begins tracking memory usage for diagnostic purposes.

6. **Environment markers set.** Three variables are stamped into `process.env`:
   - `AGENT=1` — signals to child processes that they are running inside the agent
   - `OPENCODE=1` — general presence marker
   - `OPENCODE_PID=<pid>` — allows child processes to locate the parent

7. **First-run database migration check.** The existence of `<Global.Path.data>/opencode.db` is used as a sentinel. If the file is absent, the process is performing its first run and all legacy JSON storage must be migrated to SQLite via `JsonMigration.run(Database.Client().$client, { progress })`.

8. **Progress bar rendered during migration.** When stderr is a TTY, a 36-character block-character progress bar is drawn in orange/muted ANSI colors with the cursor hidden (`\x1b[?25l` / `\x1b[?25h`). Non-TTY environments (e.g., CI, embedded TUI) receive `sqlite-migration:<percent>` newline-separated lines instead, followed by `sqlite-migration:done`.

9. **Command dispatched.** yargs resolves the subcommand and invokes its handler. Most handlers call `bootstrap()` to enter a project context.

10. **Error boundary.** If any command throws, the outer `try/catch` formats the error through `FormatError`, logs it with `Log.Default.error("fatal", ...)`, and writes a human-readable message to stderr via `UI.error()`. Unknown errors include a pointer to `Log.file()`. `process.exitCode = 1` is set but `process.exit()` is always called in `finally` to flush pending I/O and terminate any lingering child processes (particularly MCP servers running in Docker that do not handle SIGTERM).

## Command Reference

| Command export | yargs name (inferred) | Primary purpose |
|----------------|----------------------|-----------------|
| `AcpCommand` | `acp` | Agent Control Protocol server |
| `McpCommand` | `mcp` | Model Context Protocol integration |
| `TuiThreadCommand` | `thread` | Launch or resume a TUI thread |
| `AttachCommand` | `attach` | Attach to an existing TUI session |
| `RunCommand` | `run` | Non-interactive prompt execution |
| `GenerateCommand` | `generate` | Code generation utility |
| `DebugCommand` | `debug` | Diagnostics and debug output |
| `ConsoleCommand` | `account` | Account/console management |
| `ProvidersCommand` | `providers` | List and configure providers |
| `AgentCommand` | `agent` | Agent mode entry |
| `UpgradeCommand` | `upgrade` | Self-update binary |
| `UninstallCommand` | `uninstall` | Remove OpenCode from system |
| `ServeCommand` | `serve` | Start HTTP/WebSocket server |
| `WebCommand` | `web` | Open web UI |
| `ModelsCommand` | `models` | List available models |
| `StatsCommand` | `stats` | Usage statistics |
| `ExportCommand` | `export` | Export sessions/data |
| `ImportCommand` | `import` | Import sessions/data |
| `GithubCommand` | `github` | GitHub integration |
| `PrCommand` | `pr` | Pull request tooling |
| `SessionCommand` | `session` | Session management |
| `PluginCommand` | `plugin` | Plugin management |
| `DbCommand` | `db` | Database inspection/repair |

The `completion` built-in generates shell completion scripts (bash/zsh/fish).

## Source Files

| File | Key exports / functions |
|------|------------------------|
| `src/index.ts` | yargs instance construction, middleware (Log.init, Heap.start, env markers, migration), global error handlers, `show()` help formatter |
| `src/cli/bootstrap.ts` | `bootstrap(directory, cb)` — wraps `Instance.provide` + `Instance.dispose` |
| `src/installation/index.ts` | `Installation.VERSION`, `Installation.CHANNEL`, `Installation.isLocal()`, `Installation.getReleaseType()`, `Installation.Info` schema, `Installation.Event.Updated`, `Installation.Event.UpdateAvailable` |
| `src/storage/json-migration.ts` | `JsonMigration.run(client, { progress })` — migrates legacy JSON flat files to SQLite |
| `src/storage/db.ts` | `Database.Client()` — DrizzleORM client factory |
| `src/cli/heap.ts` | `Heap.start()` — heap telemetry |
| `src/util/log.ts` | `Log.init()`, `Log.Default`, `Log.file()`, `Log.Level` type |
| `src/cli/ui.ts` | `UI.logo()`, `UI.error()` — CLI output helpers |
| `src/cli/error.ts` | `FormatError(e)` — converts error objects to user-readable strings |

## See Also

- [Session System](session-system.md)
- [Project and Instance System](project-and-instance-system.md)
- [Provider System](provider-system.md)
- [Tool System](tool-system.md)
- [Request to Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [Architecture Overview](../summaries/architecture-overview.md)
