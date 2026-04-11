# OpenCode Wiki Schema

> Governance document for the OpenCode Architecture Wiki.
> Defines page types, naming rules, and maintenance workflow.

---

## Identity

- **Shared baseline:** [Claude Code Depth Standard](../depth-standard.md)

- **Name:** OpenCode Architecture Wiki
- **Purpose:** Human-readable and machine-readable knowledge base documenting the `opencode/` monorepo: core runtime, sessions, tools, providers, server, workspaces, plugins, and client surfaces.
- **Created:** 2026-04-06

## Three-Layer Architecture

| Layer | Location | Owner | Mutability |
|-------|----------|-------|------------|
| **Raw Sources** | `opencode/` | Human-curated repository | Immutable by wiki operations |
| **Wiki Pages** | `summaries/`, `entities/`, `concepts/`, `syntheses/` | LLM-generated | Updated via ingest/query/lint |
| **Schema** | This file (`schema.md`) | Human + LLM co-maintained | Updated deliberately |

## Page Types & Templates

### Entity Pages (`entities/`)
Document a concrete subsystem or package boundary in the OpenCode monorepo.

```markdown
# {Entity Name}

## Overview
What this subsystem is and why it exists.

## Key Types / Key Concepts
Important APIs, classes, schemas, or runtime concepts.

## Architecture
How the subsystem is structured internally and how it connects to neighbors.

## Source Files
| File | Purpose |
|------|---------|
| path/to/file | description |

## See Also
- [Related Entity](../entities/related.md)
- [Related Concept](../concepts/related.md)
- [Related Synthesis](../syntheses/related.md)
```

### Concept Pages (`concepts/`)
Document a cross-cutting pattern that spans multiple OpenCode entities.

```markdown
# {Concept Name}

## Overview
Why this pattern exists.

## Mechanism
How it works in practice.

## Involved Entities
Which entities implement or depend on it.

## Source Evidence
Key source files showing the pattern.

## See Also
- Related concepts, entities, and syntheses
```

### Synthesis Pages (`syntheses/`)
Document how multiple OpenCode systems compose into higher-level behavior.

```markdown
# {Synthesis Name}

## Overview
What composed behavior this page explains.

## Systems Involved
- Linked entities

## Interaction Model
Data flow, control flow, or lifecycle narrative.

## Key Interfaces
Boundary APIs and contracts.

## See Also
- Related entities and concepts
```

### Summary Pages (`summaries/`)
High-level orientation pages that link outward to the structural pages.

## Naming Conventions

- **File names:** lowercase-kebab-case with `.md`
- **Page titles:** Title Case
- **Source references:** backtick-wrapped paths relative to `opencode/`

## Depth Expectations

This wiki follows the shared [Claude Code Depth Standard](../depth-standard.md).
In practice that means:

- summaries should explain execution model and subsystem relationships, not only list folders
- entity pages should include implementation structure, runtime behavior, and a non-trivial source-file map
- concept pages should include mechanism plus explicit `## Source Evidence`
- synthesis pages should show where state, control, or policy changes hands across subsystems

## Cross-Referencing Rules

- All links use relative markdown paths.
- Every page must have `## See Also` with at least 2 outbound links.
- First mention of a documented entity or concept should be linked when practical.
- Entity pages link to the concepts they implement and the syntheses they participate in.
- Concept pages link back to all entities they discuss.
- Synthesis pages link to every participating entity and concept.
- Glossary terms link to the most explanatory page for that term.

## Operations

### Ingest
1. Scan changed paths inside `opencode/`
2. Map them onto existing entity, concept, or synthesis pages
3. Update affected pages while preserving structure
4. Add new pages only for genuinely new knowledge areas
5. Update `index.md` and append to `log.md`

### Query
1. Read relevant wiki pages rather than raw sources
2. Synthesize the answer from linked pages
3. Cite the wiki pages used

### Lint
1. Verify required sections exist
2. Verify markdown links resolve
3. Verify every page is listed in `index.md`
4. Verify cited source paths still exist
5. Verify each page has at least 2 outbound wiki links

