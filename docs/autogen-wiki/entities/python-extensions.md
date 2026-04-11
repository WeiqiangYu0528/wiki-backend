# Python Extensions

## Overview

`autogen-ext` is the capability-supply layer of the Python AutoGen stack. If `autogen-core` defines the abstractions and `autogen-agentchat` defines the high-level user API, `autogen-ext` provides the concrete implementations that make those abstractions useful in real systems. Its own README is intentionally brief, but its `pyproject.toml` tells the real story: dozens of optional dependency groups for model providers, code executors, memory backends, gRPC runtimes, MCP support, web/file/video surfers, task-centric memory, and more.

Architecturally, Extensions is where AutoGen stops being an abstract framework and starts touching real providers, host environments, and execution backends. It is also the package where breadth explodes. Core and AgentChat stay conceptually narrow enough to document in a few central pages. Extensions spreads out because it has to contain provider-specific differences, runtime variants, environment adapters, and specialized agent/team compositions.

## Key Types

| Type / cluster | Source | Role |
|----------------|--------|------|
| `OpenAIChatCompletionClient`, `AzureOpenAIChatCompletionClient` | `src/autogen_ext/models/openai/` | Concrete model-client implementations |
| `GrpcWorkerAgentRuntime` | `src/autogen_ext/runtimes/grpc/` | Distributed runtime implementation using shared protobuf contracts |
| `McpWorkbench`, server params, adapters | `src/autogen_ext/tools/mcp/` | MCP-backed capability and tool/session integration |
| `LocalCommandLineCodeExecutor`, Docker/Jupyter executors | `src/autogen_ext/code_executors/` | Concrete code-execution backends |
| `MagenticOne` | `src/autogen_ext/teams/magentic_one.py` | Packaged multi-agent team composition |
| Memory backends | `src/autogen_ext/memory/`, `experimental/task_centric_memory/` | Concrete memory implementations beyond abstract Core support |

The optional dependencies in `autogen-ext/pyproject.toml` are an important artifact in their own right because they show the intended extension seams. They include extras for `openai`, `azure`, `anthropic`, `gemini`, `ollama`, `grpc`, `mcp`, `docker`, `jupyter-executor`, `mem0`, `chromadb`, `redis`, `file-surfer`, `web-surfer`, `magentic-one`, and more. That is effectively a machine-readable map of the package’s extension surface.

## Architecture

Extensions is not one subsystem internally. It is a collection of subsystem families bound together by one job: implementing interfaces defined higher up the stack.

The **provider family** under `models/` implements concrete chat-completion clients and their provider-specific configuration models. OpenAI is the most visible path in the tree, but the extras list makes clear that the package is meant to host many providers.

The **tool and workbench family** under `tools/` is where AutoGen connects to MCP servers and other external tool surfaces. The MCP package exports session actors, stdio/SSE/streamable HTTP adapters, workbench abstractions, and elicitation/root-provider helpers. This is a core example of the Extensions layer turning abstract tool interfaces into real integration points.

The **execution family** under `code_executors/` implements local, Docker, Jupyter, Azure, and hybrid code-execution backends. This family is a good illustration of why Extensions exists: the framework needs one abstract code-executor contract, but the real implementations differ dramatically in safety, environment model, and runtime dependencies.

The **distributed runtime family** under `runtimes/grpc/` implements the worker side of the shared protocol model described in `docs/design/` and `protos/`. This family is where the theoretical worker/service architecture becomes running Python code.

The **specialized agent/team family** under `agents/` and `teams/` packages common higher-level behaviors such as Magentic-One, web surfers, file surfers, and related specializations. These are not foundational runtime constructs, but they are canonical packaged capabilities built on the rest of the stack.

## Runtime Behavior

The gRPC runtime and Magentic-One team show two different runtime roles inside Extensions.

`GrpcWorkerAgentRuntime` is the clearest example of Extensions implementing a Core contract against a concrete backend. It implements `AgentRuntime`, opens a gRPC channel to a host address, keeps send and receive queues, registers supported agent types, manages pending requests, and serializes payloads through the shared protobuf contracts. This is where the low-level Core vocabulary meets real network transport and service/worker runtime behavior.

`McpWorkbench` and the related MCP session helpers show a second pattern: turning external tool ecosystems into agent-usable capability surfaces. Instead of hard-coding tool calls, the Extensions layer creates workbenches and adapters that let agents consume MCP servers through stdio, SSE, or streamable HTTP.

The code-executor family shows a third pattern: implementing one abstract capability with multiple risk and isolation profiles. The local command-line executor explicitly warns that it executes code on the local machine and recommends Docker for safer use. That warning is not just user guidance; it reveals the architectural boundary between “the framework can execute code” and “which execution trust model the application chooses.”

Finally, the `MagenticOne` team class demonstrates how Extensions can package a full multi-agent composition. Its constructor wires together file-surfer, web-surfer, coder, and code-executor agents, optionally adds a user proxy, and delegates to a group-chat implementation. That is a packaged application composition built from AgentChat and Core contracts plus Extension-supplied capabilities.

## Extension Points

Extensions is the main answer to “where do I add concrete capability to AutoGen?” The stable extension points visible from the tree are:

- provider/model clients
- MCP adapters and workbenches
- code executors
- memory backends
- runtime implementations
- specialized agents and teams

This is also why the package is broad rather than neat. It is not trying to be one cohesive small module. It is the umbrella for the official implementations of many different framework seams.

## Source Files

| File | Purpose |
|------|---------|
| `python/packages/autogen-ext/pyproject.toml` | Best overall map of optional capabilities and extras |
| `python/packages/autogen-ext/src/autogen_ext/models/openai/__init__.py` | OpenAI and Azure provider export surface |
| `python/packages/autogen-ext/src/autogen_ext/runtimes/grpc/__init__.py` | Distributed runtime export surface |
| `python/packages/autogen-ext/src/autogen_ext/runtimes/grpc/_worker_runtime.py` | Python worker runtime over gRPC |
| `python/packages/autogen-ext/src/autogen_ext/tools/mcp/__init__.py` | MCP workbench, session, adapter, and host exports |
| `python/packages/autogen-ext/src/autogen_ext/code_executors/local/__init__.py` | Local executor behavior and safety warnings |
| `python/packages/autogen-ext/src/autogen_ext/teams/magentic_one.py` | Packaged multi-agent team composition |
| `python/packages/autogen-ext/README.md` | High-level positioning of Extensions |

## See Also

- [Python Core Runtime](python-core-runtime.md)
- [Python AgentChat](python-agentchat.md)
- [Model Client and Provider System](model-client-and-provider-system.md)
- [Tool and Code Execution System](tool-and-code-execution-system.md)
- [Distributed Runtime and Worker System](distributed-runtime-and-worker-system.md)
- [Tool-Augmented Agent Execution](../concepts/tool-augmented-agent-execution.md)
- [Core to AgentChat to Extension Composition](../syntheses/core-to-agentchat-to-extension-composition.md)
