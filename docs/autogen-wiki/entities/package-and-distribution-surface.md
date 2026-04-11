# Package and Distribution Surface

## Overview

The AutoGen repository is distributed through multiple user-facing package surfaces rather than one install name. This is a direct consequence of the layered architecture. Different users should start from different entrypoints depending on whether they want the framework substrate, the high-level chat API, a concrete application surface, or the .NET packages.

The package layout also preserves compatibility and migration history. `pyautogen` exists as a proxy package for the modern AgentChat stack, while the `.NET` side keeps both older `AutoGen.*` packages and newer `Microsoft.AutoGen.*` packages alive at the same time.

## Key Types

| Package / surface | Source | Role |
|-------------------|--------|------|
| `autogen-core` | `python/packages/autogen-core/pyproject.toml` | Foundational runtime package |
| `autogen-agentchat` | `python/packages/autogen-agentchat/pyproject.toml` | Main high-level Python API |
| `autogen-ext` | `python/packages/autogen-ext/pyproject.toml` | Concrete integration layer with optional extras |
| `pyautogen` | `python/packages/pyautogen/pyproject.toml`, `README.md` | Proxy package pointing users to the latest AgentChat line |
| `autogenstudio` | `python/packages/autogen-studio/pyproject.toml` | Packaged Studio application |
| `agbench` | `python/packages/agbench/pyproject.toml` | Benchmark CLI distribution |
| `magentic-one-cli` | `python/packages/magentic-one-cli/pyproject.toml` | Packaged Magentic-One CLI |

## Architecture

The Python package surface follows the framework layering closely.

- `autogen-core` is the low-level substrate.
- `autogen-agentchat` depends on `autogen-core` and is the recommended developer entrypoint.
- `autogen-ext` also depends on `autogen-core` and exposes optional extras for concrete capabilities.
- `pyautogen` acts as a compatibility or convenience proxy for the higher-level API.

Application and tooling packages then sit beside that framework stack rather than inside it:

- `autogenstudio` packages the UI application
- `agbench` packages the evaluation harness
- `magentic-one-cli` packages the Magentic-One app surface

The .NET package surface is parallel rather than unified with the Python one. Legacy and new package lines coexist because the repo is carrying both compatibility and forward migration work.

## Runtime Behavior

The package surface influences how users enter the architecture.

- A framework user often starts with `autogen-agentchat` plus one or more extras from `autogen-ext`.
- A compatibility-minded Python user may still install `pyautogen`, which now proxies to the newer AgentChat line.
- A prototyping user may start with `autogenstudio`.
- An evaluation user may start with `agbench`.
- A packaged-agent-system user may start with `magentic-one-cli`.

This means “which package did you install?” is actually an architectural question in AutoGen because it determines which layer of abstraction you encounter first.

## Variants, Boundaries, and Failure Modes

The most important boundary is between **framework packages** and **app/tool packages**. Installing Studio or Bench does not mean you are working at the same layer as Core or AgentChat. Likewise, installing `pyautogen` does not mean you are on the older Python architecture; its README explicitly says it now proxies to the latest `autogen-agentchat`.

## Source Files

| File | Purpose |
|------|---------|
| `python/packages/autogen-core/pyproject.toml` | Foundational package metadata |
| `python/packages/autogen-agentchat/pyproject.toml` | AgentChat package metadata |
| `python/packages/autogen-ext/pyproject.toml` | Extensions package metadata and extras |
| `python/packages/pyautogen/pyproject.toml` | Proxy package metadata |
| `python/packages/pyautogen/README.md` | Explains proxy-package role and migration caveat |
| `python/packages/autogen-studio/README.md` | Studio install and usage surface |
| `python/packages/agbench/README.md` | Bench install and usage surface |
| `python/packages/magentic-one-cli/src/magentic_one_cli/_m1.py` | CLI usage and config loading behavior |

## See Also

- [Python AgentChat](python-agentchat.md)
- [Python Extensions](python-extensions.md)
- [AutoGen Studio](autogen-studio.md)
- [AutoGen Bench](agbench.md)
- [Magentic-One](magentic-one.md)
- [Package Selection and Entrypoint Flow](../syntheses/package-selection-and-entrypoint-flow.md)
- [Python and Dotnet Ecosystem Relationship](../syntheses/python-and-dotnet-ecosystem-relationship.md)
