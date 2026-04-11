# Hermes Agent Pilot Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the Hermes Agent pilot hub pages so they are human-readable, implementation-led, and stylistically consistent with the strongest Claude Code pages.

**Architecture:** Rewrite four Hermes hub pages and the Hermes index in place. Each page should open with a reader-friendly mental model, move into concrete runtime behavior and ownership boundaries, and end with stronger cross-linking. The pages must read like one handbook rather than five isolated notes.

**Tech Stack:** Markdown, MkDocs Material, `rg`, `sed`, `mkdocs`

---

### Task 1: Rewrite `architecture-overview.md`

**Files:**
- Modify: `docs/hermes-agent-wiki/summaries/architecture-overview.md`
- Read: `docs/claude-code/summaries/architecture-overview.md`
- Read: `hermes-agent/website/docs/developer-guide/architecture.md`
- Read: `hermes-agent/website/docs/developer-guide/agent-loop.md`
- Read: `hermes-agent/website/docs/developer-guide/gateway-internals.md`

- [ ] **Step 1: Re-open the current Hermes and Claude Code overview pages**

Run:

```bash
sed -n '1,260p' docs/hermes-agent-wiki/summaries/architecture-overview.md
sed -n '1,260p' docs/claude-code/summaries/architecture-overview.md
```

Expected:
- The Hermes page reads shorter and more compressed than the Claude Code page.
- The Claude Code page demonstrates the target teaching density.

- [ ] **Step 2: Re-open the source architecture anchors before rewriting**

Run:

```bash
sed -n '1,260p' hermes-agent/website/docs/developer-guide/architecture.md
sed -n '1,260p' hermes-agent/website/docs/developer-guide/agent-loop.md
sed -n '1,260p' hermes-agent/website/docs/developer-guide/gateway-internals.md
```

Expected:
- You have concrete terminology for the runtime core, shell surfaces, and persistence model.

- [ ] **Step 3: Rewrite the page with the new teaching-first structure**

The rewritten page must use this section skeleton:

```md
# Hermes Agent Architecture Overview

## Overview
## Hermes In One Sentence
## Why The Repository Feels Larger Than A CLI Agent
## The Main Runtime Layers
## How A Request Moves Through Hermes
## Architectural Themes
## Reading Paths For Different Readers
## See Also
```

Content requirements:
- Explain that Hermes is a shared runtime platform with several shells.
- Contrast runtime core, shells, persistence/recall, and capability surface.
- Include at least one structured table covering major subsystems and ownership.
- Add a step-by-step “request moves through Hermes” section.
- Keep existing diagram embed only if it still supports the prose; do not add a new diagram in this task.

- [ ] **Step 4: Verify the rewritten page structure and link density**

Run:

```bash
rg -n '^## ' docs/hermes-agent-wiki/summaries/architecture-overview.md
rg -n '\]\(' docs/hermes-agent-wiki/summaries/architecture-overview.md | head -n 20
```

Expected:
- The page contains the new high-level sections.
- The page contains multiple meaningful wiki links in the body, not only in `See Also`.

- [ ] **Step 5: Sanity-check readability**

Read the rewritten page top-to-bottom and remove any paragraph that tries to explain more than one major idea at once.

Expected:
- The page can be read by a newcomer without needing the rest of the Hermes wiki first.

### Task 2: Rewrite `agent-loop-runtime.md`

**Files:**
- Modify: `docs/hermes-agent-wiki/entities/agent-loop-runtime.md`
- Read: `docs/claude-code/entities/agent-system.md`
- Read: `hermes-agent/run_agent.py`
- Read: `hermes-agent/website/docs/developer-guide/agent-loop.md`
- Read: `hermes-agent/agent/prompt_builder.py`
- Read: `hermes-agent/agent/context_compressor.py`
- Read: `hermes-agent/hermes_state.py`

- [ ] **Step 1: Re-open the current Hermes page and the Claude Code hub-page reference**

Run:

```bash
sed -n '1,320p' docs/hermes-agent-wiki/entities/agent-loop-runtime.md
sed -n '1,320p' docs/claude-code/entities/agent-system.md
```

Expected:
- The Claude page shows the desired combination of mental model, type detail, lifecycle, and boundary language.

- [ ] **Step 2: Re-open the runtime source anchors**

Run:

```bash
sed -n '1,320p' hermes-agent/website/docs/developer-guide/agent-loop.md
rg -n 'class AIAgent|def run_conversation|def chat|def _try_activate_fallback|IterationBudget' hermes-agent/run_agent.py
rg -n 'compress|summary|token' hermes-agent/agent/context_compressor.py
rg -n 'prompt|system' hermes-agent/agent/prompt_builder.py
rg -n 'save|session|fts|lineage' hermes-agent/hermes_state.py
```

Expected:
- You have concrete method names and adjacent modules to cite in the rewritten page.

- [ ] **Step 3: Replace the current page with a full runtime-handbook structure**

The rewritten page must use this section skeleton:

```md
# Agent Loop Runtime

## Overview
## What `AIAgent` Owns
## Key Types And Runtime Anchors
## Lifecycle Of `run_conversation()`
## Where Adjacent Subsystems Enter The Loop
## Special-Case Tool Paths
## Budgets, Fallback, Compression, And Failure Handling
## Ownership Boundaries
## Source Files
## See Also
```

Content requirements:
- Include a concrete table for key methods, collaborators, and why they matter.
- Walk the reader through `run_conversation()` in order.
- Explain where prompt assembly, providers, tools, memory, compression, and persistence enter.
- Explain agent-level intercepted tools separately from normal registry dispatch.
- Explicitly state what shells prepare for the loop versus what the loop itself owns.

- [ ] **Step 4: Verify that the page now contains runtime order, not only responsibilities**

Run:

```bash
rg -n 'Lifecycle|Ownership Boundaries|Special-Case Tool Paths|Fallback|Compression' docs/hermes-agent-wiki/entities/agent-loop-runtime.md
```

Expected:
- The page contains concrete lifecycle and boundary sections.

- [ ] **Step 5: Read the page once as a newcomer and remove any unexplained jargon in first mention**

Expected:
- A new reader can tell what `AIAgent` does before they need to know every helper module.

### Task 3: Rewrite `gateway-runtime.md`

**Files:**
- Modify: `docs/hermes-agent-wiki/entities/gateway-runtime.md`
- Read: `hermes-agent/gateway/run.py`
- Read: `hermes-agent/gateway/session.py`
- Read: `hermes-agent/gateway/delivery.py`
- Read: `hermes-agent/gateway/pairing.py`
- Read: `hermes-agent/website/docs/developer-guide/gateway-internals.md`

- [ ] **Step 1: Re-open the current gateway page and the gateway source anchors**

Run:

```bash
sed -n '1,280p' docs/hermes-agent-wiki/entities/gateway-runtime.md
sed -n '1,320p' hermes-agent/website/docs/developer-guide/gateway-internals.md
rg -n 'class GatewayRunner|handle|authorize|queue|interrupt|command' hermes-agent/gateway/run.py
rg -n 'session_key|build_session_key|SessionStore' hermes-agent/gateway/session.py
rg -n 'deliver|home channel|destination' hermes-agent/gateway/delivery.py
rg -n 'pair|authorize' hermes-agent/gateway/pairing.py
```

Expected:
- You have concrete evidence for ingress, session routing, authorization, and delivery.

- [ ] **Step 2: Rewrite the page so it explains Hermes as a long-running shell**

The rewritten page must use this section skeleton:

```md
# Gateway Runtime

## Overview
## Why The Gateway Exists
## Key Types And Ownership Anchors
## Inbound Message Lifecycle
## Authorization, Pairing, And Running-Agent Guards
## Delivery And Hook Surfaces
## Ownership Boundaries
## Source Files
## See Also
```

Content requirements:
- Explain that the gateway is a shell around `AIAgent`, not a duplicate runtime.
- Add a step-by-step inbound message lifecycle.
- Explain queueing, interrupts, and bypass-capable commands.
- Separate session identity from persistence concerns.
- State clearly what belongs to platform adapters, what belongs to gateway control flow, and what belongs to the agent loop.

- [ ] **Step 3: Verify that the new page teaches routing and guard behavior**

Run:

```bash
rg -n 'Inbound Message Lifecycle|Authorization|Pairing|Running-Agent|Delivery|Ownership Boundaries' docs/hermes-agent-wiki/entities/gateway-runtime.md
```

Expected:
- The page no longer reads like a short summary; it contains specific control-flow teaching sections.

- [ ] **Step 4: Read the page for false overlap with session-storage and messaging-platform-adapters**

Expected:
- The page explains gateway ownership without trying to re-document those adjacent subsystems in full.

### Task 4: Rewrite `tool-registry-and-dispatch.md`

**Files:**
- Modify: `docs/hermes-agent-wiki/entities/tool-registry-and-dispatch.md`
- Read: `hermes-agent/tools/registry.py`
- Read: `hermes-agent/model_tools.py`
- Read: `hermes-agent/tools/approval.py`
- Read: `hermes-agent/tools/terminal_tool.py`
- Read: `hermes-agent/website/docs/developer-guide/tools-runtime.md`

- [ ] **Step 1: Re-open the current page and the tool-runtime source anchors**

Run:

```bash
sed -n '1,320p' docs/hermes-agent-wiki/entities/tool-registry-and-dispatch.md
sed -n '1,320p' hermes-agent/website/docs/developer-guide/tools-runtime.md
rg -n 'class ToolRegistry|def register|def get_definitions|def dispatch' hermes-agent/tools/registry.py
rg -n 'discover|toolset|mcp|plugin|function call' hermes-agent/model_tools.py
rg -n 'dangerous|pattern|approve' hermes-agent/tools/approval.py
rg -n 'terminal|shell|environment' hermes-agent/tools/terminal_tool.py
```

Expected:
- You have concrete anchors for registration, discovery, filtering, dispatch, and approval gating.

- [ ] **Step 2: Rewrite the page as a capability-surface handbook**

The rewritten page must use this section skeleton:

```md
# Tool Registry and Dispatch

## Overview
## What The Tool Runtime Actually Owns
## Key Types And Registry Anchors
## How Hermes Builds The Model-Visible Tool Surface
## Normal Dispatch Path
## Agent-Level Special Cases
## Approval-Sensitive Terminal Execution
## Ownership Boundaries
## Source Files
## See Also
```

Content requirements:
- Explain the order of operations from registration through discovery to filtered exposure.
- Separate normal dispatch from agent-level intercepted tools.
- Explain why toolsets and readiness checks are governance mechanisms, not cosmetic filters.
- Make the approval boundary explicit: policy trigger in tool runtime, approval transport in the calling surface.

- [ ] **Step 3: Verify that the rewritten page has both a build path and an execution path**

Run:

```bash
rg -n 'model-visible tool surface|Normal Dispatch Path|Agent-Level Special Cases|Approval-Sensitive Terminal Execution|Ownership Boundaries' docs/hermes-agent-wiki/entities/tool-registry-and-dispatch.md
```

Expected:
- The page explains both how tools become visible and how they are executed.

- [ ] **Step 4: Remove any sentence that sounds like a generic plugin-tool summary**

Expected:
- The page reads like Hermes-specific runtime documentation, not a generic “tool registry” article.

### Task 5: Update `index.md` to act as an entry guide

**Files:**
- Modify: `docs/hermes-agent-wiki/index.md`

- [ ] **Step 1: Re-open the current Hermes index**

Run:

```bash
sed -n '1,260p' docs/hermes-agent-wiki/index.md
```

Expected:
- The page is accurate but mostly catalog-shaped.

- [ ] **Step 2: Add orientation and reading paths without removing the catalog**

The updated index must include:

```md
## What This Wiki Covers
## Recommended Reading Paths
### If You Are New To Hermes
### If You Want To Understand The Runtime And Messaging Surfaces
```

Content requirements:
- Keep the existing page tables.
- Add short guide text above the catalogs.
- Point the reading paths at the four pilot pages first.

- [ ] **Step 3: Verify that the index is still a complete catalog**

Run:

```bash
rg -n '^## ' docs/hermes-agent-wiki/index.md
```

Expected:
- The new orientation sections exist and the catalog sections are still present.

### Task 6: Run pilot-level verification

**Files:**
- Verify: `docs/hermes-agent-wiki/summaries/architecture-overview.md`
- Verify: `docs/hermes-agent-wiki/entities/agent-loop-runtime.md`
- Verify: `docs/hermes-agent-wiki/entities/gateway-runtime.md`
- Verify: `docs/hermes-agent-wiki/entities/tool-registry-and-dispatch.md`
- Verify: `docs/hermes-agent-wiki/index.md`

- [ ] **Step 1: Check required sections across the pilot files**

Run:

```bash
rg -n '^## ' docs/hermes-agent-wiki/summaries/architecture-overview.md docs/hermes-agent-wiki/entities/agent-loop-runtime.md docs/hermes-agent-wiki/entities/gateway-runtime.md docs/hermes-agent-wiki/entities/tool-registry-and-dispatch.md docs/hermes-agent-wiki/index.md
```

Expected:
- Every pilot page contains its planned sections.

- [ ] **Step 2: Build the MkDocs site**

Run:

```bash
mkdocs build
```

Expected:
- Build completes successfully.
- Pre-existing warnings elsewhere in the wiki may remain, but the Hermes pilot should not introduce new broken links.

- [ ] **Step 3: Do a final editorial pass across all five files**

Check for:
- paragraphs that are still too dense
- duplicated boundary explanations
- inconsistent terminology between pages
- missing body links to neighboring hub pages

Expected:
- The five files read like one coherent handbook slice rather than five disconnected rewrites.
