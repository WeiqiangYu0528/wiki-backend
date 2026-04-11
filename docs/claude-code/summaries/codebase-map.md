# Codebase Map

## Overview

Guide mapping the `claude_code/src/` directory tree to wiki entity pages. Every major directory and root-level file is listed below with its purpose and a link to the relevant wiki page(s).

## Root Files

| File | Purpose | Wiki Page |
|------|---------|-----------|
| `main.tsx` | Application entry point, bootstraps the Ink-based TUI | [Architecture Overview](architecture-overview.md) |
| `Tool.ts` | Base Tool type definitions and interfaces | [Tool System](../entities/tool-system.md) |
| `tools.ts` | Tool registry / tool list assembly | [Tool System](../entities/tool-system.md) |
| `QueryEngine.ts` | Query execution loop orchestrating model calls | [Query Engine](../entities/query-engine.md) |
| `query.ts` | Streaming query implementation | [Query Engine](../entities/query-engine.md) |
| `commands.ts` | Command registry and dispatch | [Command System](../entities/command-system.md) |
| `Task.ts` | Task type definitions | [Task System](../entities/task-system.md) |
| `tasks.ts` | Task list helpers and utilities | [Task System](../entities/task-system.md) |
| `context.ts` | Top-level React context setup | [State Management](../entities/state-management.md) |
| `ink.ts` | Ink renderer configuration | [Architecture Overview](architecture-overview.md) |
| `setup.ts` | Pre-boot setup and environment validation | [Architecture Overview](architecture-overview.md) |
| `history.ts` | Conversation history persistence | [Architecture Overview](architecture-overview.md) |
| `cost-tracker.ts` | Token / cost tracking logic | [Architecture Overview](architecture-overview.md) |
| `costHook.ts` | React hook for cost display | [Architecture Overview](architecture-overview.md) |
| `dialogLaunchers.tsx` | Helpers to launch modal dialogs | [Architecture Overview](architecture-overview.md) |
| `interactiveHelpers.tsx` | Shared interactive UI helpers | [Architecture Overview](architecture-overview.md) |
| `replLauncher.tsx` | REPL screen launcher | [Architecture Overview](architecture-overview.md) |
| `projectOnboardingState.ts` | Onboarding state for new projects | [Architecture Overview](architecture-overview.md) |

## Directories

| Directory | Purpose | Wiki Page(s) |
|-----------|---------|--------------|
| `tools/` | ~40 tool implementations (Bash, FileEdit, Grep, MCP, Agent, etc.) | [Tool System](../entities/tool-system.md) |
| `services/` | Core services: API client, MCP, OAuth, analytics, compaction, LSP, voice | Multiple entity pages |
| `state/` | AppState store, selectors, and state change handlers | [State Management](../entities/state-management.md) |
| `commands/` | ~100+ slash-command implementations (`/commit`, `/review`, `/plan`, etc.) | [Command System](../entities/command-system.md) |
| `components/` | Ink/React UI components (messages, dialogs, diffs, settings) | [Architecture Overview](architecture-overview.md) |
| `hooks/` | React hooks for permissions, suggestions, IDE integration, voice | [Architecture Overview](architecture-overview.md) |
| `context/` | React context providers (mailbox, modals, notifications, voice, FPS) | [State Management](../entities/state-management.md) |
| `entrypoints/` | CLI, MCP server, and SDK entry points | [Architecture Overview](architecture-overview.md) |
| `types/` | Shared TypeScript type definitions (commands, hooks, permissions, plugins) | [Architecture Overview](architecture-overview.md) |
| `utils/` | ~300+ utility modules (git, shell, permissions, config, telemetry, etc.) | Multiple entity pages |
| `query/` | Query-loop config, dependencies, stop hooks, token budgeting | [Query Engine](../entities/query-engine.md) |
| `assistant/` | Session history helpers for the assistant | [Architecture Overview](architecture-overview.md) |
| `bootstrap/` | Bootstrap state initialization | [Architecture Overview](architecture-overview.md) |
| `bridge/` | Remote bridge protocol (REPL bridge, JWT, polling, WebSocket) | [Architecture Overview](architecture-overview.md) |
| `buddy/` | Companion sprite / buddy notification system | [Architecture Overview](architecture-overview.md) |
| `cli/` | CLI transport layer, structured I/O, NDJSON, exit handling | [Architecture Overview](architecture-overview.md) |
| `constants/` | Application-wide constants (API limits, keys, prompts, tool limits) | [Architecture Overview](architecture-overview.md) |
| `coordinator/` | Coordinator / swarm mode orchestration | [Task System](../entities/task-system.md) |
| `ink/` | Forked/extended Ink rendering engine (layout, reconciler, terminal I/O) | [Architecture Overview](architecture-overview.md) |
| `keybindings/` | Keybinding system (parser, resolver, defaults, user overrides) | [Architecture Overview](architecture-overview.md) |
| `memdir/` | Memory directory system (memory scanning, team memory paths) | [Architecture Overview](architecture-overview.md) |
| `migrations/` | Settings and model migration scripts | [Architecture Overview](architecture-overview.md) |
| `moreright/` | "More to the right" scroll indicator hook | [Architecture Overview](architecture-overview.md) |
| `native-ts/` | Native TypeScript modules (color-diff, file-index, yoga-layout) | [Architecture Overview](architecture-overview.md) |
| `outputStyles/` | Output style loader | [Architecture Overview](architecture-overview.md) |
| `plugins/` | Plugin system (built-in plugins, bundled plugin definitions) | [Architecture Overview](architecture-overview.md) |
| `remote/` | Remote session management and SDK message adapter | [Architecture Overview](architecture-overview.md) |
| `schemas/` | JSON schemas (hooks) | [Architecture Overview](architecture-overview.md) |
| `screens/` | Top-level screen components (REPL, Doctor, ResumeConversation) | [Architecture Overview](architecture-overview.md) |
| `server/` | Direct-connect server for IDE/desktop integration | [Architecture Overview](architecture-overview.md) |
| `skills/` | Bundled skills system and MCP skill builders | [Tool System](../entities/tool-system.md) |
| `tasks/` | Task runner implementations (Dream, InProcess, LocalAgent, RemoteAgent) | [Task System](../entities/task-system.md) |
| `upstreamproxy/` | Upstream proxy relay for network traffic | [Architecture Overview](architecture-overview.md) |
| `vim/` | Vim mode (motions, operators, text objects, transitions) | [Architecture Overview](architecture-overview.md) |
| `voice/` | Voice mode enablement flag | [Architecture Overview](architecture-overview.md) |

## Directory Details

### tools/

Contains one subdirectory per tool, each exporting a tool definition. Notable tools include:

- **AgentTool** -- spawns sub-agents for complex tasks
- **BashTool** / **PowerShellTool** -- shell command execution
- **FileEditTool**, **FileReadTool**, **FileWriteTool** -- filesystem operations
- **GlobTool**, **GrepTool** -- file search and content search
- **MCPTool**, **ListMcpResourcesTool**, **ReadMcpResourceTool**, **McpAuthTool** -- MCP server interaction
- **WebFetchTool**, **WebSearchTool** -- web access
- **TaskCreateTool**, **TaskGetTool**, **TaskListTool**, **TaskOutputTool**, **TaskStopTool**, **TaskUpdateTool** -- background task management
- **NotebookEditTool** -- Jupyter notebook editing
- **SkillTool**, **ToolSearchTool** -- skill invocation and tool discovery
- **ScheduleCronTool**, **RemoteTriggerTool** -- scheduled and remote execution
- **shared/** -- shared helpers (`gitOperationTracking.ts`, `spawnMultiAgent.ts`)
- **testing/** -- test utilities for tool development

### services/

Core backend services organized by domain:

- **api/** -- Claude API client, error handling, retries, usage tracking, prompt cache management
- **mcp/** -- MCP connection manager, auth, channel permissions, official registry, SDK transport
- **oauth/** -- OAuth flow (auth code listener, crypto, profile retrieval)
- **analytics/** -- Usage and behavior analytics
- **compact/** -- Conversation compaction service
- **lsp/** -- Language Server Protocol integration
- **plugins/** -- Plugin service layer
- **tips/** -- Contextual tips engine
- **tokenEstimation.ts** -- Token count estimation
- **voice.ts**, **voiceKeyterms.ts**, **voiceStreamSTT.ts** -- Voice input services
- **AgentSummary/**, **MagicDocs/**, **PromptSuggestion/**, **SessionMemory/** -- Higher-level AI services
- **extractMemories/** -- Memory extraction from conversations
- **policyLimits/** -- Policy-based rate limiting
- **remoteManagedSettings/**, **settingsSync/**, **teamMemorySync/** -- Settings and memory synchronization
- **toolUseSummary/** -- Tool use summarization

### state/

Centralized application state:

- **AppState.tsx** -- AppState type definition and React context
- **AppStateStore.ts** -- State store implementation
- **store.ts** -- Store creation and initialization
- **selectors.ts** -- Derived state selectors
- **onChangeAppState.ts** -- State change side-effects
- **teammateViewHelpers.ts** -- Helpers for teammate/swarm view

### commands/

Slash commands, each in its own subdirectory or file. Over 100 commands including:

- **commit.ts**, **commit-push-pr.ts** -- Git commit and PR workflows
- **review.ts**, **review/** -- Code review
- **plan/** -- Plan mode
- **mcp/** -- MCP server management
- **memory/** -- Memory management
- **config/** -- Configuration
- **init.ts** -- Project initialization
- **doctor/** -- Diagnostics
- **vim/** -- Vim mode toggle
- **voice/** -- Voice mode
- **tasks/** -- Task management
- **skills/** -- Skills management
- **plugins/** -- Plugin management

### components/

React/Ink UI components. Major subsections:

- **App.tsx** -- Root application component
- **PromptInput/** -- User input area
- **Messages.tsx**, **Message.tsx**, **MessageRow.tsx** -- Conversation display
- **StructuredDiff.tsx**, **diff/** -- Code diff rendering
- **Settings/** -- Settings panels
- **HelpV2/** -- Help screen
- **permissions/** -- Permission approval dialogs
- **mcp/** -- MCP-related UI
- **agents/**, **tasks/**, **teams/** -- Multi-agent and task UI
- **design-system/**, **ui/** -- Shared design tokens and primitives
- **sandbox/** -- Sandbox violation display
- **shell/** -- Shell-related components
- **skills/** -- Skills UI
- **wizard/** -- Setup wizard components

### utils/

Extensive utility library. Key areas:

- **git.ts**, **git/** -- Git operations and helpers
- **permissions/** -- Permission checking and approval logic
- **settings/** -- Settings loading and validation
- **shell/**, **Shell.ts**, **ShellCommand.ts** -- Shell execution
- **sandbox/** -- Sandbox enforcement utilities
- **mcp/** -- MCP utility helpers
- **telemetry/** -- Telemetry collection
- **model/** -- Model selection and configuration
- **task/** -- Task utilities
- **swarm/** -- Multi-agent swarm utilities
- **todo/** -- Todo tracking
- **memory/** -- Memory utilities
- **config.ts** -- Configuration loading
- **systemPrompt.ts** -- System prompt assembly
- **tokens.ts**, **tokenBudget.ts** -- Token counting and budgeting

### tasks/

Background task runners:

- **DreamTask/** -- Autonomous "dream" background tasks
- **InProcessTeammateTask/** -- In-process teammate execution
- **LocalAgentTask/** -- Local agent subprocess tasks
- **LocalMainSessionTask.ts** -- Main session task wrapper
- **LocalShellTask/** -- Shell-based background tasks
- **RemoteAgentTask/** -- Remote agent execution
- **types.ts** -- Shared task type definitions

### entrypoints/

Application entry points:

- **cli.tsx** -- Main CLI entry point
- **init.ts** -- Initialization entry point
- **mcp.ts** -- MCP server entry point
- **sdk/** -- SDK entry point for programmatic usage
- **agentSdkTypes.ts**, **sandboxTypes.ts** -- Type exports

### bridge/

Remote bridge for web/desktop integration:

- **bridgeMain.ts** -- Bridge initialization
- **bridgeApi.ts** -- Bridge HTTP API
- **bridgeMessaging.ts** -- Message transport
- **replBridge.ts**, **replBridgeHandle.ts**, **replBridgeTransport.ts** -- REPL bridge layer
- **remoteBridgeCore.ts** -- Core remote bridge logic
- **jwtUtils.ts**, **trustedDevice.ts** -- Authentication
- **SessionsWebSocket** (in `remote/`) -- WebSocket session management

### ink/

Forked Ink terminal UI framework with custom extensions:

- **ink.tsx** -- Ink app initialization
- **reconciler.ts** -- Custom React reconciler for terminal
- **layout/** -- Layout engine (uses yoga-layout)
- **dom.ts** -- Terminal DOM abstraction
- **events/** -- Terminal event handling
- **components/** -- Low-level Ink components
- **termio.ts**, **termio/** -- Terminal I/O layer
- **selection.ts** -- Text selection support
- **searchHighlight.ts** -- Search result highlighting

## See Also

- [Architecture Overview](architecture-overview.md)
- [Glossary](glossary.md)
