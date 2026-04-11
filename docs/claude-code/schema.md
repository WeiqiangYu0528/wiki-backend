# Wiki Schema

> Governance document for the Claude Code Architecture Wiki.
> Defines page types, templates, conventions, and maintenance workflows.

---

## Identity

- **Name:** Claude Code Architecture Wiki
- **Purpose:** Machine-readable and human-readable knowledge base documenting the Claude Code CLI application architecture, built from source analysis of ~1,884 TypeScript files.
- **Created:** 2026-04-06

## Three-Layer Architecture

| Layer | Location | Owner | Mutability |
|-------|----------|-------|------------|
| **Raw Sources** | `claude_code/` | Human-curated repository | Immutable by wiki operations |
| **Wiki Pages** | `claude-code/summaries/`, `claude-code/entities/`, `claude-code/concepts/`, `claude-code/syntheses/` | LLM-generated | Updated via ingest/query/lint |
| **Schema** | This file (`schema.md`) | Human + LLM co-maintained | Updated deliberately |

## Page Types & Templates

### Entity Pages (`entities/`)
Document a concrete, nameable system or subsystem in the codebase.

```markdown
# {Entity Name}

## Overview
One-paragraph description of what this system is and why it exists.

## Key Types
Type definitions with brief explanations. Use code blocks for signatures.

## Architecture
How this system is structured internally. Include diagrams where helpful.

## Source Files
Table of key source files with paths relative to `claude_code/src/`.

## See Also
- [Related Entity](entities/related.md)
- [Related Concept](concepts/related.md)
- [Related Synthesis](syntheses/related.md)
```

### Concept Pages (`concepts/`)
Document a cross-cutting pattern, principle, or mechanism.

```markdown
# {Concept Name}

## Overview
What this concept is and why it matters.

## Mechanism
How it works in practice. Include flow diagrams or step lists.

## Involved Entities
Which systems implement or are governed by this concept (with links).

## Source Evidence
Key source locations that demonstrate this concept.

## See Also
- Links to related concepts, entities, and syntheses
```

### Synthesis Pages (`syntheses/`)
Document how multiple systems interact to produce emergent behavior.

```markdown
# {Synthesis Name}

## Overview
What interaction this synthesis describes.

## Systems Involved
List of participating entities (with links).

## Interaction Model
How the systems compose. Include sequence diagrams or data flow descriptions.

## Key Interfaces
The types, functions, or protocols at system boundaries.

## See Also
- Links to all participating entities and related concepts
```

### Summary Pages (`summaries/`)
High-level overviews and reference material. Free-form structure with links throughout.

## Naming Conventions

- **File names:** lowercase-kebab-case with `.md` extension (e.g., `agent-system.md`)
- **Page titles:** Title Case (e.g., `# Agent System`)
- **Source references:** Backtick-wrapped paths relative to `claude_code/src/` (e.g., `tools/AgentTool/runAgent.ts`)

## Cross-Referencing Rules

- All links use **relative markdown paths** inside the `claude-code/` wiki: `[Tool System](../entities/tool-system.md)` from a summary/concept/synthesis page, or `[Tool System](entities/tool-system.md)` from the wiki index
- Every page must have a **See Also** section with **2+ outbound links**
- **First mention** of any entity or concept in body text should be an inline link
- Entity→Entity: link when one imports from or depends on another
- Entity→Concept: link when the entity implements or is governed by the concept
- Entity→Synthesis: link when the entity participates in the synthesis
- Concept→Entity: link to all entities the concept discusses
- Synthesis→Everything: link to every entity and concept being synthesized
- Glossary links to the most thorough page for each term

## Operations

### Ingest
**Trigger:** New source files are added or existing ones change.
**Process:**
1. Scan affected directories in `claude_code/src/`
2. Extract types, functions, module boundaries, import graphs
3. Update corresponding wiki pages, preserving template structure
4. Update `index.md` if new pages are created
5. Append entry to `log.md`

### Query
**Trigger:** A question about the codebase architecture.
**Process:**
1. Search wiki pages (not raw sources) for relevant information
2. Synthesize answer from multiple pages
3. Cite wiki pages used
4. Optionally file valuable results back as new pages

### Lint
**Trigger:** After batch updates or periodically.
**Checks:**
1. **Structural:** Every page has required sections per its template
2. **Links:** All internal markdown links resolve to existing files
3. **Index:** Every `.md` in wiki directories has an `index.md` entry
4. **Staleness:** Source file paths in backticks point to existing files
5. **Cross-refs:** Every page has 2+ outbound links
**Output:** Lint report appended to `log.md`
