# Monorepo Package Layering

## Overview

The deepagents repository is a `uv`-managed monorepo containing independently versioned Python packages arranged in a deliberate dependency hierarchy. Packages higher in the stack depend on packages lower in the stack, never the reverse. This separation lets library authors embed the SDK without pulling in CLI-only concerns (Textual, MCP adapters, sandbox integrations), lets the ACP adapter expose agents over a protocol without a TUI, and lets the evaluation suite test both layers together without coupling them to each other.

## Mechanism

### Package Dependency Graph

```
deepagents-evals (0.0.1)
  ├── deepagents-cli (0.0.34)
  │     ├── deepagents (0.5.0a4)   ← core SDK
  │     └── deepagents-acp (0.0.4)
  └── deepagents (0.5.0a4)

deepagents-acp (0.0.4)
  └── deepagents (0.5.0a4)
```

Each package pins its dependencies with bounded version ranges in its own `pyproject.toml`. In development, all cross-package references resolve to editable local paths via `[tool.uv.sources]`.

### `deepagents` — Core SDK (`libs/deepagents/`)

**Version:** `0.5.0a4` | **Build backend:** `setuptools`

The foundational agent harness. Exports `create_deep_agent()`, all middleware classes (`FilesystemMiddleware`, `AsyncSubAgentMiddleware`, `MemoryMiddleware`, `SkillsMiddleware`, `SubAgentMiddleware`), and backend protocols. Has no dependency on the CLI, TUI, or MCP layer.

Runtime dependencies are intentionally lean:

```toml
dependencies = [
    "langchain-core>=1.2.21,<2.0.0",
    "langsmith>=0.3.0",
    "langchain>=1.2.15,<2.0.0",
    "langchain-anthropic>=1.4.0,<2.0.0",
    "langchain-google-genai>=4.2.1,<5.0.0",
    "wcmatch",
]
```

Only Anthropic and Google GenAI are bundled as defaults. All other model providers are opt-in at the CLI layer or above.

### `deepagents-acp` — Agent Client Protocol Integration (`libs/acp/`)

**Version:** `0.0.4` | **Build backend:** `hatchling`

Wraps the `agent-client-protocol>=0.8.0` library around the core SDK, exposing agents as ACP-compatible servers. Depends on `deepagents` (editable path in dev, `deepagents-acp>=0.0.4` in the CLI's published metadata). This is a thin adapter: it adds protocol bridging and session lifecycle without a TUI.

### `deepagents-cli` — Terminal Interface (`libs/cli/`)

**Version:** `0.0.34` | **Build backend:** `hatchling`

The batteries-included coding agent TUI. Depends on `deepagents==0.4.11` (exact pin in published metadata; editable path in dev) and `deepagents-acp>=0.0.4`. Adds a large set of optional concerns:

| Category | Key packages |
|---|---|
| UI/Terminal | `textual>=8.0.0`, `rich>=14.0.0`, `prompt-toolkit>=3.0.52` |
| Model providers | Anthropic, Google GenAI, and OpenAI bundled; 16 more as optional extras (`bedrock`, `ollama`, `openrouter`, etc.) |
| Sandbox integrations | `langsmith[sandbox]`; `agentcore`, `daytona`, `modal`, `runloop` as optional extras |
| MCP | `langchain-mcp-adapters>=0.2.0` |
| Persistence | `langgraph-checkpoint-sqlite>=3.0.0`, `aiosqlite>=0.19.0` |
| Tools | `tavily-python>=0.7.21` |

Entry points:

```toml
[project.scripts]
deepagents = "deepagents_cli:cli_main"
deepagents-cli = "deepagents_cli:cli_main"
```

Partner sandbox packages (`langchain-daytona`, `langchain-modal`, `langchain-runloop`) are editable local paths during development:

```toml
[tool.uv.sources]
deepagents = { path = "../deepagents", editable = true }
langchain-daytona = { path = "../partners/daytona", editable = true }
langchain-modal = { path = "../partners/modal", editable = true }
langchain-runloop = { path = "../partners/runloop", editable = true }
```

### `deepagents-evals` — Evaluation Suite (`libs/evals/`)

**Version:** `0.0.1` | **Build backend:** hatchling

Depends on both `deepagents>=0.5.0` and `deepagents-cli` (no upper pin). Also pulls in `harbor>=0.1.12` for Terminal Bench 2.0 execution, `langsmith>=0.4.0` for tracing and test suite logging, and model provider packages for multi-provider eval runs. Optional `charts` extra adds `matplotlib` for radar chart generation.

## Why the Layering Exists

**SDK consumers get a small install.** A project that only needs `create_deep_agent()` installs fewer than ten packages. The TUI, MCP adapters, and sandbox drivers are absent.

**CLI consumers get everything pre-wired.** Installing `deepagents-cli` gives an immediately runnable agent with multi-model support, MCP, sandboxes, and session history—none of which requires configuration beyond API keys.

**ACP is a thin adapter layer.** The `deepagents-acp` package exposes agents over the Agent Client Protocol for editor integration (e.g., VS Code, Cursor) without touching the TUI or requiring CLI installation.

**Evals stay isolated.** The evaluation suite imports both layers but does not affect their public APIs. Evals can be excluded entirely from user installs.

## Release Strategy

Packages are versioned and published to PyPI independently. The SDK uses alpha pre-releases (`0.5.0a4`) while the CLI uses stable patch releases (`0.0.34`). The CLI pins the SDK to an exact version (`deepagents==0.4.11`) in its published metadata to prevent silent breakage from SDK alpha churn. The eval suite uses `>=` lower bounds only, tolerating SDK updates during active development.

## Involved Entities

- [Graph Factory](../entities/graph-factory.md) — `create_deep_agent` in the SDK layer
- [CLI Runtime](../entities/cli-runtime.md) — agent assembly and server bootstrapping in the CLI layer
- [ACP Server](../entities/acp-server.md) — the ACP adapter layer
- [Evals System](../entities/evals-system.md) — the evaluation layer

## Source Evidence

`libs/deepagents/pyproject.toml` — SDK version `0.5.0a4`, lean runtime dependencies, setuptools build backend.

`libs/cli/pyproject.toml` — CLI version `0.0.34`, `deepagents==0.4.11` pin, full optional extras for model providers and sandboxes, `[tool.uv.sources]` editable local paths.

`libs/acp/pyproject.toml` — ACP version `0.0.4`, `agent-client-protocol>=0.8.0` dependency, editable SDK source.

`libs/evals/pyproject.toml` — Evals version `0.0.1`, depends on both SDK and CLI, `harbor>=0.1.12` for benchmark execution.

## See Also

- [Filesystem-First Agent Configuration](filesystem-first-agent-configuration.md)
- [SDK to CLI Composition](../syntheses/sdk-to-cli-composition.md)
- [Agent Customization Surface](../syntheses/agent-customization-surface.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
