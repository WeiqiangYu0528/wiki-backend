# Hermes Agent Wiki Rewrite Design

> Rewrite the Hermes Agent wiki so it is readable, detailed, and stylistically consistent with the strongest Claude Code pages, starting with a four-page pilot.

## Context

The current Hermes Agent wiki is structurally correct but editorially weak. It has the right page taxonomy, the right page titles, and mostly correct architectural claims, but the reading experience is still too compressed. Pages often feel like high-density notes written for someone who already understands the system, not a knowledge base meant to teach a reader how Hermes actually works.

The strongest Claude Code pages do three things that the current Hermes pages do not do consistently:

1. They open with a mental model instead of a directory summary.
2. They walk the reader through runtime behavior in a step-by-step way.
3. They combine prose, tables, boundaries, and source evidence so the reader can both learn and verify.

The goal of this rewrite is not to make Hermes pages merely longer. The goal is to make them teach.

## Problem Statement

The current Hermes wiki has three major failures:

### Readability failure

Many pages compress several concepts into single paragraphs with minimal transition language. The result is technically dense but pedagogically weak. A reader can finish a page and still not feel confident about what the subsystem owns, why it exists, or how it behaves at runtime.

### Detail-shape failure

The pages contain facts, but the facts are not arranged in the order a human learns them. Important topics such as lifecycle, control flow, approval boundaries, special-case paths, and failure handling are usually present only as short mentions instead of fully explained mechanisms.

### Style consistency failure

The Hermes wiki uses the same overall structure as the other peer wikis, but it does not yet read like the mature Claude Code wiki. Some pages feel like quick inventories, some feel like short architecture notes, and some feel like source maps. The style does not yet read as one coherent handbook.

## Rewrite Goal

Rewrite Hermes Agent into a wiki that a new reader can actually learn from while still satisfying the needs of a more advanced reader who wants implementation detail.

The target style is a mixed mode:

- tutorial-shaped opening sections that explain why a subsystem matters and how to think about it
- reference-shaped middle sections that define key types, boundaries, runtime flow, and source anchors
- strong cross-linking so readers can follow the architecture through neighboring pages

## Scope

This rewrite starts with a pilot rather than a full-site rewrite.

### Pilot pages

The pilot focuses on these four hub pages:

- `docs/hermes-agent-wiki/summaries/architecture-overview.md`
- `docs/hermes-agent-wiki/entities/agent-loop-runtime.md`
- `docs/hermes-agent-wiki/entities/gateway-runtime.md`
- `docs/hermes-agent-wiki/entities/tool-registry-and-dispatch.md`

These pages were selected because together they define the reader's first mental model of Hermes:

- overall system shape
- runtime execution core
- long-running messaging shell
- model-visible capability surface

If these four pages become clear, detailed, and stylistically consistent, the rest of the Hermes wiki can be normalized around them.

### Out of scope for the pilot

The pilot does not yet rewrite every Hermes page. It also does not add broad new page coverage or large-scale diagram work. The point of the pilot is to prove the target writing standard before scaling it.

## Chosen Approach

The rewrite will use a mixed tutorial/reference format instead of either of these extremes:

- pure tutorial pages that are pleasant to read but too light on source evidence
- pure reference pages that are fact-dense but hard to learn from

This mixed approach is the closest fit to the best Claude Code pages and is the right fit for a knowledge base that must serve both newcomers and future agents.

## Page Contract for the Pilot

Every pilot page must follow the same editorial contract.

### 1. Opening orientation

Each page starts by answering these questions in plain language:

- what subsystem or mechanism is this page about
- why does it exist
- why does the reader need to understand it
- what other parts of Hermes depend on it

This opening should be readable even if the user has not read the rest of the wiki.

### 2. Ownership boundaries

Each page must state what the subsystem owns and what it deliberately does not own. This prevents overlapping pages from repeating the same claims in slightly different wording.

### 3. Structured artifact

Each page must contain at least one strong structured teaching artifact:

- a key types table
- a key function or signature block
- a lifecycle or interaction list
- a boundary table

The artifact should reduce ambiguity rather than just restating prose.

### 4. Runtime mechanism

Each page must explain the order of operations. A reader should be able to follow an input through the subsystem, not just read a list of responsibilities.

### 5. Source evidence

Each page must name the concrete files and implementation anchors that support the explanation. Source paths should be specific and meaningful, not vague directory references.

### 6. Reader guidance

Each page must help the reader continue learning. Links should appear in the body where useful, not only in `See Also`.

## Page-Specific Rewrite Designs

### `architecture-overview.md`

This page will stop acting like a guided directory and start acting like a system-entry page.

It will be rewritten to cover:

1. what Hermes is, and what it is not
2. how a request or message travels through the product
3. how runtime core, shells, persistence, tools, and memory fit together
4. why the repository looks larger than a single-agent CLI
5. how a newcomer should read the wiki

Its job is to establish the main mental model: Hermes is a shared agent runtime platform with multiple shells, not one chat surface with side features.

### `agent-loop-runtime.md`

This page becomes the primary implementation anchor for the entire Hermes wiki.

It will be rewritten to explain:

1. what `AIAgent` actually owns
2. the full `run_conversation()` lifecycle
3. where prompt assembly, provider formatting, tool dispatch, memory hooks, compression, persistence, and fallback enter the loop
4. which tools are intercepted by the agent loop and why
5. how callbacks, iteration budgets, and retries change runtime behavior
6. what shells prepare for the loop versus what the loop itself owns

This page should feel like a serious execution handbook, not a compressed overview.

### `gateway-runtime.md`

This page becomes the main explanation of Hermes as a long-running multi-platform shell.

It will be rewritten to explain:

1. how inbound platform events are normalized
2. how session keys and routing identities are built
3. how authorization and pairing work
4. how running-agent guards and interrupt-capable commands work
5. how delivery, hooks, and shell-specific behavior sit around `AIAgent`
6. why the gateway is not just "the CLI with bot adapters"

This page should teach the reader how Hermes behaves when it stops being a local chat loop and becomes a message-driven service.

### `tool-registry-and-dispatch.md`

This page becomes the main explanation of how Hermes constructs the model-visible capability surface.

It will be rewritten to explain:

1. how registration works
2. how discovery works
3. how toolsets and readiness checks govern visibility
4. how plugin and MCP expansion alter the tool surface
5. how normal tool dispatch differs from agent-level tool interception
6. where dangerous-command detection lives and why approval transport belongs to the calling surface

This page should make it obvious that "tools" in Hermes are not just helper functions but a governed capability layer.

## Index Changes for the Pilot

The current Hermes index is accurate but flat. It catalogs pages well but does not help a newcomer choose where to start.

The pilot will update `docs/hermes-agent-wiki/index.md` to include:

- a short explanation of what Hermes is
- a `Recommended Reading Paths` section
- one path for first-time readers
- one path for readers trying to understand runtime and messaging behavior

The existing summaries / entities / concepts / syntheses catalogs will remain, but the page will become an entry guide instead of only a directory.

## Style Rules

The rewritten pilot pages must follow these writing rules:

### Human-readable paragraphing

- shorter paragraphs
- fewer concepts per sentence
- explicit transition phrases between sections
- less stacked noun phrasing

### Explanation before compression

If a concept needs two sentences to become clear, write the two sentences. Do not compress five relationships into a single dense sentence only to save space.

### Consistent boundary language

Each page should use stable language such as:

- "owns"
- "prepares"
- "delegates"
- "intercepts"
- "persists"
- "routes"

This helps the wiki feel like one authored system rather than several disconnected summaries.

### Concrete, not generic

Avoid vague phrases such as "handles the runtime" or "manages context" unless the next sentence explains exactly how.

## Source Evidence Rules

The pilot pages should increase evidence density in a way that helps learning rather than cluttering the page.

Preferred evidence patterns:

- function or method names when they are central to the page
- file tables for important ownership anchors
- explicit lifecycle steps tied to actual modules
- references to developer-guide pages when they mirror code ownership

Evidence should support the explanation, not replace it.

## Diagram Policy

The pilot does not require a new diagram pass.

Reason:

- the current failure is primarily textual, not structural
- the user explicitly said the priority is how the markdown reads
- the right sequence is: fix the prose first, then decide whether diagrams still add value

Existing diagrams may remain embedded, but new diagram work is deferred until the text passes review.

## Verification Criteria

The pilot will be considered successful if the rewritten pages satisfy all of the following:

1. A reader can understand each page without already knowing the subsystem.
2. Each page teaches a runtime mechanism, not just a subsystem label.
3. Each page contains richer implementation evidence than the current version.
4. The four pages read as if they were written by the same author.
5. The index becomes a better entry point for humans, not only a page list.

## Risks and Mitigations

### Risk: pages become longer but not better

Mitigation:

- enforce explanation-first structure
- require runtime flow sections
- keep sentence density lower than the current Hermes drafts

### Risk: pages start overlapping too much

Mitigation:

- explicitly state boundaries
- keep each page focused on one ownership center
- use cross-links instead of restating every neighboring detail

### Risk: the pilot still feels different from Claude Code

Mitigation:

- keep Claude Code hub pages open during rewrite
- imitate their best traits, especially teaching-oriented openings and implementation-led middle sections
- avoid copying their wording or overfitting to their exact length

## Implementation Handoff

After this design is approved, the next step is to write a task-level implementation plan for the pilot rewrite. That plan should include:

- exact files to rewrite
- the target structure for each page
- verification steps for readability, consistency, and link integrity
- a subagent-friendly task breakdown so the rewrite can use parallel help where appropriate
