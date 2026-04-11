# Agent Runtime

## Overview

The agent runtime is the execution core that transforms OpenClaw from a messaging gateway into an AI assistant. It owns agent configuration resolution (`agent-scope.ts`), per-agent workspace directories, skill loading and filtering, bash/process tool creation, embedded Pi runner integration, subagent tracking, and the Anthropic API transport layer. Routing hands off a `ResolvedAgentRoute` to the agent runtime; the runtime resolves agent config, loads tools and skills, and launches a reply-generation loop that produces the assistant's output.

## Key Types

| Type | Source | Role |
|------|--------|------|
| `ResolvedAgentConfig` | `src/agents/agent-scope.ts` | Per-agent config resolved from `openclaw.yml` |
| `AgentEntry` | `src/agents/agent-scope.ts` | One entry from `cfg.agents.list` |
| `AnyAgentTool` | `src/agents/tools/common.ts` | Union type for all tools; extends `AgentTool<TParameters, TResult>` |
| `ToolInputError` | `src/agents/tools/common.ts` | Error class for malformed tool input (HTTP 400) |
| `ToolAuthorizationError` | `src/agents/tools/common.ts` | Authorization failure (HTTP 403) |
| `ActionGate<T>` | `src/agents/tools/common.ts` | Per-action permission flags — controls which tool operations are enabled |

### Agent Config Shape

```ts
// src/agents/agent-scope.ts
type ResolvedAgentConfig = {
  name?: string;
  workspace?: string;          // agent workspace directory
  agentDir?: string;           // agent config/skills directory
  model?: AgentEntry["model"];
  thinkingDefault?: boolean;
  verboseDefault?: boolean;
  reasoningDefault?: boolean;
  fastModeDefault?: boolean;
  skills?: AgentEntry["skills"]; // skill filter list
  memorySearch?: boolean;
  humanDelay?: AgentEntry["humanDelay"];
  heartbeat?: AgentEntry["heartbeat"];
  identity?: AgentEntry["identity"];
  groupChat?: AgentEntry["groupChat"];
  subagents?: AgentEntry["subagents"];
  sandbox?: AgentEntry["sandbox"];
  tools?: AgentEntry["tools"];
};
```

## Architecture

### Agent Resolution

`resolveDefaultAgentId(cfg)` returns the agent marked `default: true` in `openclaw.yml`, or the first agent entry if none is marked, or `"main"` if the list is empty. Multiple `default: true` entries log a warning and use the first.

`resolveSessionAgentIds({ sessionKey, config, agentId })` extracts the `agentId` from a structured session key (e.g., `agent:coder:discord:direct:...` → `agentId = "coder"`), with an explicit override taking precedence over the session key.

Agent directory resolution follows a priority chain in `src/agents/agent-paths.ts`:
1. `OPENCLAW_AGENT_DIR` env var (or legacy `PI_CODING_AGENT_DIR`)
2. `~/.openclaw/state/agents/<agentId>/agent/`

### Skill Filtering

Each agent can have an explicit `skills` filter list in config:

```ts
// src/agents/skills/agent-filter.ts
export function resolveEffectiveAgentSkillFilter(
  cfg: OpenClawConfig | undefined,
  agentId: string | undefined,
): string[] | undefined {
  // Per-agent skills win; fall back to cfg.agents.defaults.skills
}
```

An empty array means "no skills". `undefined` means "use global defaults". The filter is applied by `src/agents/skills/local-loader.ts` when loading skill markdown files from the agent's `skills/` directory.

### Skills System

Skills are markdown files (`*.md`) in `skills/`, `~/.openclaw/skills/`, or plugin-contributed paths, with YAML frontmatter:

```ts
// src/agents/skills/types.ts
export type OpenClawSkillMetadata = {
  always?: boolean;          // inject unconditionally into every prompt
  skillKey?: string;
  primaryEnv?: string;
  emoji?: string;
  os?: string[];
  requires?: {
    bins?: string[];         // must-have binaries
    anyBins?: string[];      // at-least-one-of binaries
    env?: string[];
    config?: string[];
  };
  install?: SkillInstallSpec[];  // auto-install specs: brew, npm, go, uv, download
};

export type SkillInvocationPolicy = {
  userInvocable: boolean;
  disableModelInvocation: boolean;
};
```

`SkillInstallSpec` supports installing skill prerequisites via `brew`, `node` (npm), `go`, `uv`, or direct `download`.

### Bash and Process Tools

The bash tool system (`src/agents/bash-tools.*`) is the primary execution surface. It splits across several files:

| File | Role |
|------|------|
| `bash-tools.exec.ts` | `execTool` — sandboxed command execution with approval integration |
| `bash-tools.process.ts` | `processTool` — long-running process management |
| `bash-tools.exec-host-gateway.ts` | Exec host adapter for gateway-side execution |
| `bash-tools.exec-host-node.ts` | Exec host adapter for node-host-side execution |
| `bash-tools.exec-approval-request.ts` | Sends approval prompts to the client before risky commands |
| `bash-tools.exec-approval-followup.ts` | Handles approval responses |

The `ExecApprovalManager` in `src/gateway/exec-approval-manager.ts` coordinates approval state across the gateway and paired node hosts.

### Anthropic Transport

The Anthropic API transport lives in `src/agents/anthropic-transport-stream.ts` and handles streaming responses from the Anthropic API. `src/agents/anthropic-payload-policy.ts` controls what fields are sent and logged, and `src/agents/api-key-rotation.ts` manages rotating API keys for high-throughput configurations.

### Subagent Registry

`src/agents/subagent-registry.ts` (initialized by `initSubagentRegistry()` in `server.impl.ts`) tracks running subagent sessions and their parent relationships. This enables the gateway to expose subagent depth (`getSubagentDepth()`) and terminate child sessions when a parent session ends.

### Embedded Pi Runner

`src/agents/pi-embedded-runner/` contains the "Pi mode" embedded agent runner — a lightweight runtime that runs directly in the gateway process instead of spawning external processes. `getActiveEmbeddedRunCount()` tracks how many embedded runs are active at any moment.

## Operational Flow

1. Routing resolves `ResolvedAgentRoute` with `agentId` and `sessionKey`.
2. `resolveSessionAgentIds()` confirms the agent to use.
3. `resolveAgentWorkspaceDir()` and `resolveOpenClawAgentDir()` locate the workspace.
4. Skills are loaded via `local-loader.ts` filtered by `resolveEffectiveAgentSkillFilter()`.
5. Tools are assembled — bash tools, process tools, channel tools, plugin tools.
6. The agent starts a reply loop: `anthropic-transport-stream.ts` streams the model response.
7. Tool calls dispatch to the appropriate tool handler; results feed back into the loop.
8. Completed reply is delivered through the outbound pipeline to the channel.

## Source Files

| File | Purpose |
|------|---------|
| `src/agents/agent-scope.ts` | Agent config resolution, `listAgentEntries`, `resolveDefaultAgentId`, `resolveSessionAgentIds` |
| `src/agents/agent-paths.ts` | Agent directory resolution; `resolveOpenClawAgentDir()` |
| `src/agents/tools/common.ts` | `AnyAgentTool`, `ToolInputError`, `ToolAuthorizationError`, `ActionGate<T>` |
| `src/agents/bash-tools.ts` | Bash tool barrel export |
| `src/agents/bash-tools.exec.ts` | `execTool` — sandboxed command execution |
| `src/agents/bash-tools.process.ts` | `processTool` — long-running process |
| `src/agents/bash-tools.exec-approval-request.ts` | Pre-execution approval prompts |
| `src/agents/skills/agent-filter.ts` | `resolveEffectiveAgentSkillFilter()` — per-agent skill filter |
| `src/agents/skills/frontmatter.ts` | Skill frontmatter parser |
| `src/agents/skills/types.ts` | `OpenClawSkillMetadata`, `SkillInvocationPolicy`, `SkillInstallSpec` |
| `src/agents/skills/local-loader.ts` | Loads skill markdown from disk |
| `src/agents/subagent-registry.ts` | Tracks running subagent sessions |
| `src/agents/anthropic-transport-stream.ts` | Anthropic API streaming transport |
| `src/agents/anthropic-payload-policy.ts` | Controls payload fields and logging |
| `src/agents/api-key-rotation.ts` | API key rotation for high-throughput use |
| `src/agents/pi-embedded-runner/` | Embedded Pi runtime (in-process agent execution) |

## See Also

- [Skills Platform](skills-platform.md) — skill discovery, metadata, and prompt injection
- [Plugin Platform](plugin-platform.md) — plugin-contributed tools and skill sources
- [Routing System](routing-system.md) — produces `ResolvedAgentRoute` consumed here
- [Node Host and Device Pairing](node-host-and-device-pairing.md) — remote execution host
- [Tool-Augmented Agent Execution](../concepts/tool-augmented-agent-execution.md)
- [Agent Customization Surface](../syntheses/extension-to-runtime-capability-flow.md)
