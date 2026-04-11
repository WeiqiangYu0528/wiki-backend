# Entity: AgentTool

**Type:** Entity
**Source directory:** `tools/AgentTool/`
**Primary file:** `AgentTool.tsx`

---

## Purpose

AgentTool is Claude Code's recursive orchestration mechanism. It allows the top-level Claude instance to spawn one or more sub-agents — independent Claude processes — that each receive their own prompt, tool pool, and execution context. Sub-agents can run in the foreground (blocking the parent), in the background, in isolated git worktrees, or in remote cloud environments.

AgentTool is the architectural centerpiece that turns a single-threaded assistant into a parallel multi-agent system.

---

## File Structure

| File | Role |
|------|------|
| `AgentTool.tsx` | Main tool definition — schema, `call()`, lifecycle management |
| `agentToolUtils.ts` | Progress tracking, task lifecycle helpers, result extraction |
| `runAgent.ts` | Core loop that runs a sub-agent conversation to completion |
| `resumeAgent.ts` | Resumes a previously paused/backgrounded agent |
| `forkSubagent.ts` | Worktree-isolation fork logic |
| `spawnMultiAgent.ts` | (in `shared/`) Low-level spawning of teammate agents |
| `agentColorManager.ts` | Assigns terminal colors to distinguish agent output streams |
| `agentDisplay.ts` | Formatting helpers for agent progress in the UI |
| `agentMemory.ts` | Persists agent memory between sessions |
| `agentMemorySnapshot.ts` | Point-in-time memory snapshots |
| `loadAgentsDir.ts` | Discovers and loads `AgentDefinition` files from disk |
| `builtInAgents.ts` | Registry of built-in agent types |
| `built-in/generalPurposeAgent.js` | The `GENERAL_PURPOSE_AGENT` definition |
| `constants.ts` | Tool name constants and one-shot agent set |
| `prompt.ts` | System prompt for agent invocations |
| `UI.tsx` | Terminal rendering components for agent progress |

---

## Input Schema

```ts
z.object({
  description:       z.string(),            // 3-5 word task label
  prompt:            z.string(),            // Full task instructions
  subagent_type:     z.string().optional(), // Agent type (built-in or custom)
  model:             z.enum(['sonnet','opus','haiku']).optional(),
  run_in_background: z.boolean().optional(),
  // Multi-agent extensions (when feature-flagged):
  name:              z.string().optional(), // Addressable name for SendMessage
  team_name:         z.string().optional(),
  mode:              permissionModeSchema().optional(),
  isolation:         z.enum(['worktree','remote']).optional(),
  cwd:               z.string().optional()  // Override working directory
})
```

---

## Agent Types

### Built-in Agents

Defined in `constants.ts`:

```ts
export const AGENT_TOOL_NAME = 'Agent'
export const LEGACY_AGENT_TOOL_NAME = 'Task'  // backward compat

export const ONE_SHOT_BUILTIN_AGENT_TYPES: ReadonlySet<string> = new Set([
  'Explore',
  'Plan',
])
```

One-shot agents (`Explore`, `Plan`) run once and return a report without expecting follow-up messages. The parent omits the agentId/SendMessage trailer to save tokens.

### Custom Agents

`loadAgentsDir.ts` scans the file system for user-defined `AgentDefinition` YAML/markdown files, enabling teams to ship specialized agents alongside their code.

---

## Execution Modes

### Foreground (default)

The parent blocks until the sub-agent completes. Progress is streamed to the terminal via `emitTaskProgress()`.

### Background (`run_in_background: true`)

The sub-agent is registered with `registerAsyncAgent()` and runs concurrently. The parent immediately receives a task ID and can continue. Completion triggers a notification via `enqueueAgentNotification()`.

### Auto-Background

When `CLAUDE_AUTO_BACKGROUND_TASKS` env var is set or the `tengu_auto_background_agents` GrowthBook flag is enabled, agents that exceed `getAutoBackgroundMs() = 120_000 ms` are automatically moved to the background.

### Worktree Isolation (`isolation: 'worktree'`)

`createAgentWorktree()` creates a temporary git worktree so the sub-agent works on an isolated copy of the repository. `removeAgentWorktree()` cleans up on completion. This prevents concurrent agents from conflicting on shared files.

### Remote Isolation (`isolation: 'remote'`)

`checkRemoteAgentEligibility()` validates prerequisites and `registerRemoteAgentTask()` launches the agent in a remote CCR (Cloud Code Runner) environment. Always runs in background.

---

## Permission Model

```ts
async checkPermissions(input, context): Promise<PermissionResult> {
  // Checks filterDeniedAgents() and getDenyRuleForAgent()
  // Returns 'allow', 'ask', or 'deny'
}
```

Deny rules can be configured per agent name or type. `filterDeniedAgents()` also prevents spawning agents that would exceed configured quotas.

---

## Multi-Agent Communication

When the `isAgentSwarmsEnabled()` feature is active, spawned agents can be given a `name` parameter. Other agents (or the parent) can then use `SendMessageTool` to send instructions to named agents while they are running. `spawnTeammate()` handles the low-level IPC.

---

## Token Tracking

`getTokenCountFromTracker()` accumulates token usage across all sub-agents. `getAssistantMessageContentLength()` feeds into budget calculations to prevent runaway token consumption.

---

## Cross-References

- [overview.md](overview.md) — system context
- [concept_permissions.md](concept_permissions.md) — permission system used by AgentTool
- [entity_bashtool.md](entity_bashtool.md) — BashTool is a key tool within each sub-agent's tool pool
- [synthesis_composition.md](synthesis_composition.md) — AgentTool is the subject of the synthesis analysis
- [index.md](index.md) — wiki navigation
