# Python and Dotnet Ecosystem Relationship

## Overview

This synthesis explains how the Python and .NET sides of AutoGen relate without flattening them into one identical architecture. The repository contains both language ecosystems, but they are not at identical maturity points or in identical design generations. Python is the clearest current center of gravity, while .NET carries both legacy and newer event-driven lines at once.

## Systems Involved

- [Python Core Runtime](../entities/python-core-runtime.md)
- [Python AgentChat](../entities/python-agentchat.md)
- [Python Extensions](../entities/python-extensions.md)
- [Dotnet Runtime Stack](../entities/dotnet-runtime-stack.md)
- [Protocol Contracts](../entities/protocol-contracts.md)

## Interaction Model

The relationship has three layers.

1. **Conceptual alignment**
   Both ecosystems use the same broad runtime ideas: agent ids, runtimes, message sending, publication, state, and higher-level chat abstractions.

2. **Protocol alignment**
   Shared `.proto` files let distributed runtime concepts cross language boundaries through explicit contracts rather than undocumented conventions.

3. **Generational mismatch**
   The Python stack is already organized around the Core -> AgentChat -> Extensions structure, while the .NET tree still contains both older `AutoGen.*` packages and newer `Microsoft.AutoGen.*` packages. That means architectural comparison should focus on the newer .NET line when discussing convergence.

## Key Interfaces

| Boundary | Interface |
|----------|-----------|
| Shared runtime vocabulary | `AgentRuntime` / `IAgentRuntime`, ids, topics, subscriptions |
| Shared transport | `agent_worker.proto`, `cloudevent.proto` |
| High-level chat layer | `autogen-agentchat` and `Microsoft.AutoGen.AgentChat` |

## Source Evidence

- `autogen/README.md` says Core supports cross-language support for .NET and Python.
- `dotnet/README.md` explains the old/new package split on the .NET side.
- `python/packages/autogen-core/src/autogen_core/_agent_runtime.py` and `dotnet/src/Microsoft.AutoGen/Contracts/IAgentRuntime.cs` expose strikingly similar runtime responsibilities.
- `protos/agent_worker.proto` and `protos/cloudevent.proto` provide the shared contract layer.

## See Also

- [Dotnet Runtime Stack](../entities/dotnet-runtime-stack.md)
- [Python Core Runtime](../entities/python-core-runtime.md)
- [Protocol Contracts](../entities/protocol-contracts.md)
- [Protocol-Mediated Cross-Language Runtime](../concepts/protocol-mediated-cross-language-runtime.md)
- [Local to Distributed Runtime Scaling](../concepts/local-to-distributed-runtime-scaling.md)
- [Distributed Agent Worker Lifecycle](distributed-agent-worker-lifecycle.md)
