# Command System

## Overview

The command system is the slash-command framework that powers all user-facing `/` commands in Claude Code. It provides 100+ commands spanning session management, development workflows, configuration, navigation, MCP integration, and more. Commands are registered centrally in `commands.ts`, assembled from multiple sources (built-in, bundled skills, plugins, MCP servers, workflow scripts), and filtered at runtime by feature flags, auth availability, and environment.

Each command exports a `Command` object conforming to a union type that determines its execution model: `prompt` commands expand into model-facing text, `local` commands execute logic and return structured results, and `local-jsx` commands render interactive Ink UI. The registry uses `bun:bundle`'s `feature()` function for dead-code elimination -- conditionally-loaded commands are wrapped in `feature()` guards so they are stripped from builds that lack the corresponding flag.

## Key Types

### Command

The `Command` type (`types/command.ts`) is the intersection of `CommandBase` with one of three execution variants:

```typescript
type Command = CommandBase & (PromptCommand | LocalCommand | LocalJSXCommand)
```

**CommandBase** carries shared metadata:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `string` | Canonical command name (used for `/name` invocation) |
| `aliases` | `string[]` | Alternative names (e.g., `clear` has aliases `reset`, `new`) |
| `description` | `string` | User-facing description shown in typeahead and help |
| `availability` | `('claude-ai' \| 'console')[]` | Auth/provider gating -- restricts who sees the command |
| `isEnabled` | `() => boolean` | Runtime enablement check (feature flags, env vars) |
| `isHidden` | `boolean` | If true, hidden from typeahead and help |
| `whenToUse` | `string` | Detailed usage scenarios for model-facing skill discovery |
| `disableModelInvocation` | `boolean` | If true, only users (not the model) can invoke this command |
| `userInvocable` | `boolean` | Whether users can invoke via `/name` |
| `loadedFrom` | `'commands_DEPRECATED' \| 'skills' \| 'plugin' \| 'managed' \| 'bundled' \| 'mcp'` | Origin of the command |
| `kind` | `'workflow'` | Distinguishes workflow-backed commands |
| `immediate` | `boolean` | If true, bypasses the execution queue |
| `isSensitive` | `boolean` | If true, arguments are redacted from conversation history |
| `argumentHint` | `string` | Hint text displayed in gray after the command name |

**PromptCommand** (type: `'prompt'`) -- expands to model-facing content:

- `getPromptForCommand(args, context)` returns `ContentBlockParam[]` injected into the conversation.
- `progressMessage` -- displayed while the command processes.
- `contentLength` -- character length estimate for token budgeting.
- `allowedTools` -- restricts which tools the model can use after expansion.
- `source` -- one of `SettingSource | 'builtin' | 'mcp' | 'plugin' | 'bundled'`.
- `context` -- `'inline'` (default) or `'fork'` (run as sub-agent).
- `hooks` -- hook settings registered when the skill is invoked.
- `paths` -- glob patterns; when set, the skill only appears after the model touches matching files.

**LocalCommand** (type: `'local'`) -- lazy-loaded logic returning structured results:

- `load()` returns a `LocalCommandModule` with a `call(args, context)` function.
- `call()` returns `LocalCommandResult`: `{ type: 'text', value }`, `{ type: 'compact', compactionResult }`, or `{ type: 'skip' }`.
- `supportsNonInteractive` -- whether the command works outside the interactive REPL.

**LocalJSXCommand** (type: `'local-jsx'`) -- lazy-loaded commands that render React/Ink UI:

- `load()` returns a `LocalJSXCommandModule` with a `call(onDone, context, args)` function.
- `onDone` callback controls what happens after the UI dismisses: display mode (`'skip' | 'system' | 'user'`), whether to re-query the model, meta messages, and next input prefill.

### Helper Functions

- `getCommandName(cmd)` -- resolves the user-visible name, falling back to `cmd.name`.
- `isCommandEnabled(cmd)` -- resolves enablement, defaulting to `true`.
- `meetsAvailabilityRequirement(cmd)` -- checks auth/provider gating (claude-ai subscriber, console API key user).
- `findCommand(name, commands)` -- looks up by name, `getCommandName`, or aliases.
- `formatDescriptionWithSource(cmd)` -- appends source annotations for user-facing UI (e.g., "(plugin)", "(bundled)", "(workflow)").

## Command Categories

### Setup and Authentication

| Command | Type | Description |
|---------|------|-------------|
| `/init` | prompt | Initialize project configuration |
| `/login` | local-jsx | Authenticate with Anthropic (hidden for 3P users) |
| `/logout` | local-jsx | Sign out |
| `/onboarding` | local-jsx | Interactive onboarding flow (internal only) |
| `/config` | local-jsx | View and edit configuration |
| `/install-github-app` | local-jsx | Install the GitHub App integration |
| `/install-slack-app` | local-jsx | Install the Slack App integration |
| `/terminal-setup` | local-jsx | Configure terminal integration |
| `/permissions` | local-jsx | Manage tool permission rules |
| `/privacy-settings` | local-jsx | Configure privacy and telemetry settings |

### Development Workflows

| Command | Type | Description |
|---------|------|-------------|
| `/review` | prompt | Review a pull request via `gh pr diff` |
| `/ultrareview` | local-jsx | Deep bug-finding review (runs remotely, feature-gated) |
| `/commit` | prompt | Create a git commit (internal only) |
| `/commit-push-pr` | prompt | Commit, push, and create PR (internal only) |
| `/diff` | local | Show current git diff |
| `/pr-comments` | prompt | Fetch and address PR review comments |
| `/release-notes` | local | Generate release notes |
| `/security-review` | prompt | Run a security-focused code review |
| `/branch` | local-jsx | Create or switch git branches |
| `/init-verifiers` | prompt | Initialize verification scripts (internal only) |

### Navigation and Files

| Command | Type | Description |
|---------|------|-------------|
| `/add-dir` | local-jsx | Add a directory to the working set |
| `/files` | local | List tracked files in context |
| `/context` | prompt | View and manage context window contents |

### Session Management

| Command | Type | Description |
|---------|------|-------------|
| `/clear` | local | Clear conversation history (aliases: `reset`, `new`) |
| `/compact` | local | Summarize and compress conversation context |
| `/resume` | local-jsx | Resume a previous session |
| `/session` | local-jsx | Show session QR code/URL for remote access |
| `/export` | local-jsx | Export conversation history |
| `/rename` | local | Rename the current session |
| `/share` | local | Share session (internal only) |
| `/copy` | local | Copy last assistant message to clipboard |
| `/cost` | local | Show session token cost |
| `/rewind` | local-jsx | Rewind conversation to a previous point |
| `/stats` | local | Show session statistics |

### MCP and Integrations

| Command | Type | Description |
|---------|------|-------------|
| `/mcp` | local-jsx | Manage MCP server connections (add, remove, configure) |
| `/bridge` | local-jsx | Bridge mode for remote control (feature-gated: `BRIDGE_MODE`) |
| `/ide` | local-jsx | IDE extension management |
| `/desktop` | local-jsx | Desktop app integration |
| `/mobile` | local-jsx | Mobile QR code for remote access |
| `/chrome` | local-jsx | Chrome extension integration |

### Project Configuration

| Command | Type | Description |
|---------|------|-------------|
| `/memory` | local-jsx | View and edit CLAUDE.md project memory |
| `/doctor` | local-jsx | Diagnose configuration and environment issues |
| `/help` | local-jsx | Show help and available commands |
| `/hooks` | local-jsx | Manage event hooks |
| `/plugin` | local-jsx | Manage plugins |
| `/reload-plugins` | local | Reload plugin configurations |

### Skills and Agents

| Command | Type | Description |
|---------|------|-------------|
| `/skills` | local-jsx | Browse and manage skills |
| `/agents` | local-jsx | View and manage agent configurations |
| `/tasks` | local-jsx | View and manage background tasks |
| `/plan` | local | Toggle plan mode |
| `/passes` | local-jsx | Manage multi-pass execution |

### UI and Preferences

| Command | Type | Description |
|---------|------|-------------|
| `/theme` | local-jsx | Change terminal color theme |
| `/color` | local-jsx | Change agent color |
| `/vim` | local | Toggle vim keybinding mode |
| `/keybindings` | local-jsx | Manage keyboard shortcuts |
| `/stickers` | local-jsx | Sticker pack management |
| `/output-style` | local-jsx | Change output formatting style |
| `/statusline` | local | Toggle status line |
| `/effort` | local-jsx | Set response effort level |
| `/fast` | local | Toggle fast/low-effort mode |

### Feature-Gated Commands

These commands are conditionally loaded via `feature()` guards and stripped from builds without the flag:

| Command | Feature Flag | Description |
|---------|-------------|-------------|
| `/proactive` | `PROACTIVE` or `KAIROS` | Proactive agent mode |
| `/brief` | `KAIROS` or `KAIROS_BRIEF` | Brief response mode |
| `/assistant` | `KAIROS` | Assistant mode |
| `/bridge` | `BRIDGE_MODE` | Remote control bridge |
| `/voice` | `VOICE_MODE` | Voice input mode |
| `/force-snip` | `HISTORY_SNIP` | Force history snipping |
| `/workflows` | `WORKFLOW_SCRIPTS` | Workflow script management |
| `/remote-setup` | `CCR_REMOTE_SETUP` | Remote environment setup |
| `/subscribe-pr` | `KAIROS_GITHUB_WEBHOOKS` | PR webhook subscriptions |
| `/ultraplan` | `ULTRAPLAN` | Advanced planning mode |
| `/torch` | `TORCH` | Torch debugging |
| `/peers` | `UDS_INBOX` | Peer agent communication |
| `/fork` | `FORK_SUBAGENT` | Fork sub-agent sessions |
| `/buddy` | `BUDDY` | Buddy pairing mode |

### Internal-Only Commands

Commands in `INTERNAL_ONLY_COMMANDS` are only loaded when `USER_TYPE === 'ant'` and `IS_DEMO` is not set:

`backfill-sessions`, `break-cache`, `bughunter`, `commit`, `commit-push-pr`, `ctx-viz`, `good-claude`, `issue`, `init-verifiers`, `mock-limits`, `bridge-kick`, `version`, `reset-limits`, `onboarding`, `share`, `summary`, `teleport`, `ant-trace`, `perf-issue`, `env`, `oauth-refresh`, `debug-tool-call`, `agents-platform`, `autofix-pr`.

## Command Lifecycle

### 1. Registration

Commands are imported and collected in `commands.ts`. The `COMMANDS()` function (memoized) returns the master array of built-in commands. Feature-gated commands use `bun:bundle`'s `feature()` for dead-code elimination:

```typescript
const proactive = feature('PROACTIVE') || feature('KAIROS')
  ? require('./commands/proactive.js').default
  : null
```

Conditional commands are spread into the array: `...(proactive ? [proactive] : [])`.

### 2. Multi-Source Assembly

`loadAllCommands(cwd)` (memoized by working directory) assembles the full command list from multiple sources in priority order:

1. **Bundled skills** -- from `skills/bundledSkills.ts`
2. **Built-in plugin skills** -- from `plugins/builtinPlugins.ts`
3. **Skill directory commands** -- user-defined skills from `.claude/skills/` directories
4. **Workflow commands** -- from `WorkflowTool/createWorkflowCommand.ts` (feature-gated)
5. **Plugin commands** -- from installed plugins
6. **Plugin skills** -- skill-type commands from plugins
7. **Built-in commands** -- the `COMMANDS()` array

### 3. Filtering

`getCommands(cwd)` applies two runtime filters on every call (not memoized, since auth can change mid-session):

- `meetsAvailabilityRequirement(cmd)` -- checks `cmd.availability` against current auth state (claude-ai subscriber, console API key user, etc.).
- `isCommandEnabled(cmd)` -- evaluates the command's `isEnabled()` function (feature flags, environment variables).

Dynamic skills discovered during file operations are also deduped and merged.

### 4. User Invocation

The user types `/command-name [args]` in the REPL. The input handler:

1. Strips the `/` prefix.
2. Calls `findCommand(name, commands)` -- matches on `name`, `getCommandName()`, or `aliases`.
3. Dispatches based on `command.type`.

### 5. Execution

- **`prompt`** -- `getPromptForCommand(args, context)` is called, returning `ContentBlockParam[]` that are injected into the conversation as if the user had typed them. The model then responds.
- **`local`** -- `load()` lazily imports the implementation module, then `call(args, context)` executes. Returns `LocalCommandResult`.
- **`local-jsx`** -- `load()` lazily imports the UI module, then `call(onDone, context, args)` returns a React node rendered in the terminal. The `onDone` callback controls post-command flow.

### 6. Caching and Invalidation

- `loadAllCommands` is memoized by `cwd` to avoid repeated expensive disk I/O and dynamic imports.
- `clearCommandsCache()` invalidates all layers: command memoization, plugin command cache, plugin skills cache, skill caches, and the skill search index.
- `clearCommandMemoizationCaches()` invalidates only the memoization layer (used when dynamic skills are added).

## Remote and Bridge Safety

Two allowlists restrict which commands execute in constrained environments:

- **`REMOTE_SAFE_COMMANDS`** -- commands safe in `--remote` mode (no local filesystem/git/shell/IDE dependencies): `session`, `exit`, `clear`, `help`, `theme`, `color`, `vim`, `cost`, `usage`, `copy`, `btw`, `feedback`, `plan`, `keybindings`, `statusline`, `stickers`, `mobile`.
- **`BRIDGE_SAFE_COMMANDS`** -- local-type commands safe to execute when input arrives over the Remote Control bridge: `compact`, `clear`, `cost`, `summary`, `release-notes`, `files`.
- `isBridgeSafeCommand(cmd)` -- prompt commands are always bridge-safe (they expand to text); local-jsx commands are always blocked (they render Ink UI); local commands require explicit opt-in via the allowlist.

## Source Files

| File | Description |
|------|-------------|
| `commands.ts` | Central registry -- imports, assembles, filters, and exports all commands |
| `types/command.ts` | `Command`, `CommandBase`, `PromptCommand`, `LocalCommand`, `LocalJSXCommand` type definitions |
| `commands/clear/index.ts` | Example local command -- minimal metadata with lazy `load()` |
| `commands/compact/index.ts` | Example local command with `isEnabled` gating via env var |
| `commands/review.ts` | Example prompt command -- injects a code review prompt into the conversation |
| `commands/review/ultrareviewCommand.ts` | Example local-jsx command with feature-flag gating |
| `skills/loadSkillsDir.ts` | Loads skill directory commands and dynamic skills |
| `skills/bundledSkills.ts` | Bundled skill registration |
| `plugins/builtinPlugins.ts` | Built-in plugin skill commands |
| `utils/plugins/loadPluginCommands.ts` | Plugin command and skill loading with cache management |

## See Also

- [Skill System](skill-system.md) -- skills are prompt-type commands loaded from skill directories, plugins, and bundles
- [Tool System](tool-system.md) -- tools are the model-invocable actions; SkillTool bridges commands into the tool system
- [Configuration System](configuration-system.md) -- settings that control command availability and behavior
- [Permission System](permission-system.md) -- permission rules that gate tool usage after command expansion
