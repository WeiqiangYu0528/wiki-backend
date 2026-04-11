# Claude Code Depth Standard

> Shared content standard for architecture wikis in this knowledge base.
> Derived from the existing Claude Code wiki and used as the rewrite baseline for peer wikis.

---

## Purpose

This document defines what “Claude Code depth” means in practical terms. It is not a request for longer pages for their own sake. It is a structural standard for pages that explain how a codebase actually works: the key types, control flow, lifecycle, precedence rules, extension points, and source evidence needed for an implementer or future agent to reason about the system without constantly re-reading raw sources.

The standard exists because a shallow wiki quickly becomes an index of filenames, while a deep wiki compounds. A high-quality page should let a reader understand what a subsystem is, why it exists, how it behaves at runtime, and where in the repo to confirm the explanation.

## Baseline Characteristics

The existing Claude Code wiki establishes these baseline traits:

- pages are implementation-led, not marketing-led
- summaries are narrative entry points, not inventories
- entities explain internal structure and execution behavior, not just purpose
- concepts describe mechanism and guarantees, not just definitions
- syntheses explain composition across systems, not just that two systems are related
- source evidence is explicit and repeated throughout the page
- links form a graph dense enough that the reader can move from overview to subsystem to pattern without searching raw code

## Page Standards

### Summary Pages

Summary pages should orient a newcomer and establish the mental model for the rest of the wiki.

Expected sections:

- `## Overview`
- `## Major Subsystems`
- `## Execution Model` or `## Technology Stack` when useful
- `## Architectural Themes`
- `## Entry Points for Newcomers`
- `## See Also`

Quality expectations:

- explain how the system runs, not just what folders exist
- name the central coordinating modules or services
- link to every major entity page on first mention where practical
- include at least one structured list or table that helps the reader scan the system shape

### Entity Pages

Entity pages are the backbone of the wiki. They should explain one concrete subsystem in a way that helps a reader predict runtime behavior.

Expected sections:

- `## Overview`
- `## Key Types` or `## Key Types / Key Concepts`
- `## Architecture`
- `## Lifecycle`, `## Operational Flow`, `## Runtime Behavior`, or equivalent when relevant
- `## Source Files`
- `## See Also`

Quality expectations:

- describe what the subsystem owns versus what neighbors own
- call out extension points, precedence rules, or important variants when they affect behavior
- include at least one of:
  - type/interface table
  - signature block
  - structured lifecycle or precedence list
- include a non-trivial source-file map, not only one file unless the subsystem is truly tiny

### Concept Pages

Concept pages should capture cross-cutting mechanics that recur across multiple entities.

Expected sections:

- `## Overview`
- `## Mechanism`
- `## Involved Entities`
- `## Source Evidence`
- `## See Also`

Recommended additions:

- `## Why It Exists`
- `## Operational Implications`
- `## Invariants` or `## Boundaries`

Quality expectations:

- show the mechanism step by step
- explain why the pattern exists and what guarantee or tradeoff it provides
- cite multiple source locations or multiple participating entities where possible

### Synthesis Pages

Synthesis pages should explain how multiple systems compose into a higher-level behavior.

Expected sections:

- `## Overview`
- `## Systems Involved`
- `## Interaction Model`
- `## Key Interfaces`
- `## See Also`

Recommended additions:

- `## Source Evidence`
- `## Operational Consequences`
- `## Failure or Boundary Conditions`

Quality expectations:

- show the path across subsystem boundaries
- identify where control, state, or policy changes hands
- explain the “why this composition works” story, not just the participating names

## Evidence Density

Source evidence should be materially denser than a first-pass wiki.

Targets:

- name concrete files and modules, not only directories
- use code signatures when they meaningfully anchor the explanation
- prefer several specific sources per page over one generic folder reference
- avoid wildcard pseudo-paths such as ``src/foo/*`` or placeholder-style references

For concept and synthesis pages, `## Source Evidence` should normally exist explicitly.

## Depth Targets

These are working targets, not strict minimums:

| Page Type | Target Depth |
|-----------|--------------|
| Summaries | roughly 900-1400 words |
| Hub Entities | roughly 1200-2200 words |
| Smaller Entities | materially deeper than first-pass pages, often 500-1200 words |
| Concepts | roughly 800-1400 words |
| Syntheses | roughly 800-1400 words |

Shorter pages are acceptable when the subsystem is genuinely small, but they still need structure, evidence, and mechanism.

## Rewrite Heuristics

Use these heuristics when deepening a page:

### Add a Table When

- the page defines a stable set of types, commands, subsystems, or configuration fields
- the reader needs a fast scan of responsibilities or file ownership
- the subsystem exposes multiple variants with different behaviors

### Add a Signature Block When

- one function, type, or interface defines the center of gravity for the subsystem
- the signature makes configuration or extension points obvious
- the page would otherwise have to describe an API shape indirectly

### Add a Lifecycle or Flow Section When

- the subsystem has ordered runtime steps
- multiple modules participate in a request or event path
- initialization, resume, teardown, or delivery behavior matters to correctness

### Split Explanation Internally, Not Structurally, When

- the page is broad but the current site structure should remain stable
- one subsystem needs more room but should still live on a single page
- the right fix is better subsections, not more navigation entries

Good internal split patterns:

- startup vs steady-state vs teardown
- local vs remote paths
- sync vs async behavior
- host runtime vs adapter/plugin layer

## Acceptance Checklist

A page is close to this standard when:

- it explains behavior, not only purpose
- it includes explicit evidence from real source files
- it gives the reader enough structure to reason about runtime flow
- it links outward to related systems and patterns
- it would still be useful if the reader never opened the raw source during a first pass

## See Also

- [Claude Code Wiki Schema](claude-code/schema.md)
- [Deep Agents Wiki Schema](deepagents-wiki/schema.md)
- [OpenCode Wiki Schema](opencode-wiki/schema.md)
- [OpenClaw Wiki Schema](openclaw-wiki/schema.md)
