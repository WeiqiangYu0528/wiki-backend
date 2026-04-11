# Wiki Schema

This document defines the structure and conventions used throughout the Claude Code Tools wiki.

## Page Types

| Type | Description | Naming Convention |
|------|-------------|-------------------|
| `summary` | High-level overview of the entire system | `overview.md` |
| `entity` | Detailed documentation of a specific subsystem or tool | `entity_<name>.md` |
| `concept` | Explanation of a cross-cutting architectural idea | `concept_<name>.md` |
| `synthesis` | Analysis relating multiple subsystems or themes | `synthesis_<name>.md` |
| `index` | Navigation index for the wiki | `index.md` |
| `schema` | This document — defines wiki conventions | `schema.md` |
| `log` | Build log tracking analysis decisions | `log.md` |

## Cross-Reference Convention

All pages use markdown links to cross-reference each other. Links use relative paths within the wiki directory.

## Source

Source code analyzed: `/Users/weiqiangyu/Downloads/wiki/docs/claude_code/src/tools`

Language: TypeScript (`.ts`, `.tsx`)

## Entity Selection Criteria

Entity pages cover the two most architecturally significant subsystems identified by:
1. Breadth of functionality (number of sub-files)
2. Centrality to the overall system (referenced by other tools)
3. Complexity of permission and execution logic

Selected entities: **BashTool** and **AgentTool**

## Concept Selection

The concept page covers the **Permission System** — the cross-cutting architecture that governs all tool execution authorization.

## Synthesis

The synthesis page examines how **Tool Composition and the Agent-Tool Feedback Loop** enables the system's recursive multi-agent capabilities.

---

Related pages: [index.md](index.md) | [log.md](log.md) | [overview.md](overview.md)
