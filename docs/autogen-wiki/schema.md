# AutoGen Wiki Schema

> Governance document for the AutoGen architecture wiki.
> Defines page contracts, naming, source-reference style, and maintenance workflow.

---

## Identity

- **Shared baseline:** [Claude Code Depth Standard](../depth-standard.md)
- **Name:** AutoGen Architecture Wiki
- **Purpose:** Human-readable and machine-readable knowledge base documenting the `autogen/` repository across the Python framework stack, app surfaces, shared runtime protocols, and the parallel .NET ecosystem.
- **Created:** 2026-04-06

## Three-Layer Architecture

| Layer | Location | Owner | Mutability |
|-------|----------|-------|------------|
| **Raw Sources** | `autogen/` | Human-curated repository | Immutable by wiki operations |
| **Wiki Pages** | `summaries/`, `entities/`, `concepts/`, `syntheses/` | LLM-generated | Updated via ingest/query/lint |
| **Schema** | This file (`schema.md`) | Human + LLM co-maintained | Updated deliberately |

## Page Types & Templates

### Summary Pages (`summaries/`)

Summary pages orient the reader before they dive into subsystem pages.

Required sections:

- `## Overview`
- `## Major Subsystems`
- `## Execution Model` or `## Technology Stack`
- `## Architectural Themes`
- `## Entry Points for Newcomers`
- `## See Also`

### Entity Pages (`entities/`)

Entity pages document one stable subsystem, package family, runtime surface, or app boundary.

```markdown
# {Entity Name}

## Overview
What this subsystem owns and why it exists.

## Key Types
Important classes, protocols, config models, or contracts.

## Architecture
How the subsystem is organized internally and how it connects to neighbors.

## Runtime Behavior
Lifecycle, execution path, precedence rules, or failure behavior.

## Source Files
| File | Purpose |
|------|---------|
| path/to/file | description |

## See Also
- Related entities
- Related concepts
- Related syntheses
```

### Concept Pages (`concepts/`)

Concept pages capture patterns that span multiple entities.

```markdown
# {Concept Name}

## Overview
What the pattern is.

## Mechanism
How the pattern works in practice.

## Involved Entities
Which entity pages implement or rely on it.

## Source Evidence
Concrete files, docs, or contracts that prove the explanation.

## See Also
- Related entities, concepts, and syntheses
```

### Synthesis Pages (`syntheses/`)

Synthesis pages explain how multiple entities compose into a higher-level flow.

```markdown
# {Synthesis Name}

## Overview
What behavior this page explains.

## Systems Involved
- Linked entities

## Interaction Model
Control flow, state flow, and handoff boundaries.

## Key Interfaces
Protocols, abstractions, or runtime boundaries that make the composition work.

## See Also
- Related entities and concepts
```

## Naming Conventions

- **File names:** lowercase-kebab-case with `.md`
- **Page titles:** Title Case
- **Source references:** backtick-wrapped paths relative to `autogen/`
- **Hub pages:** identified in `log.md` and expected to be materially deeper than supporting pages

## Depth Expectations

This wiki follows the shared [Claude Code Depth Standard](../depth-standard.md).
In practice that means:

- summary pages explain the execution model and package layering, not only directory layout
- hub entity pages include concrete type tables, runtime flows, and multiple code references
- concept pages include explicit `## Source Evidence`
- synthesis pages identify where control or state changes owners across packages or runtimes
- smaller pages may be shorter, but they must still explain behavior rather than list files

## Cross-Referencing Rules

- All links use relative markdown paths.
- Every page must have `## See Also` with at least 2 outbound links.
- Hub pages should usually have at least 4 meaningful outbound links.
- First mention of a documented subsystem should be linked when practical.
- Concept pages link back to the entity pages that realize the concept.
- Synthesis pages link to every participating entity and the most relevant concepts.

## Diagram Conventions

- Store editable sources in `assets/graphs/`
- Use `.excalidraw` for architecture and mechanism diagrams
- Render `.png` next to the source file
- Embed diagrams only when they materially improve understanding over prose
- Preferred first-pass targets:
  - `summaries/architecture-overview.md`
  - `syntheses/distributed-agent-worker-lifecycle.md`

## Operations

### Build
1. Scan the source tree and identify major package layers, protocols, apps, and runtime owners
2. Create `schema.md`, `index.md`, and `log.md`
3. Write summary pages before entity pages
4. Write hub entities before supporting entities
5. Add diagrams only for pages that clear the diagram gate
6. Populate `index.md`, append to `log.md`, and run lint

### Ingest
1. Scan changed paths inside `autogen/`
2. Map changes onto existing pages
3. Update affected pages in place
4. Add pages only when a new knowledge area appears
5. Refresh diagrams only if the architecture or lifecycle explanation changed materially
6. Update `index.md` and append to `log.md`

### Query
1. Prefer wiki pages over raw sources
2. Use raw sources only when the wiki lacks needed detail
3. Cite the wiki pages used

### Lint
1. Verify required sections for each page type
2. Verify markdown links resolve
3. Verify every page appears in `index.md`
4. Verify cited source files still exist
5. Verify concept and synthesis pages include `## Source Evidence` where required
6. Verify pages explain mechanism or runtime behavior rather than just package inventory
