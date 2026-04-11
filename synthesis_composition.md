# Synthesis: Tool Composition and the Agent-Tool Feedback Loop

**Type:** Synthesis

---

## The Core Insight

Claude Code is built around a self-referential architecture: the system that runs tools *is itself* a tool. AgentTool allows Claude to invoke Claude, which can invoke Claude again — creating an arbitrarily deep recursive structure. The tool pool each agent receives is assembled dynamically via `assembleToolPool()`, and AgentTool is almost always included. This means the full power of the tool system — shell access, file editing, web fetching — is available to every agent in the tree, not just the root.

This document synthesizes how the different subsystems interconnect to enable this capability, and what constraints prevent it from becoming unbounded or unsafe.

---

## The Composition Pattern

Every Claude Code session runs a main loop that:

1. Sends messages (including tool results) to the Anthropic API
2. Receives `assistant` messages that may contain `tool_use` blocks
3. Dispatches each `tool_use` to the matching tool's `call()` method
4. Collects results and loops

When AgentTool is dispatched, step 3 itself executes steps 1-4 for the sub-agent. The sub-agent runs `runAgent()`, which is a full conversation loop with its own message history, tool pool, and termination condition.

```
Root agent loop
  └─> AgentTool.call()
        └─> runAgent()  [sub-agent loop]
              ├─> BashTool.call()     [shell execution]
              ├─> FileReadTool.call() [file access]
              ├─> AgentTool.call()    [nested sub-agent]
              │     └─> runAgent()   [grandchild agent loop]
              └─> [completion]
```

This is a tree of agent loops, each with its own conversation context.

---

## How BashTool and AgentTool Interlock

BashTool is the primary "leaf" action — it performs concrete work on the operating system. AgentTool is the primary "branch" node — it creates new subtrees. The combination is powerful:

- The root agent can analyze a large codebase by spawning multiple `AgentTool` sub-agents in parallel, each running `BashTool(grep ...)` and `FileReadTool` calls independently.
- A sub-agent can itself spawn further sub-agents for sub-tasks.
- Because sub-agents in worktree isolation mode (`isolation: 'worktree'`) operate on separate git branches, even concurrent `FileEditTool` calls across agents don't conflict.

AgentTool imports `BASH_TOOL_NAME` from BashTool to detect when a sub-agent's last action was a shell command — used to determine progress display behavior.

---

## How the Permission System Propagates

The permission model is layered across the agent tree:

1. **Root-level rules** — set by the user's configuration, apply to the root agent's tool calls.
2. **Sub-agent mode inheritance** — `AgentTool` accepts a `mode` parameter that overrides the permission mode for the sub-agent (e.g., spawning a sub-agent in `plan` mode so it must get user approval before any destructive action).
3. **Deny rules for agents** — `getDenyRuleForAgent()` prevents certain agent types from being spawned at all, regardless of what the parent requests.
4. **Worktree isolation** — if an agent runs in a worktree, its file-system permission rules are scoped to that worktree path.

This means the permission system is not flat: a root agent with broad permissions can spawn a child with restricted permissions, and those restrictions are enforced at the child's tool call boundaries.

See [concept_permissions.md](concept_permissions.md) for the permission system details.

---

## Structural Tensions and Guardrails

### Token Budget Exhaustion

Each level of nesting consumes tokens. `getAssistantMessageContentLength()` and `getTokenCountFromTracker()` accumulate usage across the subtree. Without limits, deeply nested agents would exhaust the context window.

The system mitigates this via:
- `ONE_SHOT_BUILTIN_AGENT_TYPES` (`Explore`, `Plan`) — these agents skip the agentId/SendMessage trailer (~135 tokens saved per invocation)
- Auto-summarization via `startAgentSummarization()` for long-running agents
- Agent-level token budgets enforced by the task infrastructure

### Runaway Parallelism

Background agents (`run_in_background: true`) are registered with `registerAsyncAgent()`. The task system tracks all active agents and can kill them via `killAsyncAgent()`. The `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` environment variable disables background spawning entirely as a circuit breaker.

### Context Contamination

Each sub-agent gets `buildEffectiveSystemPrompt()` with its own injected context (working directory, memory files, teammate info). `runWithAgentContext()` and `runWithCwdOverride()` ensure that CWD and agent identity don't leak between siblings.

---

## The MCP Bridge

MCPTool represents a third architectural pattern alongside BashTool (leaf execution) and AgentTool (recursive orchestration): **external capability injection**. MCP servers register additional tools at runtime; `mcpClient.ts` overrides MCPTool's name, schema, and `call()` implementation with the real MCP server's definitions. From the model's perspective, these look identical to built-in tools.

This means the tool tree is not fixed: operators can extend it at deployment time without modifying the core codebase.

---

## Summary

| Component | Role in Composition |
|-----------|---------------------|
| `buildTool()` | Enforces uniform tool interface across all 40+ tools |
| `assembleToolPool()` | Dynamically constructs the tool set available to each agent |
| `AgentTool` | Branch node — creates recursive agent subtrees |
| `BashTool` | Leaf node — executes concrete OS actions |
| `MCPTool` | Extension point — injects operator-defined tools |
| Permission System | Safety layer at every branch/leaf boundary |
| Worktree isolation | Prevents concurrent agents from conflicting on shared state |
| Token tracking | Prevents unbounded resource consumption |

The architecture is best understood not as a flat list of tools, but as a recursive capability graph where Claude can dynamically compose any subset of the graph to solve a task.

---

## Cross-References

- [overview.md](overview.md) — system introduction
- [entity_bashtool.md](entity_bashtool.md) — primary leaf execution tool
- [entity_agenttool.md](entity_agenttool.md) — primary orchestration tool
- [concept_permissions.md](concept_permissions.md) — the safety layer governing all composition
- [index.md](index.md) — wiki navigation
- [schema.md](schema.md) — wiki conventions
