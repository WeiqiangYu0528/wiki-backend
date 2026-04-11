# Hermes Agent Remaining Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the remaining Hermes Agent wiki pages so the whole sub-wiki matches the readability, depth, and handbook-like style established by the pilot hub-page rewrite.

**Architecture:** Continue the Hermes rewrite in dependency order. First deepen the entity pages that sit immediately beside the rewritten hub pages. Then rewrite the remaining shell and support entities. After that, rewrite concepts and syntheses so they can assume stronger neighboring pages. Finish with index/log refresh and full-site Hermes verification.

**Tech Stack:** Markdown, MkDocs Material, `rg`, `sed`, `mkdocs`

---

### Task 1: Rewrite runtime-adjacent entity pages

**Files:**
- Modify: `docs/hermes-agent-wiki/entities/prompt-assembly-system.md`
- Modify: `docs/hermes-agent-wiki/entities/provider-runtime.md`
- Modify: `docs/hermes-agent-wiki/entities/session-storage.md`
- Modify: `docs/hermes-agent-wiki/entities/memory-and-learning-loop.md`
- Read: `hermes-agent/agent/prompt_builder.py`
- Read: `hermes-agent/agent/prompt_caching.py`
- Read: `hermes-agent/agent/model_metadata.py`
- Read: `hermes-agent/agent/auxiliary_client.py`
- Read: `hermes-agent/hermes_cli/runtime_provider.py`
- Read: `hermes-agent/hermes_state.py`
- Read: `hermes-agent/agent/memory_manager.py`
- Read: `hermes-agent/agent/memory_provider.py`
- Read: `hermes-agent/plugins/memory/*`
- Read: `hermes-agent/website/docs/developer-guide/prompt-assembly.md`
- Read: `hermes-agent/website/docs/developer-guide/provider-runtime.md`
- Read: `hermes-agent/website/docs/developer-guide/session-storage.md`

- [ ] **Step 1: Re-open the four current entity pages and confirm they are still shallow relative to the new hub pages**

Run:

```bash
sed -n '1,260p' docs/hermes-agent-wiki/entities/prompt-assembly-system.md
sed -n '1,260p' docs/hermes-agent-wiki/entities/provider-runtime.md
sed -n '1,260p' docs/hermes-agent-wiki/entities/session-storage.md
sed -n '1,260p' docs/hermes-agent-wiki/entities/memory-and-learning-loop.md
```

Expected:
- The pages are materially shorter and less explanatory than the rewritten hub pages.

- [ ] **Step 2: Re-open the source anchors before rewriting**

Run:

```bash
sed -n '1,320p' hermes-agent/website/docs/developer-guide/prompt-assembly.md
sed -n '1,320p' hermes-agent/website/docs/developer-guide/provider-runtime.md
sed -n '1,320p' hermes-agent/website/docs/developer-guide/session-storage.md
rg -n 'prompt|cache|SOUL|HERMES|AGENTS|CLAUDE' hermes-agent/agent/prompt_builder.py hermes-agent/agent/prompt_caching.py
rg -n 'provider|model|api_mode|fallback|aux' hermes-agent/hermes_cli/runtime_provider.py hermes-agent/agent/model_metadata.py hermes-agent/agent/auxiliary_client.py
rg -n 'session|fts|lineage|parent_session_id|summary' hermes-agent/hermes_state.py
rg -n 'memory|provider|search|nudge|skill' hermes-agent/agent/memory_manager.py hermes-agent/agent/memory_provider.py hermes-agent/plugins/memory/*
```

Expected:
- You have concrete implementation anchors for prompt layering, provider routing, session durability, and memory-provider behavior.

- [ ] **Step 3: Rewrite `prompt-assembly-system.md` as a mechanism page**

The page must explain:
- what prompt assembly owns
- stable vs ephemeral prompt layers
- filesystem sources and ordering
- cache-stability goals
- where shells can add overlays without becoming prompt owners

Expected:
- The page teaches how Hermes builds prompt context rather than only listing source files.

- [ ] **Step 4: Rewrite `provider-runtime.md` as a routing-and-fallback page**

The page must explain:
- model/provider selection
- API modes
- auxiliary clients
- fallback activation and runtime constraints
- what belongs to provider setup versus what belongs to the agent loop

Expected:
- A reader can understand how Hermes changes provider behavior without confusing it with prompt or tool behavior.

- [ ] **Step 5: Rewrite `session-storage.md` as a continuity and lineage page**

The page must explain:
- what the session DB stores
- replay, FTS, lineage, and post-compression continuation
- shell-facing session use versus storage internals
- why storage shapes runtime behavior before and after turns

Expected:
- The page reads as a continuity subsystem page, not only a SQLite note.

- [ ] **Step 6: Rewrite `memory-and-learning-loop.md` as a closed-loop behavior page**

The page must explain:
- built-in memory
- external memory providers
- session search and recall
- nudges / review / skill-improvement flow if present in sources
- why Hermes treats memory as a runtime behavior rather than an optional add-on

Expected:
- The page clearly connects memory, recall, and learning behaviors instead of summarizing them separately.

- [ ] **Step 7: Verify the four pages**

Run:

```bash
rg -n '^## ' docs/hermes-agent-wiki/entities/prompt-assembly-system.md docs/hermes-agent-wiki/entities/provider-runtime.md docs/hermes-agent-wiki/entities/session-storage.md docs/hermes-agent-wiki/entities/memory-and-learning-loop.md
```

Expected:
- Each page has a clear teaching structure with runtime/mechanism sections and `See Also`.

### Task 2: Rewrite remaining supporting entities and summaries

**Files:**
- Modify: `docs/hermes-agent-wiki/entities/cli-runtime.md`
- Modify: `docs/hermes-agent-wiki/entities/config-and-profile-system.md`
- Modify: `docs/hermes-agent-wiki/entities/messaging-platform-adapters.md`
- Modify: `docs/hermes-agent-wiki/entities/skills-system.md`
- Modify: `docs/hermes-agent-wiki/entities/terminal-and-execution-environments.md`
- Modify: `docs/hermes-agent-wiki/entities/plugin-and-memory-provider-system.md`
- Modify: `docs/hermes-agent-wiki/entities/acp-adapter.md`
- Modify: `docs/hermes-agent-wiki/entities/cron-system.md`
- Modify: `docs/hermes-agent-wiki/entities/research-and-batch-surfaces.md`
- Modify: `docs/hermes-agent-wiki/summaries/codebase-map.md`
- Modify: `docs/hermes-agent-wiki/summaries/glossary.md`

- [ ] **Step 1: Group the pages by role before rewriting**

Use this grouping:
- shell entry and configuration: `cli-runtime`, `config-and-profile-system`
- transport and execution surfaces: `messaging-platform-adapters`, `terminal-and-execution-environments`, `acp-adapter`, `cron-system`
- capability and extension surfaces: `skills-system`, `plugin-and-memory-provider-system`
- peripheral product surfaces: `research-and-batch-surfaces`
- orientation support: `codebase-map`, `glossary`

Expected:
- You know what each page teaches and how it differs from neighboring pages.

- [ ] **Step 2: Rewrite each entity page as a bounded subsystem page**

Every rewritten entity page must:
- open with what the subsystem is for
- state ownership boundaries
- contain at least one structured artifact
- explain runtime behavior or setup flow in order
- link back into the four pilot hub pages where appropriate

Expected:
- Supporting pages stop reading like mini-index entries and start reading like reusable subsystem references.

- [ ] **Step 3: Rewrite `codebase-map.md` as a guided source map**

The page must:
- keep the repo map function
- add “how to read this repo” guidance
- direct readers toward the strongest hub pages first

Expected:
- A newcomer can use the map to navigate Hermes instead of only reading a directory list.

- [ ] **Step 4: Rewrite `glossary.md` so the terms explain system behavior, not just definitions**

Expected:
- Important terms such as `SOUL.md`, pairing, toolset, lineage, ACP, and recall become more useful to humans reading the rest of the wiki.

- [ ] **Step 5: Verify all supporting pages still link cleanly**

Run:

```bash
rg -n '^## See Also' docs/hermes-agent-wiki/entities/*.md docs/hermes-agent-wiki/summaries/codebase-map.md docs/hermes-agent-wiki/summaries/glossary.md
```

Expected:
- Every updated supporting page retains `See Also`.

### Task 3: Rewrite Hermes concepts

**Files:**
- Modify: `docs/hermes-agent-wiki/concepts/self-improving-agent-architecture.md`
- Modify: `docs/hermes-agent-wiki/concepts/prompt-layering-and-cache-stability.md`
- Modify: `docs/hermes-agent-wiki/concepts/toolset-based-capability-governance.md`
- Modify: `docs/hermes-agent-wiki/concepts/multi-surface-session-continuity.md`
- Modify: `docs/hermes-agent-wiki/concepts/environment-abstraction-for-agent-execution.md`
- Modify: `docs/hermes-agent-wiki/concepts/cross-session-recall-and-memory-provider-pluggability.md`
- Modify: `docs/hermes-agent-wiki/concepts/interruption-and-human-approval-flow.md`

- [ ] **Step 1: Re-open the current concept pages and confirm that they are still definition-heavy and mechanism-light**

Expected:
- The concepts remain much shorter than the hub pages and need stepwise explanation.

- [ ] **Step 2: Rewrite each concept page so it explains one cross-cutting mechanism in order**

Every concept page must:
- start with the problem the concept solves
- explain the mechanism step by step
- name the entity pages that participate
- include `## Source Evidence`
- end with `## See Also`

Expected:
- The concept pages become bridges between entity pages instead of glossary-like notes.

- [ ] **Step 3: Verify concept-page structure**

Run:

```bash
rg -n '^## Source Evidence|^## See Also' docs/hermes-agent-wiki/concepts/*.md
```

Expected:
- Every concept page includes both required sections.

### Task 4: Rewrite Hermes syntheses

**Files:**
- Modify: `docs/hermes-agent-wiki/syntheses/cli-to-agent-loop-composition.md`
- Modify: `docs/hermes-agent-wiki/syntheses/gateway-message-to-agent-reply-flow.md`
- Modify: `docs/hermes-agent-wiki/syntheses/tool-call-execution-and-approval-pipeline.md`
- Modify: `docs/hermes-agent-wiki/syntheses/compression-memory-and-session-search-loop.md`
- Modify: `docs/hermes-agent-wiki/syntheses/cron-delivery-and-platform-routing.md`
- Modify: `docs/hermes-agent-wiki/syntheses/acp-editor-session-bridge.md`

- [ ] **Step 1: Rewrite each synthesis as a composition page, not a short recap**

Every synthesis page must:
- explain the systems involved
- walk the interaction in order
- highlight handoff boundaries
- include `## Source Evidence`
- end with `## See Also`

Expected:
- Syntheses become the best place to learn multi-system flows.

- [ ] **Step 2: Give extra attention to the two highest-value flow pages**

Prioritize detail in:
- `gateway-message-to-agent-reply-flow.md`
- `tool-call-execution-and-approval-pipeline.md`

Expected:
- These pages become strong end-to-end learning surfaces, not diagram captions.

- [ ] **Step 3: Verify synthesis-page structure**

Run:

```bash
rg -n '^## Source Evidence|^## See Also' docs/hermes-agent-wiki/syntheses/*.md
```

Expected:
- Every synthesis page includes both required sections.

### Task 5: Final Hermes verification and bookkeeping

**Files:**
- Modify: `docs/hermes-agent-wiki/index.md`
- Modify: `docs/hermes-agent-wiki/log.md`
- Verify: all Hermes markdown pages

- [ ] **Step 1: Refresh index metadata and reading paths if the page mix changed**

Expected:
- The Hermes index still routes newcomers toward the best pages first.

- [ ] **Step 2: Append a log entry for the phase-2 rewrite**

Expected:
- `log.md` records sources read, pages rewritten, and any diagrams deferred or retained.

- [ ] **Step 3: Run Hermes-level verification**

Run:

```bash
mkdocs build
```

Expected:
- Build completes successfully.
- Any remaining warnings should still be pre-existing warnings outside the new Hermes rewrite scope, or already-known non-nav plan/spec files.

- [ ] **Step 4: Do one final editorial pass across the rewritten Hermes pages**

Check for:
- inconsistent terminology
- hub pages that still feel denser than adjacent supporting pages
- concepts that restate entities without adding mechanism
- syntheses that summarize instead of composing

Expected:
- Hermes reads like one knowledge base rather than a mix of old and new writing styles.
