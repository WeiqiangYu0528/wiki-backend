# Agent Isolation

## Overview

When Claude Code spawns a subagent (via the Agent tool), the child must be isolated from the parent to prevent state corruption, tool conflicts, and unintended side effects. Agent isolation encompasses file state cache cloning, per-agent working directories, optional git worktree isolation, agent-specific MCP server lifecycles, and controlled state merge-back. The design balances isolation (so agents cannot corrupt each other) with efficiency (sharing what is safe to share, like prompt cache prefixes).

## Mechanism

### File State Cache Cloning

Each subagent receives its own file state cache, but the initialization strategy depends on whether the agent inherits conversation context:

- **Fork agents** (those receiving `forkContextMessages`): The parent's `readFileState` cache is cloned via `cloneFileStateCache()`, giving the child a snapshot of the parent's file knowledge at fork time. This allows the child to reason about files the parent has already read without re-reading them.
- **Fresh agents** (no fork context): A new empty cache is created via `createFileStateCacheWithSizeLimit(READ_FILE_STATE_CACHE_SIZE)`. The child starts with no file knowledge and builds its own cache from scratch.

This is implemented in `runAgent.ts:375-378`:
```typescript
const agentReadFileState =
  forkContextMessages !== undefined
    ? cloneFileStateCache(toolUseContext.readFileState)
    : createFileStateCacheWithSizeLimit(READ_FILE_STATE_CACHE_SIZE)
```

### Per-Agent Working Directories

Subagents share the parent's working directory by default but can operate in different contexts:

- **Transcript isolation**: Each agent writes to its own transcript file under `subagents/<agentId>/` in the session storage directory. The `setAgentTranscriptSubdir()` function allows grouping related agent transcripts (e.g., `workflows/<runId>`).
- **Permission scoping**: When `allowedTools` is provided, the agent's `alwaysAllowRules.session` is replaced entirely, preventing parent permission approvals from leaking. SDK-level `cliArg` rules are preserved since they represent explicit consumer intent.
- **Abort controller isolation**: Async agents get a new `AbortController()` unlinked from the parent, so canceling the parent does not abort background work. Sync agents share the parent's controller. Override controllers can be passed explicitly.

### Worktree Isolation

Agents with `isolation: 'worktree'` in their definition run in a separate git worktree:

- The `worktreePath` parameter is passed to `runAgent()`, and the agent operates in a fully separate working copy of the same repository.
- The `buildWorktreeNotice()` function (in `forkSubagent.ts:205-209`) injects a notice telling the child to translate paths from the inherited context to its worktree root, re-read files that may be stale, and understand that its changes are isolated from the parent.
- Worktree state is persisted to the session transcript via `saveWorktreeState()` so it can be restored on resume.

Fork subagents also support worktree isolation. The `FORK_AGENT` definition uses `permissionMode: 'bubble'` to surface permission prompts to the parent terminal while running in a separate worktree.

### Agent-Specific MCP Servers

Agents can declare their own MCP servers via the `mcpServers` frontmatter field. The `initializeAgentMcpServers()` function in `runAgent.ts` handles the lifecycle:

1. **Reference servers** (string name like `"slack"`): Looked up via `getMcpConfigByName()` and connected via the memoized `connectToServer()`. These are shared with the parent -- they are not cleaned up when the agent finishes.
2. **Inline servers** (object like `{ myServer: { command: "...", args: [...] } }`): Created fresh with `scope: 'dynamic'`. These are tracked as `newlyCreatedClients` and cleaned up when the agent finishes.
3. **Policy gating**: When `strictPluginOnlyCustomization` locks MCP to plugin-only, frontmatter MCP servers are skipped for user-controlled agents but still allowed for admin-trusted sources (built-in, plugin, policy).

The cleanup function only disconnects newly created (inline) clients, not shared referenced ones:
```typescript
const cleanup = async () => {
  for (const client of newlyCreatedClients) {
    if (client.type === 'connected') {
      await client.cleanup()
    }
  }
}
```

The merged client list (`[...parentClients, ...agentClients]`) gives the agent access to both parent and agent-specific MCP tools.

### State Merge Back

After a subagent completes, certain state flows back to the parent:

- **Messages**: The subagent's message stream is yielded back to the parent as `Message` objects, which the parent processes (recording to transcript, updating UI).
- **Permission state**: Agents with `permissionMode: 'bubble'` surface permission prompts to the parent's terminal rather than auto-denying.
- **Shell task cleanup**: `killShellTasksForAgent()` terminates any background shell processes the agent started.
- **Perfetto tracing**: `unregisterAgent()` removes the agent from the trace hierarchy.
- **Cache break detection**: `cleanupAgentTracking()` removes the agent from prompt cache break tracking.
- **Session hooks**: `clearSessionHooks()` removes any hooks the agent registered via its frontmatter.

Importantly, the agent's file state cache does NOT merge back -- the parent retains its own cache. This prevents a subagent's stale file reads from contaminating the parent's knowledge. The parent must re-read files if the subagent modified them.

### Fork Subagent Isolation

The fork subagent path (`forkSubagent.ts`) has additional isolation properties:

- **Recursive fork prevention**: `isInForkChild()` checks for the `FORK_BOILERPLATE_TAG` in conversation history to prevent fork children from forking again.
- **Cache-identical prefixes**: All fork children produce byte-identical API request prefixes for prompt cache sharing. Tool results in the fork prefix use a uniform placeholder (`'Fork started -- processing in background'`), with only the final directive text block differing per child.
- **Strict output format**: Fork children receive rigid instructions (10 non-negotiable rules) constraining them to direct tool execution with a structured report format, preventing conversational drift.

## Involved Entities

- [runAgent.ts](../claude_code/src/tools/AgentTool/runAgent.ts) -- core agent execution, cache cloning, MCP server lifecycle, permission scoping
- [forkSubagent.ts](../claude_code/src/tools/AgentTool/forkSubagent.ts) -- fork agent definition, worktree notices, recursive fork prevention
- [AgentTool.tsx](../claude_code/src/tools/AgentTool/AgentTool.tsx) -- tool definition and UI for agent invocation
- [agentToolUtils.ts](../claude_code/src/tools/AgentTool/agentToolUtils.ts) -- tool resolution for agent tool pools
- [loadAgentsDir.ts](../claude_code/src/tools/AgentTool/loadAgentsDir.ts) -- agent definition parsing including isolation field
- [resumeAgent.ts](../claude_code/src/tools/AgentTool/resumeAgent.ts) -- agent resume after backgrounding
- [fileStateCache.ts](../claude_code/src/utils/fileStateCache.ts) -- cache cloning and size-limited creation
- [forkedAgent.ts](../claude_code/src/utils/forkedAgent.ts) -- `createSubagentContext()` and `runForkedAgent()` utilities
- [Session Storage](../claude_code/src/utils/sessionStorage.ts) -- per-agent transcript recording

## Source Evidence

- `runAgent.ts:375-378` file state cache initialization: clones parent cache for fork agents, creates fresh for others.
- `runAgent.ts:95-218` full `initializeAgentMcpServers()` function handling reference vs. inline servers and cleanup.
- `runAgent.ts:469-479` permission scoping: replaces session allow rules while preserving CLI arg rules.
- `runAgent.ts:524-528` abort controller isolation: override > new for async > parent's for sync.
- `forkSubagent.ts:78-89` recursive fork guard: `isInForkChild()` checks for boilerplate tag in messages.
- `forkSubagent.ts:93` placeholder: `'Fork started -- processing in background'` for cache-identical prefixes.
- `forkSubagent.ts:205-209` `buildWorktreeNotice()` informing the child about path translation and isolation.
- `loadAgentsDir.ts:94-98` `isolation` field in AgentJsonSchema: accepts `'worktree'` (or `'remote'` for ant builds).

## See Also

- [Frontmatter Conventions](./frontmatter-conventions.md) -- defines the `isolation`, `mcpServers`, and `permissionMode` fields
- [Session Lifecycle](./session-lifecycle.md) -- subagent transcripts are part of the parent session's persistence
- [Compaction and Context Management](./compaction-and-context-management.md) -- subagent compaction respects isolation (no main-thread state reset)
