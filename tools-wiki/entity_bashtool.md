# Entity: BashTool

**Type:** Entity
**Source directory:** `tools/BashTool/`
**Primary file:** `BashTool.tsx`

---

## Purpose

BashTool is Claude Code's interface to the operating system shell. It executes arbitrary shell commands on behalf of the user and returns stdout/stderr output. It is the highest-risk tool in the system and consequently has the most elaborate security and permission infrastructure.

---

## File Structure

| File | Role |
|------|------|
| `BashTool.tsx` | Main tool definition — schema, `call()`, progress logic |
| `bashPermissions.ts` | Permission rule evaluation against configured allow/deny rules |
| `bashSecurity.ts` | AST-based static analysis blocking dangerous shell patterns |
| `commandSemantics.ts` | Classifies commands as read/search/list/write for UI collapsing |
| `readOnlyValidation.ts` | Enforces read-only mode constraints |
| `sedEditParser.ts` | Parses `sed -i` edit commands for structured display |
| `sedValidation.ts` | Validates sed commands before execution |
| `shouldUseSandbox.ts` | Decides whether to route execution through the sandbox adapter |
| `modeValidation.ts` | Cross-checks tool invocation against active mode (plan, etc.) |
| `pathValidation.ts` | Validates that paths in commands stay within allowed scope |
| `destructiveCommandWarning.ts` | Detects and warns about destructive commands (rm, etc.) |
| `prompt.ts` | System prompt text and timeout configuration |
| `toolName.ts` | Exports `BASH_TOOL_NAME = 'Bash'` |
| `commentLabel.ts` | Generates human-readable labels for command comments |
| `utils.ts` | Helpers: image detection, CWD reset, stderr formatting |
| `UI.tsx` | Ink/React components for terminal rendering |
| `BashToolResultMessage.tsx` | Renders tool result messages in conversation |

---

## Input Schema

```ts
z.object({
  command: z.string(),           // The shell command to run
  timeout: z.number().optional(), // Execution timeout in ms
  description: z.string().optional() // Human-readable summary
})
```

---

## Security Model

### 1. Static Pattern Blocking (bashSecurity.ts)

Before execution, the raw command string is checked against a blocklist of dangerous shell constructs:

- **Process substitution:** `<()`, `>()`, `=()`
- **Command substitution:** `$()`, `${}`, backticks
- **Zsh-specific attacks:** `zmodload`, `emulate`, `sysopen`, `sysread`, `syswrite`, `ztcp`
- **PowerShell syntax:** `<#` (defense-in-depth)

The check uses a tree-sitter AST parse where possible, falling back to regex pattern matching.

### 2. Permission Rules (bashPermissions.ts)

Each configured permission rule is evaluated against the parsed command. Rules use wildcard patterns (`matchWildcardPattern`) against the command prefix. The permission system returns one of:

- `allow` — proceed without prompting
- `ask` — prompt the user for confirmation
- `deny` — block execution entirely
- `passthrough` — defer to default behavior

An LLM-based classifier (`bashClassifier.ts` in `utils/permissions/`) can optionally classify commands when explicit rules do not match.

### 3. Sandbox Isolation (shouldUseSandbox.ts)

`shouldUseSandbox()` determines whether to route execution through the `SandboxManager` (macOS sandbox profiles). Sandbox mode restricts file system access and network access at the OS level.

### 4. Read-Only Validation (readOnlyValidation.ts)

When the session is in read-only mode, `checkReadOnlyConstraints()` rejects commands that would write to the file system.

---

## Command Categorization

BashTool categorizes commands for UI display purposes:

```ts
const BASH_SEARCH_COMMANDS = new Set(['find', 'grep', 'rg', 'ag', ...])
const BASH_READ_COMMANDS   = new Set(['cat', 'head', 'tail', 'jq', 'awk', ...])
const BASH_LIST_COMMANDS   = new Set(['ls', 'tree', 'du'])
const BASH_SILENT_COMMANDS = new Set(['mv', 'cp', 'rm', 'mkdir', ...])
```

The `isSearchOrReadBashCommand()` function walks the parsed pipeline and classifies it as read/search/list so the UI can collapse uninteresting output.

---

## Execution and Background Tasks

- Commands run via `exec()` from `utils/Shell.ts`
- Long-running commands auto-background after `ASSISTANT_BLOCKING_BUDGET_MS = 15_000 ms`
- `backgroundExistingForegroundTask()` moves an in-progress command to the background task queue
- Output is streamed through `EndTruncatingAccumulator` to respect `TOOL_SUMMARY_MAX_LENGTH`
- Image output is detected (`isImageOutput()`) and resized for display

---

## Git Integration

`trackGitOperations()` from `shared/gitOperationTracking.ts` is called after execution to detect when the command modifies git state, enabling the UI to show diffs.

---

## Cross-References

- [overview.md](overview.md) — system context
- [concept_permissions.md](concept_permissions.md) — permission system used by this tool
- [entity_agenttool.md](entity_agenttool.md) — AgentTool uses BashTool via `BASH_TOOL_NAME`
- [synthesis_composition.md](synthesis_composition.md) — how BashTool fits into multi-agent workflows
- [index.md](index.md) — wiki navigation
