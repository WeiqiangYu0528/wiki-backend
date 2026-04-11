# Memory System

## Overview

The memory subsystem provides persistent knowledge across conversations. It encompasses CLAUDE.md memory files (per-project instructions), the memdir module (structured memory with types and relevance scoring), team memory sync, auto-memory extraction, session memory, and agent memory scopes with snapshots.

Memory is file-based and stored under `~/.claude/projects/<sanitized-project-root>/memory/`. The system distinguishes between user-managed instruction files (CLAUDE.md, rules) and auto-managed memory files (memdir, agent memory, session memory). Auto-memory is enabled by default but can be disabled via the `CLAUDE_CODE_DISABLE_AUTO_MEMORY` env var, the `autoMemoryEnabled` setting, or `--bare` mode.

## Key Components

### CLAUDE.md Memory Files

Project-level instructions loaded from multiple scopes (managed, user, project, local). These are user-managed and not part of the auto-memory system. See [Configuration System](configuration-system.md) for the load order.

### Memdir Module

Structured memory stored in `~/.claude/projects/<sanitized-project-root>/memory/`. The memdir module is the core of the auto-memory system, providing a four-type taxonomy for persistent, file-based memory that captures context not derivable from the current project state.

**Memory types** (defined in `memoryTypes.ts`):

| Type | Description | Scope |
|---|---|---|
| `user` | User role, goals, preferences, knowledge | Always private |
| `feedback` | Corrections and confirmed approaches from the user | Default private; team if project-wide convention |
| `project` | Ongoing work, goals, incidents, decisions not in code/git | Bias toward team |
| `reference` | Pointers to external systems (dashboards, Linear, Slack) | Usually team |

**MEMORY.md index file**: An entrypoint index loaded into the system prompt. Each entry is a one-line pointer (`- [Title](file.md) -- one-line hook`) to a topic file. Capped at 200 lines and 25,000 bytes; content beyond the cap is truncated with a warning. The index has no frontmatter and must not contain memory content directly.

**Memory file format**: Each memory is a standalone `.md` file with YAML frontmatter containing `name`, `description`, and `type` fields. The description is used for relevance scoring during retrieval.

**Relevance scoring** (`findRelevantMemories.ts`): At query time, all memory files are scanned for frontmatter headers (`scanMemoryFiles` in `memoryScan.ts`, capped at 200 files, sorted newest-first). A Sonnet side-query selects up to 5 relevant memories based on the user's query and each memory's filename plus description. Recently-used tool reference docs are deprioritized to avoid noise.

**Age management** (`memoryAge.ts`): Memories older than 1 day receive a staleness caveat in their output, warning that claims about code behavior or file:line citations may be outdated. The `memoryAge()` helper converts mtime to human-readable strings ("today", "yesterday", "N days ago") because models are poor at date arithmetic.

**Path resolution** (`paths.ts`): The auto-memory directory is resolved via a priority chain: (1) `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` env var, (2) `autoMemoryDirectory` in settings.json (trusted sources only -- policy, local, user; project settings excluded for security), (3) `<memoryBase>/projects/<sanitized-git-root>/memory/`. Git worktrees of the same repo share one memory directory via canonical git root resolution.

**Assistant daily-log mode** (feature `KAIROS`): Long-lived assistant sessions use append-only date-named log files (`logs/YYYY/MM/YYYY-MM-DD.md`) instead of maintaining MEMORY.md. A separate nightly `/dream` skill distills logs into topic files and MEMORY.md.

### Team Memory Sync

Synchronization of memories across team members via a server-side API. Team memory lives at `<autoMemPath>/team/` as a subdirectory of the auto-memory directory.

**Architecture**: A file watcher (`watcher.ts`) monitors the team memory directory for changes and triggers debounced pushes (2s debounce) to the server. On session startup, it performs an initial pull. The sync protocol uses versioned data with SHA-256 checksums, ETags for conditional requests, and optimistic concurrency with 412 conflict resolution.

**Security**: Path validation in `teamMemPaths.ts` includes symlink resolution (`realpathDeepestExisting`) to prevent traversal attacks, null byte injection detection, URL-encoded traversal detection, and Unicode normalization attack prevention. A `secretScanner.ts` (gitleaks-based) filters out files containing detected secrets before push.

**API contract** (`types.ts`): Flat key-value storage where keys are relative file paths and values are UTF-8 Markdown content. Supports `GET` (with ETag/304), `GET ?view=hashes` (metadata-only probe), and `PUT` (with precondition version). Server enforces entry count limits (413 with structured error body).

**Gating**: Team memory requires auto-memory to be enabled (`isTeamMemoryEnabled` checks `isAutoMemoryEnabled` first) and is controlled by the `tengu_herring_clock` feature flag.

### Auto-Memory Extraction

Automatic extraction of memories from conversations via a background forked subagent (`extractMemories.ts`). Runs once at the end of each complete query loop (when the model produces a final response with no tool calls).

**Forked agent pattern**: Uses `runForkedAgent` -- a perfect fork of the main conversation that shares the parent's prompt cache. The extraction agent has a restricted tool set: read-only tools (Read, Grep, Glob, read-only Bash) plus Edit/Write only within the memory directory. Limited to 5 turns. Turn throttling via `tengu_bramble_lintel` (default every 1 eligible turn).

**Mutual exclusion with main agent**: When the main agent writes memories itself (detected by `hasMemoryWritesSince`), the extraction agent skips that range and advances its cursor. This prevents duplicate memory writes.

**Coalescing**: If an extraction request arrives while one is in progress, the context is stashed for a trailing run after the current one finishes. Only the latest stashed context is kept.

**Prompts** (`prompts.ts`): The extraction prompt instructs the subagent to analyze the most recent N messages, provides the existing memory manifest (to avoid duplicates), and includes the full type taxonomy and save instructions. Separate prompts for auto-only and combined (auto + team) modes.

### Session Memory

Session Memory (`SessionMemory/`) automatically maintains a markdown file with notes about the current conversation. It runs periodically in the background using a forked subagent, separate from the cross-session memdir system.

**Trigger thresholds** (`sessionMemoryUtils.ts`): Extraction triggers when both a token-growth threshold (default 5,000 tokens since last extraction) and a tool-call threshold (default 3 calls) are met, or when the token threshold is met and the last assistant turn has no tool calls (natural conversation break). Initialization requires a minimum of 10,000 context window tokens.

**Tool restriction**: The session memory subagent can only use `FileEditTool` on the exact session memory file path. All other tools are denied.

**Integration with compaction**: Session memory is gated on auto-compact being enabled. The `lastSummarizedMessageId` tracks which messages have been summarized, enabling compaction to use session memory as a summary source.

### Agent Memory Scopes

Each agent definition can specify a `memory` field with one of three scopes: `user`, `project`, or `local`. Agent memory directories are separate from the main memdir and are identified by `isAgentMemoryPath()`. These memories persist across agent invocations and support snapshot-based bootstrapping for new agents.

## Source Files

| File | Description |
|---|---|
| `src/memdir/memdir.ts` | Core memory prompt building, MEMORY.md truncation, directory lifecycle |
| `src/memdir/memoryTypes.ts` | Four-type taxonomy (user, feedback, project, reference), frontmatter format |
| `src/memdir/findRelevantMemories.ts` | Query-time relevance scoring via Sonnet side-query |
| `src/memdir/memoryScan.ts` | Directory scanning, frontmatter parsing, manifest formatting |
| `src/memdir/memoryAge.ts` | Age computation and staleness caveats for recalled memories |
| `src/memdir/paths.ts` | Auto-memory path resolution, enable/disable gating, path validation |
| `src/memdir/teamMemPaths.ts` | Team memory path resolution, symlink-safe validation, containment checks |
| `src/memdir/teamMemPrompts.ts` | Combined (private + team) memory prompt builder |
| `src/services/extractMemories/extractMemories.ts` | Background memory extraction via forked agent, cursor management |
| `src/services/extractMemories/prompts.ts` | Extraction agent prompt templates (auto-only and combined modes) |
| `src/services/teamMemorySync/watcher.ts` | File watcher for team memory push, debounce, pull-on-startup |
| `src/services/teamMemorySync/index.ts` | Sync state management, pull/push operations |
| `src/services/teamMemorySync/types.ts` | Zod schemas and types for team memory API contract |
| `src/services/teamMemorySync/secretScanner.ts` | Gitleaks-based secret scanning for team memory push |
| `src/services/SessionMemory/sessionMemory.ts` | Session memory extraction hook, threshold-based triggering |
| `src/services/SessionMemory/sessionMemoryUtils.ts` | Configuration, threshold tracking, extraction state management |
| `src/services/SessionMemory/prompts.ts` | Session memory update prompt templates |
| `src/utils/memoryFileDetection.ts` | Path classification (auto-managed vs user-managed memory files) |
| `src/commands/memory/memory.tsx` | `/memory` command UI for editing memory files in external editor |
| `src/components/memory/MemoryFileSelector.tsx` | Memory file picker component |
| `src/components/memory/MemoryUpdateNotification.tsx` | Notification component for memory saves |

## See Also

- [Configuration System](configuration-system.md)
- [Agent System](agent-system.md)
- [State Management](state-management.md)
- [Session Lifecycle](../concepts/session-lifecycle.md)
