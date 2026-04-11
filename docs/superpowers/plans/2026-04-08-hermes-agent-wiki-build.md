# Hermes Agent Wiki Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new Hermes Agent peer wiki under `docs/hermes-agent-wiki/`, wire it into MkDocs, and populate it with depth-standard-compliant architecture pages grounded in the `hermes-agent/` source tree.

**Architecture:** Create the Hermes wiki as a peer sub-wiki with the same `schema / index / log / summaries / entities / concepts / syntheses / assets` shape used by the existing codebase wikis. Use `hermes-agent` source files plus the repo's own developer-guide docs as evidence anchors, write summaries first, then hub entities, then supporting pages, and finish with navigation wiring and MkDocs verification.

**Tech Stack:** MkDocs Material, Markdown, repo-local architecture wiki conventions, Hermes Agent source files and docs.

---

### Task 1: Scaffold plan targets and peer-wiki shell

**Files:**
- Create: `docs/hermes-agent-wiki/schema.md`
- Create: `docs/hermes-agent-wiki/index.md`
- Create: `docs/hermes-agent-wiki/log.md`
- Create: `docs/hermes-agent-wiki/assets/graphs/.gitkeep`
- Modify: `docs/index.md`
- Modify: `mkdocs.yml`

- [ ] **Step 1: Create the wiki directory shell**

```bash
mkdir -p docs/hermes-agent-wiki/assets/graphs \
         docs/hermes-agent-wiki/summaries \
         docs/hermes-agent-wiki/entities \
         docs/hermes-agent-wiki/concepts \
         docs/hermes-agent-wiki/syntheses
touch docs/hermes-agent-wiki/assets/graphs/.gitkeep
```

- [ ] **Step 2: Write the governance pages**

```markdown
# Hermes Agent Wiki Schema

> Governance document for the Hermes Agent Architecture Wiki.

## Identity
- Shared baseline: [Claude Code Depth Standard](../depth-standard.md)
- Purpose: document the `hermes-agent/` runtime, gateway, tool system, memory loop, and supporting surfaces.

## Operations
1. Ingest changed source files from `hermes-agent/`
2. Map them onto Hermes wiki pages
3. Update `index.md` and append to `log.md`
```

- [ ] **Step 3: Wire the new peer wiki into site navigation**

```markdown
| Hermes Agent | Architecture knowledge base for the `hermes-agent/` runtime platform | [Open Hermes Agent Wiki](hermes-agent-wiki/index.md) |
```

```yaml
  - Hermes Agent:
      - Index: hermes-agent-wiki/index.md
      - Summaries:
          - Architecture Overview: hermes-agent-wiki/summaries/architecture-overview.md
          - Codebase Map: hermes-agent-wiki/summaries/codebase-map.md
          - Glossary: hermes-agent-wiki/summaries/glossary.md
```

- [ ] **Step 4: Verify the shell exists**

Run: `find docs/hermes-agent-wiki -maxdepth 2 -type d | sort`
Expected: `assets`, `summaries`, `entities`, `concepts`, and `syntheses` directories all appear.

### Task 2: Write Hermes summary pages

**Files:**
- Create: `docs/hermes-agent-wiki/summaries/architecture-overview.md`
- Create: `docs/hermes-agent-wiki/summaries/codebase-map.md`
- Create: `docs/hermes-agent-wiki/summaries/glossary.md`
- Modify: `docs/hermes-agent-wiki/index.md`
- Modify: `docs/hermes-agent-wiki/log.md`

- [ ] **Step 1: Write `architecture-overview.md` as the narrative entry point**

```markdown
# Hermes Agent Architecture Overview

## Overview
Explain Hermes as a multi-surface agent product whose runtime center of gravity is `run_agent.py` plus prompt assembly, provider resolution, tool dispatch, session persistence, and long-running gateway/ACP/cron shells.

## Major Subsystems
Cover CLI, gateway, ACP, tool runtime, memory loop, session storage, skills, and research surfaces.

## Execution Model
Trace the path from entry points into `AIAgent.run_conversation()`, then out into providers, tools, storage, and background surfaces.
```

- [ ] **Step 2: Write `codebase-map.md` with concrete ownership mapping**

```markdown
## Top-Level Surfaces
| Path | Runtime Role | Primary Wiki Page |
|------|--------------|-------------------|
| `run_agent.py` | Core conversation loop | `../entities/agent-loop-runtime.md` |
| `hermes_cli/` | CLI and config runtime | `../entities/cli-runtime.md` |
| `gateway/` | Messaging control plane | `../entities/gateway-runtime.md` |
| `tools/` | Tool registry and backends | `../entities/tool-registry-and-dispatch.md` |
```

- [ ] **Step 3: Write `glossary.md` with stable Hermes vocabulary**

```markdown
Include: `SOUL.md`, `HERMES_HOME`, toolset, API mode, ACP, Honcho, session lineage, compression, pairing, and gateway hook.
```

- [ ] **Step 4: Update the Hermes wiki index and log for the new summary pages**

Run: `rg -n "Architecture Overview|Codebase Map|Glossary" docs/hermes-agent-wiki/index.md docs/hermes-agent-wiki/log.md`
Expected: all three summary pages appear in the index and the log records the initial build scope.

### Task 3: Write hub entity pages first

**Files:**
- Create: `docs/hermes-agent-wiki/entities/agent-loop-runtime.md`
- Create: `docs/hermes-agent-wiki/entities/prompt-assembly-system.md`
- Create: `docs/hermes-agent-wiki/entities/provider-runtime.md`
- Create: `docs/hermes-agent-wiki/entities/tool-registry-and-dispatch.md`
- Create: `docs/hermes-agent-wiki/entities/memory-and-learning-loop.md`
- Create: `docs/hermes-agent-wiki/entities/session-storage.md`
- Create: `docs/hermes-agent-wiki/entities/cli-runtime.md`
- Create: `docs/hermes-agent-wiki/entities/gateway-runtime.md`

- [ ] **Step 1: Write `agent-loop-runtime.md` with signatures, lifecycle, and fallback behavior**

```markdown
Include `AIAgent.chat()` and `AIAgent.run_conversation()` as the center-of-gravity signatures, explain API-mode branching, tool-call loops, callback surfaces, budgets, compression triggers, and fallback provider activation.
```

- [ ] **Step 2: Write prompt, provider, and tool-runtime hub pages**

```markdown
`prompt-assembly-system.md`: cached vs ephemeral prompt layers, context-file priority, SOUL.md handling.
`provider-runtime.md`: provider resolution precedence, native Anthropic path, Codex Responses path, auxiliary routing.
`tool-registry-and-dispatch.md`: registration, discovery, toolset filtering, async bridging, dangerous-command approval.
```

- [ ] **Step 3: Write memory, session, CLI, and gateway hub pages**

```markdown
`memory-and-learning-loop.md`: memory manager, provider plugins, session search, skills improvement loop.
`session-storage.md`: SQLite schema, FTS5, lineage, contention handling.
`cli-runtime.md`: `hermes` entrypoint, config loading, setup flow, command registry, platform-specific CLI concerns.
`gateway-runtime.md`: session keys, authorization, running-agent guards, adapter architecture, delivery path.
```

- [ ] **Step 4: Verify hub-page contracts**

Run: `rg -n "^## (Overview|Key Types|Architecture|Runtime Behavior|Operational Flow|Source Files|See Also)" docs/hermes-agent-wiki/entities/*.md`
Expected: each hub page contains the required depth-standard sections or equivalent runtime-flow sections.

### Task 4: Write supporting entities and all concept pages

**Files:**
- Create: `docs/hermes-agent-wiki/entities/terminal-and-execution-environments.md`
- Create: `docs/hermes-agent-wiki/entities/skills-system.md`
- Create: `docs/hermes-agent-wiki/entities/config-and-profile-system.md`
- Create: `docs/hermes-agent-wiki/entities/messaging-platform-adapters.md`
- Create: `docs/hermes-agent-wiki/entities/cron-system.md`
- Create: `docs/hermes-agent-wiki/entities/plugin-and-memory-provider-system.md`
- Create: `docs/hermes-agent-wiki/entities/acp-adapter.md`
- Create: `docs/hermes-agent-wiki/entities/research-and-batch-surfaces.md`
- Create: `docs/hermes-agent-wiki/concepts/self-improving-agent-architecture.md`
- Create: `docs/hermes-agent-wiki/concepts/prompt-layering-and-cache-stability.md`
- Create: `docs/hermes-agent-wiki/concepts/toolset-based-capability-governance.md`
- Create: `docs/hermes-agent-wiki/concepts/multi-surface-session-continuity.md`
- Create: `docs/hermes-agent-wiki/concepts/environment-abstraction-for-agent-execution.md`
- Create: `docs/hermes-agent-wiki/concepts/cross-session-recall-and-memory-provider-pluggability.md`
- Create: `docs/hermes-agent-wiki/concepts/interruption-and-human-approval-flow.md`

- [ ] **Step 1: Write the remaining entity pages**

```markdown
Keep each entity page implementation-led: name concrete files, explain runtime ownership, and include source-file maps.
```

- [ ] **Step 2: Write concept pages with explicit mechanism and source evidence**

```markdown
Every concept page must contain:
- `## Overview`
- `## Mechanism`
- `## Involved Entities`
- `## Source Evidence`
- `## See Also`
```

- [ ] **Step 3: Update the Hermes index for the full entity/concept inventory**

Run: `rg -n "entities/|concepts/" docs/hermes-agent-wiki/index.md`
Expected: all Hermes entity and concept pages are listed with one-line descriptions.

### Task 5: Write synthesis pages and first-pass diagrams

**Files:**
- Create: `docs/hermes-agent-wiki/syntheses/cli-to-agent-loop-composition.md`
- Create: `docs/hermes-agent-wiki/syntheses/gateway-message-to-agent-reply-flow.md`
- Create: `docs/hermes-agent-wiki/syntheses/tool-call-execution-and-approval-pipeline.md`
- Create: `docs/hermes-agent-wiki/syntheses/compression-memory-and-session-search-loop.md`
- Create: `docs/hermes-agent-wiki/syntheses/cron-delivery-and-platform-routing.md`
- Create: `docs/hermes-agent-wiki/syntheses/acp-editor-session-bridge.md`
- Create: `docs/hermes-agent-wiki/assets/graphs/hermes-agent-architecture.excalidraw`
- Create: `docs/hermes-agent-wiki/assets/graphs/hermes-agent-architecture.png`
- Create: `docs/hermes-agent-wiki/assets/graphs/hermes-gateway-message-flow.excalidraw`
- Create: `docs/hermes-agent-wiki/assets/graphs/hermes-gateway-message-flow.png`
- Modify: `docs/hermes-agent-wiki/summaries/architecture-overview.md`
- Modify: `docs/hermes-agent-wiki/syntheses/gateway-message-to-agent-reply-flow.md`

- [ ] **Step 1: Write all synthesis pages with boundary handoffs**

```markdown
Each synthesis page must show where control, session state, approvals, or delivery ownership changes hands across Hermes subsystems.
```

- [ ] **Step 2: Create the architecture diagram if it materially improves the overview**

```markdown
Embed the rendered architecture image in `summaries/architecture-overview.md` and link the editable `.excalidraw` source from the page.
```

- [ ] **Step 3: Create the gateway message-flow diagram if it materially improves the synthesis**

```markdown
Embed the rendered message-flow image in `syntheses/gateway-message-to-agent-reply-flow.md` and link the editable `.excalidraw` source from the page.
```

- [ ] **Step 4: Verify synthesis-page contracts**

Run: `rg -n "^## (Overview|Systems Involved|Interaction Model|Key Interfaces|Source Evidence|See Also)" docs/hermes-agent-wiki/syntheses/*.md`
Expected: each synthesis page contains the required sections or an equivalent explicit interaction-model structure.

### Task 6: Final lint and MkDocs verification

**Files:**
- Modify: `docs/hermes-agent-wiki/index.md`
- Modify: `docs/hermes-agent-wiki/log.md`

- [ ] **Step 1: Append the final build details to `log.md`**

```markdown
Record the source areas read, pages created, and whether diagrams were created or deferred.
```

- [ ] **Step 2: Run structural checks**

Run: `find docs/hermes-agent-wiki -name '*.md' | sort`
Expected: schema, index, log, 3 summaries, 16 entities, 7 concepts, and 6 syntheses are present.

- [ ] **Step 3: Run the site build**

Run: `mkdocs build`
Expected: build succeeds; pre-existing warnings outside Hermes are acceptable, but the Hermes wiki must not introduce new broken-link failures.

- [ ] **Step 4: Spot-check section and link coverage**

Run: `rg -n "^## See Also" docs/hermes-agent-wiki/**/*.md`
Expected: every Hermes content page has `## See Also`.
