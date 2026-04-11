# Protocol-Mediated Cross-Language Runtime

## Overview

The repository’s shared protobuf contracts and matching Python/.NET runtime layers reveal an important architectural choice: cross-language interoperability is mediated through explicit protocols, not through undocumented adapter behavior. AutoGen does not assume Python and .NET runtimes can directly share in-memory semantics. Instead, it uses `agent_worker.proto` and `cloudevent.proto` as the neutral boundary.

## Mechanism

The mechanism is straightforward but powerful.

1. Shared `.proto` files define the wire-level shapes for agent ids, RPC requests/responses, subscriptions, CloudEvents, and control messages.
2. Python runtimes such as `GrpcWorkerAgentRuntime` serialize runtime traffic into those contracts.
3. Newer `.NET` packages such as `Microsoft.AutoGen.Core.Grpc` and `Microsoft.AutoGen.RuntimeGateway.Grpc` consume the same contract layer.
4. Application-level cross-language messaging can then happen as long as both sides agree on the payload schemas riding inside those shared envelopes.

This is why the Python gRPC runtime documentation warns that cross-language agents need shared protobuf schemas for any concrete message types they exchange. The framework can standardize the outer transport, but application payloads still need compatible schemas.

## Involved Entities

- [Protocol Contracts](../entities/protocol-contracts.md)
- [Distributed Runtime and Worker System](../entities/distributed-runtime-and-worker-system.md)
- [Dotnet Runtime Stack](../entities/dotnet-runtime-stack.md)
- [Python Extensions](../entities/python-extensions.md)

## Source Evidence

- `protos/agent_worker.proto` defines the runtime channel, control-plane messages, and RPC service.
- `protos/cloudevent.proto` defines the common event envelope.
- `python/packages/autogen-ext/src/autogen_ext/runtimes/grpc/_worker_runtime.py` states that cross-language agents require shared protobuf schemas for sent message types.
- `dotnet/src/Microsoft.AutoGen/Core.Grpc/` and `RuntimeGateway.Grpc/` provide the matching .NET transport/runtime surface.

## See Also

- [Protocol Contracts](../entities/protocol-contracts.md)
- [Distributed Runtime and Worker System](../entities/distributed-runtime-and-worker-system.md)
- [Dotnet Runtime Stack](../entities/dotnet-runtime-stack.md)
- [Event-Driven Agent Programming Model](event-driven-agent-programming-model.md)
- [Python and Dotnet Ecosystem Relationship](../syntheses/python-and-dotnet-ecosystem-relationship.md)
- [Distributed Agent Worker Lifecycle](../syntheses/distributed-agent-worker-lifecycle.md)
