# Local to Distributed Runtime Scaling

## Overview

One of AutoGen’s strongest architectural through-lines is that the same conceptual runtime model is meant to work both in a local in-process setting and in a distributed worker/service setting. The repository does not define one API for small local apps and a totally different API for distributed apps. Instead, it keeps the core abstractions stable and swaps runtime implementations and protocol boundaries underneath them.

## Mechanism

The scaling path works like this:

1. In the local case, a runtime such as `SingleThreadedAgentRuntime` or `.NET` `InProcessRuntime` owns agent factories, subscriptions, delivery queues, and state locally.
2. Agents are still identified by ids and reached through runtime-managed send/publish operations.
3. When the system needs to scale across processes, those same concepts are projected outward through shared protocol contracts.
4. Worker processes host agents and register which agent types they can host.
5. Service processes take over placement and active-directory responsibilities.
6. Requests, responses, and events now cross a gRPC/protobuf boundary instead of only an in-memory boundary.

The result is not “a different architecture.” It is the same ownership model with more explicit transport and placement layers.

## Involved Entities

- [Python Core Runtime](../entities/python-core-runtime.md)
- [Distributed Runtime and Worker System](../entities/distributed-runtime-and-worker-system.md)
- [Protocol Contracts](../entities/protocol-contracts.md)
- [Dotnet Runtime Stack](../entities/dotnet-runtime-stack.md)

## Source Evidence

- `python/packages/autogen-core/src/autogen_core/_single_threaded_agent_runtime.py` documents the local runtime implementation.
- `autogen/docs/design/03 - Agent Worker Protocol.md` explains how workers and services split runtime ownership in the distributed case.
- `python/packages/autogen-ext/src/autogen_ext/runtimes/grpc/_worker_runtime.py` implements the worker-side runtime in Python.
- `dotnet/src/Microsoft.AutoGen/Core/InProcessRuntime.cs` shows the same basic runtime responsibilities in local .NET form.
- `dotnet/src/Microsoft.AutoGen/Core.Grpc/` and `RuntimeGateway.Grpc/` show the distributed .NET side.

## See Also

- [Python Core Runtime](../entities/python-core-runtime.md)
- [Distributed Runtime and Worker System](../entities/distributed-runtime-and-worker-system.md)
- [Dotnet Runtime Stack](../entities/dotnet-runtime-stack.md)
- [Event-Driven Agent Programming Model](event-driven-agent-programming-model.md)
- [Distributed Agent Worker Lifecycle](../syntheses/distributed-agent-worker-lifecycle.md)
- [Python and Dotnet Ecosystem Relationship](../syntheses/python-and-dotnet-ecosystem-relationship.md)
