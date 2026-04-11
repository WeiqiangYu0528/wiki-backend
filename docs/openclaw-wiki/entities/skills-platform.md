# Skills Platform

## Overview

OpenClaw's skills platform delivers markdown-based capability bundles to agents. A skill is a directory containing a `SKILL.md` file with YAML frontmatter and a prose description of a capability; the agent runtime injects matching skills into the system prompt so the model knows what tools and behaviors are available. Skills also declare installation requirements (`brew`, `npm`, `go`, `uv`, or direct download), OS constraints, required binaries, and invocation policies that control whether the model or only the user can invoke them.

The platform has two parts: the runtime layer (`src/agents/skills/`) that loads, filters, and injects skills at agent startup; and the skills content library (`skills/`) that ships bundled skills for integrations like GitHub, Apple Notes, Gemini, Discord, ClaWHub, and dozens of others.

## Key Types

```ts
// src/agents/skills/types.ts
export type OpenClawSkillMetadata = {
  always?: boolean;          // inject unconditionally into every system prompt
  skillKey?: string;         // stable identifier for deduplication
  primaryEnv?: string;       // required env var the skill checks for
  emoji?: string;
  homepage?: string;
  os?: string[];             // restrict to specific OS platforms
  requires?: {
    bins?: string[];         // all of these binaries must exist
    anyBins?: string[];      // at least one of these must exist
    env?: string[];          // required env vars
    config?: string[];       // required config keys
  };
  install?: SkillInstallSpec[];
};

export type SkillInstallSpec = {
  id?: string;
  kind: "brew" | "node" | "go" | "uv" | "download";
  label?: string;
  bins?: string[];
  os?: string[];
  formula?: string;          // for brew
  package?: string;          // for npm
  module?: string;           // for go
  url?: string;              // for download
  archive?: string;
  extract?: boolean;
  stripComponents?: number;
  targetDir?: string;
};

export type SkillInvocationPolicy = {
  userInvocable: boolean;
  disableModelInvocation: boolean;
};
```

## Architecture

### Skill Discovery Sources

Skills are loaded from multiple sources in priority order:

| Source | Path | Description |
|--------|------|-------------|
| Workspace | `<agentDir>/skills/` | Per-agent workspace skills (highest precedence) |
| User | `~/.openclaw/skills/` | User-wide skills |
| Plugin | Plugin package `skills/` | Skills contributed by installed plugins |
| Bundled | `skills/` in repo | Shipped with OpenClaw; lowest-precedence source |

`src/agents/skills/local-loader.ts` handles filesystem loading. `src/agents/skills/plugin-skills.ts` collects plugin-contributed skills. `src/agents/skills/bundled-dir.ts` locates the bundled skills directory.

### Loading a Single Skill

The local loader looks for `SKILL.md` inside each subdirectory of a skills root:

```
skills/
  github/
    SKILL.md      ← loaded as the "github" skill
  apple-notes/
    SKILL.md
  ...
```

`loadSingleSkillDirectory()` in `local-loader.ts`:
1. Reads `SKILL.md` via `openVerifiedFileSync()` — symlinks are rejected for safety.
2. Parses YAML frontmatter with `parseFrontmatter()`.
3. Requires `name` and `description` to be non-empty.
4. Calls `resolveSkillInvocationPolicy()` to set `userInvocable` / `disableModelInvocation`.
5. Returns a `Skill` object with `filePath`, `baseDir`, `source` (origin label), and parsed metadata.

### Skill Filtering

Per-agent skill filters apply when the active agent has an explicit `skills` list in config:

```ts
// src/agents/skills/agent-filter.ts
export function resolveEffectiveAgentSkillFilter(
  cfg: OpenClawConfig,
  agentId: string,
): string[] | undefined;
```

- Returns `undefined` → use all available skills.
- Returns `[]` → no skills.
- Returns `["github", "coding-agent"]` → only those two skill names.

When per-agent skills are absent, the function falls back to `cfg.agents.defaults.skills`.

### Invocation Policy

Frontmatter fields `user-invocable: false` and `disable-model-invocation: true` produce a `SkillInvocationPolicy` that restricts who can trigger the skill. Skills marked `always: true` in frontmatter are injected regardless of whether the agent's model explicitly calls them.

### Requirement Checks

Before a skill is offered to the model, the runtime checks `requires.bins` (all must exist) and `requires.anyBins` (at least one must exist) using the node host's binary lookup. Skills whose requirements are not met are silently omitted from the prompt. This prevents broken capability references from confusing the model.

### Auto-Install

`SkillInstallSpec` entries specify how to satisfy binary requirements. The node host runner (`src/node-host/runner.ts`) calls `listRegisteredNodeHostCapsAndCommands()` which, when a skill's bins are missing, can trigger the install flow specified in the `install` array. Supported installers:

- `brew` — homebrew formula by name
- `node` — npm package spec
- `go` — Go module path
- `uv` — Python package (via uv)
- `download` — direct URL, optionally archived

### System Prompt Injection

Skills that pass requirement checks and invocation policy are serialized and injected into the agent's system prompt by `buildContextEngineSkillsBlock()` (or equivalent). The skill's `name`, `description`, and body text become available to the model as part of its capability context.

## Bundled Skills Library

The `skills/` directory ships integrations for:
- Developer tools: `github`, `gh-issues`, `coding-agent`
- Communication: `discord`, `bluebubbles`
- Productivity: `apple-notes`, `apple-reminders`, `bear-notes`
- AI services: `gemini`, `canvas`
- Utilities: `gifgrep`, `goplaces`, `healthcheck`, `blucli`
- ...and 30+ more

Each subdirectory is an independent skill with its own `SKILL.md`.

## Source Files

| File | Purpose |
|------|---------|
| `src/agents/skills/types.ts` | `OpenClawSkillMetadata`, `SkillInvocationPolicy`, `SkillInstallSpec` |
| `src/agents/skills/skill-contract.ts` | `Skill` type definition and `createSyntheticSourceInfo()` |
| `src/agents/skills/local-loader.ts` | Filesystem skill loader; `loadSingleSkillDirectory()` |
| `src/agents/skills/frontmatter.ts` | Parses YAML frontmatter; `resolveSkillInvocationPolicy()` |
| `src/agents/skills/agent-filter.ts` | `resolveEffectiveAgentSkillFilter()` — per-agent skill filter |
| `src/agents/skills/plugin-skills.ts` | Collects plugin-contributed skills |
| `src/agents/skills/bundled-dir.ts` | Locates the bundled skills directory |
| `src/agents/skills/source.ts` | `resolveSkillSource()` — source label normalization |
| `src/agents/skills/filter.ts` | `normalizeSkillFilter()` — filter list normalization |
| `src/agents/skills/refresh.ts` | `registerSkillsChangeListener()` — hot-reload on skill file changes |
| `src/agents/skills/runtime-config.ts` | Runtime skill config helpers |
| `skills/` | Bundled skill library (50+ integrations) |

## See Also

- [Agent Runtime](agent-runtime.md) — loads and injects skills at agent startup
- [Plugin Platform](plugin-platform.md) — plugins can contribute skill directories
- [Node Host and Device Pairing](node-host-and-device-pairing.md) — node host runs skill binary checks and installs
- [Filesystem-First Configuration](../concepts/filesystem-first-agent-configuration.md) — skills as filesystem-first capability delivery
- [Extension to Runtime Capability Flow](../syntheses/extension-to-runtime-capability-flow.md)
