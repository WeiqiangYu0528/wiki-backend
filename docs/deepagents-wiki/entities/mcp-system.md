# MCP System

## Overview

MCP (Model Context Protocol) allows the CLI to connect to external tool servers and expose their capabilities as first-class LangChain tools available to the agent. The `mcp_tools.py` module owns the full lifecycle: discovering config files, validating server configurations, establishing connections (stdio subprocess or remote SSE/HTTP), and wrapping each discovered MCP tool as a `BaseTool` that the agent graph can call like any built-in tool.

Config files follow the Claude Desktop JSON format. Multiple files from user-level and project-level locations are merged, with later files taking precedence. Stdio servers in project-level configs require explicit trust approval before they are loaded.

---

## Key Types / Key Concepts

### MCP config schema

Config files must contain a top-level `mcpServers` key mapping server names to server config objects. Three transport types are supported:

```json
{
  "mcpServers": {
    "my-stdio-server": {
      "command": "npx",
      "args": ["-y", "@my-org/mcp-server"],
      "env": { "API_KEY": "..." }
    },
    "my-sse-server": {
      "type": "sse",
      "url": "https://my-mcp-host.example.com/sse",
      "headers": { "Authorization": "Bearer ..." }
    },
    "my-http-server": {
      "type": "http",
      "url": "https://my-mcp-host.example.com/mcp"
    }
  }
}
```

The `type` (or `transport`) field defaults to `"stdio"` when omitted. stdio servers require `command` (string) and accept optional `args` (list) and `env` (dict). SSE and HTTP servers require `url` (string) and accept optional `headers` (dict).

The project root `.mcp.json` example from the repo:

```json
{
  "mcpServers": {
    "docs-langchain": {
      "type": "http",
      "url": "https://docs.langchain.com/mcp"
    },
    "reference-langchain": {
      "type": "http",
      "url": "https://reference.langchain.com/mcp"
    }
  }
}
```

### `MCPServerInfo` and `MCPToolInfo`

Lightweight dataclasses returned alongside the loaded tools. `MCPServerInfo` captures the server name, transport type, and a list of `MCPToolInfo` entries (name and description for each tool). These are used by the CLI to display which MCP servers and tools are active in the current session.

### Config discovery — `discover_mcp_configs()`

Auto-discovers `.mcp.json` files from three locations in lowest-to-highest precedence order:

1. `~/.deepagents/.mcp.json` — user-level global config, always trusted
2. `<project-root>/.deepagents/.mcp.json` — project subdir config
3. `<project-root>/.mcp.json` — project root config (Claude Code compatible)

Project root is resolved from the `ProjectContext` when provided, otherwise via `find_project_root()`, falling back to `cwd`. All discovered files are merged by `merge_mcp_configs()`, with later (higher-precedence) entries overriding earlier ones when server names collide.

### Trust gating for project stdio servers

User-level configs are loaded without restriction. Project-level configs that contain stdio servers are subject to trust gating controlled by the `trust_project_mcp` parameter in `resolve_and_load_mcp_tools()`:

- `True`: all project stdio servers are allowed (flag or prompt approved)
- `False`: stdio servers are filtered out; remote-only (SSE/HTTP) servers in the same file are still loaded
- `None` (default): the persistent trust store is checked; fingerprint match allows, otherwise stdio servers are filtered with a warning

Remote-only project configs (no stdio servers) are always loaded without trust gating.

### Pre-flight health checks

Before opening sessions, `_load_tools_from_config()` runs transport-specific checks:

- **stdio**: `shutil.which(command)` — raises `RuntimeError` if the command is not on `PATH`
- **SSE/HTTP**: a lightweight `HEAD` request with a 2-second timeout — raises `RuntimeError` on DNS failure, connection refused, or timeout; HTTP 4xx/5xx responses are not treated as failures

All preflight errors are collected and reported together before any session is opened.

### Tool loading and naming

After connections are established, `load_mcp_tools(session, server_name=..., tool_name_prefix=True)` from `langchain-mcp-adapters` is called per server. Setting `tool_name_prefix=True` prepends the server name to each tool name, creating namespaced tool identifiers (e.g., `docs-langchain__search`). This prevents collisions when multiple MCP servers expose tools with the same base name.

The resulting `BaseTool` objects are appended to the agent's tool list alongside built-in tools.

### `MCPSessionManager`

Wraps an `AsyncExitStack` that keeps all stdio subprocess sessions alive across tool calls. Without persistent sessions, each stdio tool call would restart the subprocess, losing any in-process server state. `MCPSessionManager.cleanup()` must be called when the CLI session ends to terminate all child processes.

### Error handling

`load_mcp_config()` raises on invalid JSON, missing `mcpServers` key, empty server list, or invalid field types. The lenient wrapper `load_mcp_config_lenient()` used during auto-discovery returns `None` and logs a warning instead of raising, so a broken user-level config does not block session startup.

Tool-load failures (e.g., MCP server crashes during handshake) raise `RuntimeError` with a diagnostic message distinguishing stdio from SSE/HTTP causes. The manager's exit stack is closed before re-raising to avoid orphaned processes.

---

## Architecture

### Server connection lifecycle

```
discover_mcp_configs()
  → merge_mcp_configs()
    → trust-gate stdio servers
      → _load_tools_from_config()
          → preflight checks (PATH / HEAD request)
          → MultiServerMCPClient(connections)
          → per-server: client.session(name) → load_mcp_tools()
          → return (tools, MCPSessionManager, server_infos)
```

The `MCPSessionManager` holds the `AsyncExitStack` that keeps all sessions open. The CLI registers `manager.cleanup()` to run at session teardown.

### Tool naming / namespacing

Each tool name is `<server_name>__<tool_name>` (double underscore separator applied by `langchain-mcp-adapters` when `tool_name_prefix=True`). The agent sees these alongside built-in tools. No renaming or aliasing is applied after loading — the prefix is the canonical name throughout the agent's tool list.

### Integration into the agent tool list

`resolve_and_load_mcp_tools()` is called by the CLI runtime before `create_deep_agent()`. The returned `tools` list is concatenated with any user-supplied tools and passed to `create_deep_agent(tools=[...])`. MCP tools are indistinguishable from built-in tools at the graph level — they are all `BaseTool` instances registered in the same tool node.

The `no_mcp=True` flag short-circuits the entire system and returns an empty tool list, suitable for `--no-mcp` CLI flag support.

---

## Source Files

| File | Purpose |
|---|---|
| `libs/cli/deepagents_cli/mcp_tools.py` | Config loading and validation, auto-discovery, transport-specific health checks, `MultiServerMCPClient` setup, `MCPSessionManager`, tool loading and namespacing |
| `libs/cli/deepagents_cli/mcp_trust.py` | Persistent trust store for project-level stdio servers |
| `libs/cli/deepagents_cli/server_graph.py` | Server-mode MCP preload and integration (ACP server path) |
| `.mcp.json` (repo root) | Example project-level MCP config with two HTTP servers |

---

## See Also

- [CLI Runtime](cli-runtime.md)
- [Skills System](skills-system.md)
- [Batteries Included Agent Architecture](../concepts/batteries-included-agent-architecture.md)
