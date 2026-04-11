# Context Compaction and Session Recovery

## Overview

This synthesis explains what happens when an OpenCode session's context window
fills up and how the system recovers to allow the conversation to continue. The
compaction mechanism creates a child session that inherits a compressed summary
of the parent, preserving the edit history (additions, deletions, file count,
diffs) without repeating the full message log. It also covers the revert path,
which allows a session to be restored to a known-good state identified by the
`revert` field on `Session.Info`.

Understanding this flow matters because compaction and recovery are silent
operations from the user's perspective — they happen inside the session layer
with no explicit user action. When they go wrong, the symptoms are subtle: a
model that "forgot" earlier context, a session title that unexpectedly changed,
or a restore that lands at the wrong message index. Knowing exactly which fields
are written and when allows an implementer to distinguish a compaction bug from
a provider bug or a client rendering bug.

## Systems Involved

| System | Contribution |
| --- | --- |
| [Session System](../entities/session-system.md) | Owns all `Session.Info` rows, compaction timestamps, child session creation, and revert pointers |
| [Storage and Sync](../entities/storage-and-sync.md) | SQLite persistence via `Database`; `SessionTable` schema with all compaction-related columns |
| [Provider System](../entities/provider-system.md) | Generates the compacted summary by asking the model to summarize the session |
| [Permission System](../entities/permission-system.md) | `Permission.Approval` records are scoped to `projectID`, not `sessionID`; inherited across sessions in same project |
| [Bus System](../entities/storage-and-sync.md) | Publishes `Session.Event.Updated` events when compaction state changes |

## Step-by-Step Flow

### 1. Context Limit Detected

During a model streaming turn, the AI SDK returns usage metadata
(`LanguageModelV2Usage`) with the token count for the current context window.
The session layer compares this against the model's declared context window
limit from the provider's model definition.

When the accumulated token count approaches the limit (within a configurable
threshold margin), compaction is triggered. The check occurs at the end of each
streaming turn, after the assistant's message is finalized but before the next
user prompt is processed.

The session layer also checks `Session.Info.time.compacting !== undefined`
before starting compaction. If `time_compacting` is already set, the session is
already compacting (or has completed a prior compaction); the new trigger is
skipped and the existing child session is reused.

### 2. `time.compacting` Written

The session layer calls `Session.update(id, { time: { compacting: Date.now() } })`.
This writes the current Unix timestamp (milliseconds) to the `time_compacting`
column in `SessionTable`. The `toRow(info)` mapping serializes
`info.time.compacting` to `time_compacting`.

This field serves two purposes:
- **Client signal**: The `Session.Event.Updated` Bus event delivers the updated
  `Session.Info` to all clients. The UI can show a "compacting..." indicator
  when `session.time.compacting` is non-null.
- **Concurrency lock**: Prevents two concurrent compaction attempts on the same
  session (the guard in step 1 checks this field).

### 3. Summary Generation

The session sends the full `MessageV2.WithParts[]` message history to the
provider with a compaction-specific system prompt from `SessionPrompt`. This
is a separate model call from the main conversation — it uses the same
`LanguageModelV3` object returned by `Provider.get`, but with a different
prompt template variant.

The model returns a structured summary that populates these fields on the
parent session's `SessionTable` row (written via `toRow`):
- `summary_additions: number` — net lines added across all file edits
- `summary_deletions: number` — net lines deleted across all file edits
- `summary_files: number` — count of distinct files touched
- `summary_diffs: Snapshot.FileDiff[] | undefined` — per-file diff snapshots
  for detailed history display

`Session.fromRow` reconstructs the `summary` object from these columns:
```
summary_additions !== null || summary_deletions !== null || summary_files !== null
  → { additions, deletions, files, diffs }
```
All three columns must be null for `summary` to be `undefined` on the Info object.

### 4. Child Session Creation

`Session.create({ parentID: currentSession.id, ... })` is called. The child
session row is inserted into `SessionTable` with:

- `parent_id`: the parent session's `id` (a ULID `SessionID`)
- `title`: produced by `createDefaultTitle(true)`:
  `"Child session - " + new Date().toISOString()`
- `workspace_id`: inherited from the parent (`session.workspaceID ?? null`)
- `directory`: inherited from the parent (`session.directory`)
- `project_id`: inherited from the parent (`session.projectID`)
- `version`: current schema version string
- `time_created`: current Unix ms timestamp
- All compaction fields start as `null`:
  `time_compacting`, `summary_*`, `revert`, `parent_id` on the *child's*
  children (the child is a leaf at creation time)

### 5. `isDefaultTitle` Detection

The function `Session.isDefaultTitle(title: string): boolean` tests whether a
session title matches the auto-generated pattern. Internally it uses:

```typescript
const regex = new RegExp(
  `^(${parentTitlePrefix}|${childTitlePrefix})` +
  `\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$`
)
return regex.test(title)
```

Where `parentTitlePrefix = "New session - "` and
`childTitlePrefix = "Child session - "`.

`isDefaultTitle` is used by:
- **UI session list**: decides whether to show the raw ISO timestamp or a
  localized placeholder label
- **Sort order**: auto-titled sessions sort below manually renamed sessions
- **Compaction logic**: may auto-rename the child session after the first turn
  produces a meaningful title

### 6. Child Session Inherits Summary

`SessionPrompt` in `session/prompt.ts` is called with the child `Session.Info`.
It detects that `parentID` is set and reads the parent's `summary` object via
a DB query for the parent row using `Session.fromRow`.

The summary is serialized into the child session's system prompt as a condensed
history preamble. This preamble appears before all other system-prompt content
and states something like:
> "The following is a summary of the prior conversation: N lines added,
> M lines deleted across K files. [optional diff narrative]"

The child session's `MessageV2` history starts fresh — no messages from the
parent are copied. But the model receives the summary as context, allowing it
to answer questions about prior work without replaying thousands of tokens.

### 7. Bus Events Published

Two `Session.Event.Updated` events fire in sequence:

1. `Bus.publish(Session.Event.Updated, updatedParent)` — the parent `Session.Info`
   with `time.compacting: number` (set) and `summary` populated.
2. `Bus.publish(Session.Event.Updated, newChild)` — the newly created child
   `Session.Info` with `parentID` set and an auto-generated title.

All connected clients receive these as SSE frames and update their session list:
- Parent shows "compacting" state (non-null `time.compacting`).
- Child appears as a new session entry, indented under the parent (client-side
  rendering uses `parentID` to build the tree).

### 8. Active Session Pointer Switches

After the child session is confirmed written to DB, the session layer switches
all subsequent prompt calls and message writes to use the child `SessionID`.

The parent's `time_compacting` column is left set as a permanent record of when
compaction occurred. Future calls to `Session.fromRow` on the parent row return
`time.compacting: number` (the epoch timestamp), which the UI renders as the
time compaction began rather than clearing it.

### 9. `Session.GlobalInfo` and Session List Rendering

The server API returns `Session.GlobalInfo` objects from `GET /session`:

```typescript
Session.GlobalInfo = Session.Info.extend({
  project: {
    id:       ProjectID,
    name:     string | undefined,
    worktree: string,
  } | null,
})
```

Clients use `parentID` to render child sessions as indented children in the
session tree. The `isDefaultTitle` predicate determines whether to render the
raw title string or a localized placeholder. Sessions with `time.compacting`
set display a spinner or "compacting" badge.

### 10. Revert Field and Recovery

The `revert` field on `Session.Info` enables checkpoint-based recovery:

```typescript
revert: {
  messageID: MessageID     // last "known good" message
  partID:    PartID | undefined
  snapshot:  string | undefined   // filesystem snapshot key
  diff:      string | undefined   // patch diff for display
} | undefined
```

`Session.fromRow` reads it as `row.revert ?? undefined`, where `row.revert` is
a JSON column in SQLite. On healthy sessions `revert` is `undefined`.

The recovery path:
1. Reads `session.revert` from `fromRow`.
2. Re-runs the session message query filtering to messages up to (but not
   including) `revert.messageID`.
3. Messages after that point are soft-deleted or excluded from the query.
4. If `revert.snapshot` is set, calls `Snapshot.restore(key)` to roll back
   the filesystem to the saved state.
5. The session is effectively truncated to the checkpoint.

### 11. Version Field and Schema Migration

The `version` field on `Session.Info` is a string tracking the schema version
of the session row. `updateSchema(row, migrations)` in `util/update-schema.ts`
runs column-level migrations when an older row is loaded by a newer binary.

Behavior on version mismatch:
- If a migration handler exists for the loaded version → migration applied;
  `version` updated in DB; session loads normally.
- If no handler exists → session is skipped in the session list load rather
  than crashing the entire list.

`version` is written at row creation time and updated by each applied migration.

### 12. Compaction Complete

Once the child session is confirmed written to DB, the session proceeds with
the child session ID for all subsequent turns. The compaction turn itself does
not produce a visible assistant message in the UI — it is an internal operation.
The next user message goes to the child session, and the model responds using
the injected summary as its starting context.

## Data at Each Boundary

| Boundary | Data Crossing | Key Types |
| --- | --- | --- |
| AI SDK → session layer (trigger) | Token usage from streaming turn | `LanguageModelV2Usage { promptTokens, completionTokens, totalTokens }` |
| Session layer → DB (compaction start) | Compaction lock timestamp | `time_compacting: number` via `toRow`; integer column in `SessionTable` |
| Session layer → provider (summary call) | Message history + compaction prompt | `MessageV2.WithParts[]`; compaction system prompt from `SessionPrompt` |
| Provider → session layer (summary result) | Structured summary from model | `{ additions: number, deletions: number, files: number, diffs: Snapshot.FileDiff[] \| undefined }` |
| Session layer → DB (summary write) | Summary columns update | `summary_additions`, `summary_deletions`, `summary_files`, `summary_diffs` via `toRow` |
| Session layer → DB (child create) | New session row | `parent_id: SessionID`, `title: "Child session - " + ISO`, inherited `directory`, `workspace_id`, `project_id`, `version` |
| Session layer → Bus (parent update) | Compaction state event | `Session.Event.Updated` with `Session.Info { time.compacting, summary }` |
| Session layer → Bus (child create) | New child session event | `Session.Event.Updated` with child `Session.Info { parentID, title }` |
| `SessionPrompt` → model (child turn) | Injected summary preamble | Serialized `summary` fields as text in child session system prompt |
| Recovery: DB → session layer | Revert checkpoint | `Session.Info.revert { messageID, partID?, snapshot?, diff? }` from `row.revert` JSON column |
| `updateSchema` → DB | Migration applied | Column updates on `SessionTable` rows with old `version` |

## Failure Points

| Stage | What Can Fail | Mechanism | Observable Symptom |
| --- | --- | --- | --- |
| Context limit detection | Token count not accurately tracked by AI SDK for the provider | `LanguageModelV2Usage` returns 0 or under-counted | Compaction triggers too late; model returns context-too-long error |
| `time_compacting` write | DB write fails (disk full, WAL lock timeout) | Drizzle update throws | Compaction not locked; concurrent compaction may be attempted |
| Summary generation | Provider returns malformed JSON or empty response | Model output parsing fails; `summary` not constructed | Child session starts with no context; behaves as fresh session |
| Summary generation | Provider API error during summary call | Provider throws or stream errors | Compaction aborted; parent stuck with `time_compacting` set |
| Child session creation | `SessionTable` insert fails (constraint, disk error) | Drizzle insert throws | Compaction aborted; no child session visible; parent stuck compacting |
| `createDefaultTitle(true)` | Clock skew gives identical millisecond timestamp | Two children with identical auto-title | Not a unique-key error (title is not unique-constrained) but confusing UI |
| `isDefaultTitle` false negative | Title has extra whitespace or encoding difference | Regex does not match valid auto-title | UI shows raw ISO timestamp; sort order wrong |
| Summary injection | `SessionPrompt` cannot find parent row (parent deleted concurrently) | `Session.fromRow` throws `NotFoundError` | Child model has no history context; behaves as fresh session |
| Revert field | `revert.messageID` points to a deleted or migrated message | Message query returns empty result | Recovery restores to wrong point or errors |
| Revert field | `revert.snapshot` key is stale (snapshot garbage-collected) | `Snapshot.restore` cannot find key | Filesystem rollback fails; message-level revert may still succeed |
| Version migration | `updateSchema` has no handler for the loaded version | Migration skipped; session skipped in list | User cannot access old session data without a binary downgrade |
| Bus publish during compaction | Client disconnects between parent-update and child-create events | `Bus.publish` iterates closed SSE connections | Client shows parent as compacting but child never appears; must refresh |
| `permission` field inheritance | Child session has `permission: null` but parent had session-level overrides | `fromRow` returns `permission: undefined` on child | Child uses only project-level rules, not parent's session-level overrides |

## Source Evidence

| File | Function / Symbol | Why It Matters |
| --- | --- | --- |
| `packages/opencode/src/session/index.ts` | `createDefaultTitle(isChild)`, `isDefaultTitle(title)`, `fromRow(row)`, `toRow(info)`, `Session.Info`, `Session.GlobalInfo` | All compaction field mappings; title prefix constants; revert and summary fields |
| `packages/opencode/src/session/prompt.ts` | `SessionPrompt` (variant selector) | Selects child vs. parent prompt variant; injects `summary` preamble |
| `packages/opencode/src/session/session.sql.ts` | `SessionTable` schema | All compaction columns: `time_compacting`, `summary_*`, `parent_id`, `revert`, `version` |
| `packages/opencode/src/storage/db.ts` | `Database`, `NotFoundError` | DB access layer; error type thrown when `fromRow` target not found |
| `packages/opencode/src/storage/storage.ts` | `Storage` interface, JSON migration helpers | JSON column serialization for `revert` and `summary_diffs` |
| `packages/opencode/src/util/update-schema.ts` | `updateSchema(row, migrations)` | Row-level version migration; skips sessions with unmigrated `version` |
| `packages/opencode/src/permission/index.ts` | `Permission.Approval { projectID, patterns }` | Approval scoped to `projectID`; inherited across all sessions in same project |
| `packages/opencode/src/bus/index.ts` | `Bus.publish(Session.Event.Updated, ...)` | Emits compaction state events to all connected clients |

## See Also

- [Session System](../entities/session-system.md)
- [Storage and Sync](../entities/storage-and-sync.md)
- [Provider System](../entities/provider-system.md)
- [Request to Session Execution Flow](request-to-session-execution-flow.md)
- [Provider Tool Plugin Interaction Model](provider-tool-plugin-interaction-model.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
