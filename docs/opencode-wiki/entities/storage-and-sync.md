# Storage and Sync

## Overview

The OpenCode storage subsystem handles all persistence of project data, sessions, messages, and related entities. It evolved from a flat JSON file store to a SQLite database backed by drizzle-orm. A migration subsystem (`JsonMigration`) handles one-time conversion of legacy JSON files into the SQLite schema on first run. The `Storage` namespace provides a generic key-value interface over the JSON store (used during transition and for configuration data), while the `Database` namespace manages the SQLite connection and schema migrations for the primary database.

Both systems are initialized via the Effect runtime and participate in the `InstanceState` scoping so that database connections are properly managed per-workspace instance.

## Key Types

### `Storage.Interface`

The generic JSON storage interface, implemented under the `Storage` namespace in `src/storage/storage.ts`:

- `read<T>(key: string[])` — reads a stored JSON value by hierarchical key. Returns `Effect<T, Storage.Error>`.
- `write<T>(key: string[], content: T)` — serializes and persists a value.
- `update<T>(key: string[], fn: (draft: T) => void)` — atomic read-modify-write with a draft mutation function.
- `remove(key: string[])` — deletes a stored entry.
- `list(prefix: string[])` — enumerates all keys under a given prefix, returning `string[][]`.

Keys are hierarchical arrays that map directly to filesystem paths: `["session", "abc123"]` resolves to `session/abc123.json` under the storage root.

### `Storage.Service`

`Storage.Service` extends `ServiceMap.Service` with the tag `"@opencode/Storage"`. It is provided as an Effect layer and injected into services that need to read or write persistent data.

### `Storage.NotFoundError`

A `NamedError` subtype carrying `{ message }` returned when a `read()` call targets a key that has no corresponding file.

### `Storage.Error`

Union type of `AppFileSystem.Error | Storage.NotFoundError`, covering all error cases that can arise from storage operations.

### `JsonMigration.Progress`

A callback payload type for migration progress reporting:

```
{ current: number, total: number, label: string }
```

Used to display incremental progress during the potentially slow one-time JSON-to-SQLite migration.

### `Database.Path`

The resolved path to the SQLite database file. Resolution logic in `Database.getChannelPath()`:

- For `latest` and `beta` channels (and when `OPENCODE_DISABLE_CHANNEL_DB` is set): `$DATA_DIR/opencode.db`
- For other channels (e.g., named release channels): `$DATA_DIR/opencode-<channel>.db`

The `OPENCODE_DB` environment flag overrides all logic: `:memory:` enables an in-memory database, an absolute path is used directly, and a relative path is resolved under `$DATA_DIR`.

### `Database.Transaction`

Type alias for `SQLiteTransaction<"sync", void>`, used for synchronous transactions within drizzle-orm operations.

### `Database.Client`

Type alias for `SQLiteBunDatabase` (the drizzle-orm wrapper around Bun's built-in `bun:sqlite` driver).

## Architecture

### JSON File Store (`Storage`)

The JSON store uses the filesystem as a key-value store. Each key array maps to a `.json` file path under a configured root directory. The `Git` module is consulted when determining the storage root, allowing storage to be optionally rooted at the git repository root rather than the global data directory.

Four schema validators (using Effect `Schema`) are defined for the main stored entity types:

- `RootFile` — optionally carries a `path.root` override for the storage root
- `SessionFile` — minimal `{ id }` schema for session entries
- `MessageFile` — minimal `{ id }` schema for message entries
- `SummaryFile` — carries `{ id, projectID, summary: { diffs: [{ additions, deletions }] } }`

The `missing()` helper function normalizes ENOENT filesystem errors and Effect `NotFound` tagged errors to a common boolean, allowing `read()` to return `NotFoundError` regardless of the underlying OS error format.

An `RcMap` combined with `TxReentrantLock` provides safe concurrent access: multiple concurrent readers are allowed but writes are serialized per key.

### SQLite Database (`Database`)

The primary database uses `bun:sqlite` (Bun's native SQLite bindings) wrapped with `drizzle-orm/bun-sqlite`. Schema definitions live in dedicated `.sql.ts` files alongside their domain modules:

| Table | Schema File |
|---|---|
| `ProjectTable` | `src/project/project.sql.ts` |
| `SessionTable`, `MessageTable`, `PartTable`, `TodoTable`, `PermissionTable` | `src/session/session.sql.ts` |
| `SessionShareTable` | `src/share/share.sql.ts` |

The database is initialized via `init` imported from `#db` (a Bun build-time alias). The `migrate()` function from `drizzle-orm/bun-sqlite/migrator` runs schema migrations from a migrations journal. When bundled, migrations are embedded as `OPENCODE_MIGRATIONS` (a declared constant with `sql`, `timestamp`, and `name` fields per entry).

### `JsonMigration.run()`

`JsonMigration.run(sqlite, options?)` is the one-time migration function that moves legacy JSON storage into SQLite. It is called during startup if the legacy storage directory exists. The migration:

1. Detects the storage directory at `$DATA_DIR/storage`. If absent, returns immediately with zero counts.
2. Opens a drizzle connection over the provided `sqlite` handle.
3. Sets SQLite performance pragmas for bulk insert: WAL journal mode, synchronous OFF, large cache, in-memory temp store.
4. Scans the storage directory using `Glob.scan()` for all entity files across projects, sessions, messages, parts, todos, permissions, and shares.
5. Processes files in batches of 1000 to limit memory pressure.
6. Calls `options.progress()` callback with `{ current, total, label }` after each batch so the TUI or CLI can show a progress indicator.
7. Tracks orphan records (sessions/todos/permissions/shares with no parent project/session) and logs them without failing.
8. Returns a stats object with counts of migrated rows and a list of error strings for records that could not be parsed.

The migration is idempotent: the database schema uses `INSERT OR IGNORE` patterns so re-running the migration on already-migrated data is safe.

### Migration Marker

The database file path itself serves as the migration marker. When `JsonMigration.run()` completes successfully, subsequent starts detect the SQLite database at `$DATA_DIR/opencode.db` (or the channel-specific path) and skip the migration. The legacy `data/storage/` JSON directory is not deleted automatically — users can remove it manually after confirming the migration succeeded.

## Runtime Behavior

### Startup Sequence

1. `Database.Path` is resolved once (lazily via `iife`) at module load time.
2. At runtime initialization, the `bun:sqlite` `Database` is opened at `Database.Path`.
3. `migrate()` runs schema migrations from the embedded journal.
4. `JsonMigration.run()` is called if the legacy storage directory exists, with a progress callback that feeds into the CLI loading indicator.
5. The `Storage.Service` layer is initialized with the resolved data directory.

### Concurrency Safety

The JSON store's `update()` operation uses `TxReentrantLock` to serialize writes on a per-key basis. This prevents lost updates when multiple concurrent Effect fibers attempt to modify the same JSON record. Reads are not locked, so they can observe stale data if a write is in progress.

The SQLite layer inherits Bun's WAL mode for concurrent read safety. All schema-level writes in the drizzle layer use explicit transactions.

### Namespacing

Storage keys are namespaced by entity type. Example key hierarchies:

- `["projects", "<projectID>"]` — project root record
- `["sessions", "<sessionID>"]` — session metadata
- `["sessions", "<sessionID>", "messages", "<messageID>"]` — individual message

This hierarchy maps directly to the filesystem path structure used by the legacy JSON store and is preserved in the SQLite migration for traceability.

### Remote Workspace Sync

For remote workspaces managed via the control plane, the storage layer writes to a local directory that is synchronized to the remote workspace's storage root. The `RootFile` schema's `path.root` field allows the storage root to be redirected to a different directory, which is used by the control plane to point storage at the remote-synchronized location.

## Source Files

- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/storage/storage.ts` — `Storage` namespace, `Interface`, `Service`, `NotFoundError`, JSON file store implementation
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/storage/db.ts` — `Database` namespace, `Database.Path`, `Database.Client`, `Database.Transaction`, migration runner, channel path logic
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/storage/json-migration.ts` — `JsonMigration.run()`, `Progress` type, batch processing, orphan tracking
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/project/project.sql.ts` — `ProjectTable` drizzle schema
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/session/session.sql.ts` — `SessionTable`, `MessageTable`, `PartTable`, `TodoTable`, `PermissionTable` drizzle schemas
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/share/share.sql.ts` — `SessionShareTable` drizzle schema

## See Also

- [Session System](./session-system.md) — sessions and messages are the primary consumers of the storage layer
- [Project and Instance System](./project-and-instance-system.md) — project records are stored via `ProjectTable`
- [Control Plane and Workspaces](./control-plane-and-workspaces.md) — remote workspaces redirect the storage root
- [CLI Runtime](./cli-runtime.md) — migration progress is displayed during startup
