# Dotnet Runtime Stack

## Overview

The `.NET` side of the AutoGen repository is not one cleanly unified package line. The top-level `dotnet/README.md` explicitly says there are two sets of packages:

- older `AutoGen.*` packages derived from the 0.2 lineage
- newer `Microsoft.AutoGen.*` packages that adopt the event-driven model and are still evolving

That split is the key to understanding the .NET tree. The older packages look more like the earlier chat/middleware/orchestrator style, with packages such as `AutoGen.Core`, `AutoGen.OpenAI`, and related provider integrations. The newer packages introduce contracts, in-process runtime, gRPC runtime support, runtime gateway services, agent host infrastructure, and a dedicated `AgentChat` abstraction layer under the `Microsoft.AutoGen.*` namespace.

## Key Types

| Type / subsystem | Source | Role |
|------------------|--------|------|
| `IAgentRuntime` | `dotnet/src/Microsoft.AutoGen/Contracts/IAgentRuntime.cs` | .NET runtime contract closely paralleling Python Core runtime responsibilities |
| `InProcessRuntime` | `dotnet/src/Microsoft.AutoGen/Core/InProcessRuntime.cs` | Newer in-process event-driven runtime implementation |
| `IChatAgent` | `dotnet/src/Microsoft.AutoGen/AgentChat/Abstractions/ChatAgent.cs` | .NET high-level chat-agent abstraction |
| Runtime gateway and gRPC services | `dotnet/src/Microsoft.AutoGen/RuntimeGateway.Grpc/` | Distributed runtime/service infrastructure |
| Legacy `AutoGen.Core`, `AutoGen.OpenAI`, etc. | `dotnet/src/AutoGen.*` | Older package line with prior agent/chat/middleware model |

## Architecture

The .NET stack currently has two overlapping architectures.

The **legacy line** is the older `AutoGen.*` family. Its directory layout emphasizes agents, messages, middleware, group chat, orchestrators, and provider-specific packages such as `AutoGen.OpenAI`. This is the lineage closest to older AutoGen versions and it is still present for compatibility and migration reasons.

The **newer line** is `Microsoft.AutoGen.*`. It more clearly mirrors the newer event-driven model:

- `Contracts/` defines ids, metadata, runtime interfaces, message context, and subscription abstractions
- `Core/` implements the in-process runtime and delivery logic
- `Core.Grpc/` bridges the runtime to protobuf and gRPC transport
- `RuntimeGateway.Grpc/` provides gateway and registry infrastructure
- `AgentChat/` adds higher-level chat-oriented abstractions on top
- `AgentHost/` packages runtime hosting
- `Extensions/` integrates into broader .NET ecosystems such as Aspire or Semantic Kernel

This newer structure is not a one-to-one copy of the Python package tree, but it is conceptually much closer to it than the legacy line is. That is why the shared protocol contracts and distributed-runtime docs matter so much for the .NET story.

## Runtime Behavior

`IAgentRuntime` in the new contracts package is the clearest signal of architectural convergence with Python Core. Its surface includes:

- `SendMessageAsync`
- `PublishMessageAsync`
- `GetAgentAsync`
- `SaveAgentStateAsync`
- `LoadAgentStateAsync`
- `GetAgentMetadataAsync`
- subscription add/remove
- agent-factory registration
- proxy retrieval

That is unmistakably the same class of runtime ownership seen in Python’s `AgentRuntime` protocol.

`InProcessRuntime` then provides the default concrete implementation. It maintains dictionaries for agent instances, subscriptions, and agent factories; uses a message-delivery queue; ensures agents are instantiated lazily when needed; and handles both publish and send flows. This is the .NET analogue of Python’s `SingleThreadedAgentRuntime`, even though the implementation details and surrounding hosting model differ.

On top of that runtime, the newer `Microsoft.AutoGen.AgentChat` layer provides chat-oriented abstractions. `ChatAgent.cs` defines validated agent names, response and streaming-frame types, and the `IChatAgent` interface with reset and state support. This mirrors the same “runtime substrate below, chat ergonomics above” separation present in Python.

## Variants, Boundaries, and Failure Modes

The main architectural boundary in the .NET tree is generational:

- the old `AutoGen.*` line remains for continuity and migration
- the new `Microsoft.AutoGen.*` line is where the event-driven runtime model is being expressed more directly

This means documentation or code search in the .NET tree can be misleading if the reader assumes every package belongs to the same design generation. It also means cross-language comparisons should focus on the new `Microsoft.AutoGen.*` contracts and runtime layers rather than flattening the entire `.NET` tree into one story.

## Source Files

| File | Purpose |
|------|---------|
| `autogen/dotnet/README.md` | Explains the old vs new package split |
| `dotnet/src/Microsoft.AutoGen/Contracts/IAgentRuntime.cs` | New runtime contract |
| `dotnet/src/Microsoft.AutoGen/Core/InProcessRuntime.cs` | In-process runtime implementation |
| `dotnet/src/Microsoft.AutoGen/AgentChat/Abstractions/ChatAgent.cs` | New chat-agent abstraction layer |
| `dotnet/src/Microsoft.AutoGen/Core.Grpc/` | gRPC and protobuf bridge for the runtime |
| `dotnet/src/Microsoft.AutoGen/RuntimeGateway.Grpc/` | Gateway/service infrastructure |
| `dotnet/src/AutoGen.Core/` | Older runtime/chat/middleware line |
| `dotnet/src/AutoGen.OpenAI/` | Older provider-specific integration line |

## See Also

- [Protocol Contracts](protocol-contracts.md)
- [Distributed Runtime and Worker System](distributed-runtime-and-worker-system.md)
- [Package and Distribution Surface](package-and-distribution-surface.md)
- [Protocol-Mediated Cross-Language Runtime](../concepts/protocol-mediated-cross-language-runtime.md)
- [Python and Dotnet Ecosystem Relationship](../syntheses/python-and-dotnet-ecosystem-relationship.md)
- [Local to Distributed Runtime Scaling](../concepts/local-to-distributed-runtime-scaling.md)
