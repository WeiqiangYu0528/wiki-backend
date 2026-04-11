# Hermes Agent Wiki Schema

> Governance document for the Hermes Agent Architecture Wiki.
> Defines page contracts, source-reference rules, and maintenance workflow.

---

## Identity

- **Shared baseline:** [Claude Code Depth Standard](../depth-standard.md)
- **Name:** Hermes Agent Architecture Wiki
- **Purpose:** Document the `hermes-agent/` repository as a multi-surface agent platform spanning the CLI, gateway, ACP adapter, tool runtime, memory providers, session storage, cron automation, and research surfaces.
- **Created:** 2026-04-08

## Three-Layer Architecture

| Layer | Location | Owner | Mutability |
|------|----------|-------|------------|
| Raw Sources | `hermes-agent/` | Human-curated repository | Immutable by wiki operations |
| Wiki Pages | `summaries/`, `entities/`, `concepts/`, `syntheses/` | LLM-maintained documentation | Updated by build and ingest |
| Schema | This file plus `index.md` and `log.md` | Human + LLM | Updated deliberately |

## Page Types and Contracts

### Summary Pages

Summary pages establish the mental model for the rest of the wiki.

Required sections:

- `## Overview`
- `## Major Subsystems`
- `## Execution Model` or `## Technology Stack`
- `## Architectural Themes`
- `## Entry Points for Newcomers`
- `## See Also`

### Entity Pages

Entity pages document a concrete subsystem with stable ownership boundaries.

Required sections:

- `## Overview`
- `## Key Types` or `## Key Types / Key Concepts`
- `## Architecture`
- `## Runtime Behavior`, `## Operational Flow`, or `## Lifecycle`
- `## Source Files`
- `## See Also`

Entity pages should explain what the subsystem owns, how it composes with neighboring pages, and which source files prove the description.

### Concept Pages

Concept pages document a cross-cutting mechanism that spans multiple entities.

Required sections:

- `## Overview`
- `## Mechanism`
- `## Involved Entities`
- `## Source Evidence`
- `## See Also`

Concept pages should explain why the mechanism exists, what guarantees it provides, and what tradeoffs it introduces.

### Synthesis Pages

Synthesis pages describe higher-level behaviors formed by multiple entities working together.

Required sections:

- `## Overview`
- `## Systems Involved`
- `## Interaction Model`
- `## Key Interfaces`
- `## Source Evidence`
- `## See Also`

Synthesis pages should make ownership handoffs visible: where control, session state, policy, or delivery responsibility changes subsystems.

## Naming and Source Reference Rules

- File names use lowercase kebab case with `.md`.
- Page titles use Title Case.
- Source paths should be written as backtick-wrapped repo-relative paths such as `run_agent.py` or `gateway/run.py`.
- Prefer concrete files over wildcard pseudo-paths.
- First mention of a documented page should be linked when practical.

## Diagram Conventions

- Diagrams are optional and should only be created when they materially improve understanding over prose.
- Hermes diagrams live under `assets/graphs/`.
- Preferred editable source format is `.excalidraw`; rendered outputs should be `.png`.
- Pages that embed diagrams should also link the editable source file.

## Depth Expectations

This wiki follows the shared [Claude Code Depth Standard](../depth-standard.md).

In practice:

- summaries must explain the runtime spine, not just directory layout
- hub entity pages should include lifecycle or control-flow discussion plus concrete source maps
- concept and synthesis pages should include explicit `## Source Evidence`
- smaller pages may be shorter, but they still need mechanism, evidence, and cross-links

## Cross-Referencing Rules

- Every content page must end with `## See Also`.
- Hub pages should include at least 4 meaningful outbound links when practical.
- Entity pages should link to the concepts they implement and the syntheses they participate in.
- Concept pages should link back to the entity pages that realize the mechanism.
- Synthesis pages should link to all participating entities and concepts.
- The glossary should point readers toward the most explanatory page for each term.

## Operations

### Build

1. Explore the `hermes-agent/` repository and classify knowledge areas.
2. Create `schema.md`, `index.md`, and `log.md`.
3. Write summaries first.
4. Write hub entities before supporting entities.
5. Write concepts and syntheses after the relevant entity pages exist.
6. Create diagrams only for pages that clear the diagram gate.
7. Update the index and append to the log.
8. Run structural lint and a site build.

### Ingest

1. Scan changed files under `hermes-agent/`.
2. Map them to affected pages.
3. Update those pages in place and create new pages only for genuinely new knowledge areas.
4. Refresh diagrams only if the mechanism changed materially.
5. Update `index.md` and append to `log.md`.

### Query

1. Read Hermes wiki pages before raw sources.
2. Synthesize answers from linked summary, entity, concept, and synthesis pages.
3. Cite the wiki pages used.

### Lint

1. Verify required sections by page type.
2. Verify all internal markdown links resolve.
3. Verify every content page appears in `index.md`.
4. Verify cited source paths still exist in `hermes-agent/`.
5. Verify each content page has `## See Also`.

## See Also

- [Claude Code Depth Standard](../depth-standard.md)
- [Hermes Agent Wiki Index](index.md)
- [Hermes Agent Wiki Log](log.md)
- [Deep Agents Wiki Schema](../deepagents-wiki/schema.md)
