# Wiki Schema

## Purpose

This document defines page templates, naming conventions, cross-referencing rules, and maintenance operations for the Claude Code Services wiki. Source: `/Users/weiqiangyu/Downloads/wiki/docs/claude_code/src/services`.

## Directory Structure

```
wiki/
├── schema.md          # This file — governance
├── index.md           # Master catalog of all pages
├── log.md             # Append-only operation log
├── summaries/         # High-level orientation
│   ├── overview.md
│   └── glossary.md
├── entities/          # Concrete services/subsystems
│   ├── api-service.md
│   ├── mcp-service.md
│   ├── analytics-service.md
│   ├── compact-service.md
│   └── oauth-service.md
├── concepts/          # Cross-cutting patterns
│   ├── async-event-queue.md
│   └── context-window-management.md
└── syntheses/         # How services compose
    └── request-lifecycle.md
```

## Page Templates

### Entity Page Template

```markdown
# {Entity Name}

## Overview
One-paragraph description.

## Key Types / Key Concepts
Core types, interfaces, or concepts with code blocks.

## Architecture
Internal structure and organization.

## Source Files
| File | Purpose |
|------|---------|
| path/to/file | description |

## See Also
- [Related Entity](../entities/related.md)
- [Related Concept](../concepts/related.md)
```

### Concept Page Template

```markdown
# {Concept Name}

## Overview
What this concept is and why it matters.

## Mechanism
How it works in practice.

## Involved Entities
Which entities implement or are governed by this concept.

## Source Evidence
Key source locations that demonstrate this concept.

## See Also
- Links to related pages
```

### Synthesis Page Template

```markdown
# {Synthesis Name}

## Overview
What interaction this synthesis describes.

## Systems Involved
- [Entity A](../entities/a.md)

## Interaction Model
How the systems compose.

## Key Interfaces
Types, functions, or protocols at system boundaries.

## See Also
- Links to all participating entities and related concepts
```

## Naming Conventions

- File names: `lowercase-kebab-case.md`
- Page titles: Title Case
- Internal links: relative markdown paths from the file's location

## Cross-Referencing Rules

- Every page must have `## See Also` with at least 2 outbound links
- First mention of any entity or concept in body text should be a link
- Entity pages link to concepts they implement and syntheses they participate in
- Concept pages link to all entities the concept discusses
- Synthesis pages link to every entity and concept being synthesized

## Operations

### Ingest
Re-read changed source files and update affected wiki pages. Append to `log.md`.

### Query
Read relevant wiki pages, synthesize an answer, cite wiki pages used.

### Lint
Check structural completeness, verify all internal links resolve, confirm every page has 2+ outbound See Also links.
