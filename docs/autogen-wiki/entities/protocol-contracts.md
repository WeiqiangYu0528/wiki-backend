# Protocol Contracts

## Overview

The shared protocol contracts in `protos/` are one of the most important architectural anchors in the AutoGen repository because they make the distributed runtime story concrete and language-neutral. The design docs talk about publish-subscribe, CloudEvents, workers, services, placement, RPC requests, and subscription management. The protobuf files define the actual wire shapes that these concepts must serialize into.

This matters for two reasons. First, it makes the worker/service runtime model implementable across both Python and .NET. Second, it forces the distributed runtime abstractions to be explicit about what crosses process and language boundaries instead of relying on implicit in-memory conventions.

## Key Types

| Contract | Source | Role |
|----------|--------|------|
| `CloudEvent` | `protos/cloudevent.proto` | Shared event envelope used by the distributed programming model |
| `AgentId` | `protos/agent_worker.proto` | Wire-level agent identifier |
| `RpcRequest` / `RpcResponse` | `protos/agent_worker.proto` | Request-response transport for addressed calls |
| `Subscription`, `TypeSubscription`, `TypePrefixSubscription` | `protos/agent_worker.proto` | Wire-level subscription representation |
| `Message` | `protos/agent_worker.proto` | Union wrapper for RPC requests, responses, or CloudEvents |
| `ControlMessage` | `protos/agent_worker.proto` | Control-plane envelope for state and administrative RPCs |
| `AgentRpc` service | `protos/agent_worker.proto` | Bidirectional channel and registration/subscription service |

## Architecture

The protocol layer is split into two complementary files.

`cloudevent.proto` defines the generalized event envelope. It imports timestamp and `Any`, models the required CloudEvent attributes (`id`, `source`, `spec_version`, `type`), carries optional or extension attributes in a map, and allows binary, text, or protobuf-encoded event payloads. This file is the schema-level expression of the programming-model design doc’s claim that AutoGen events are defined as CloudEvents.

`agent_worker.proto` defines the worker/service runtime protocol. It adds:

- agent identity
- generic payload encoding
- RPC request and response types
- agent-type registration messages
- subscription-management messages
- runtime state save/load messages
- a top-level `Message` union for transport over the open channel
- a distinct `ControlMessage` envelope for state and destination-aware control traffic
- the `AgentRpc` service with streaming data and control channels plus registration and subscription methods

Together these files split the problem cleanly:

- `cloudevent.proto` models distributed events
- `agent_worker.proto` models distributed runtime coordination and RPC transport

## Runtime Behavior

At runtime, these contracts mediate several distinct flows.

1. **Event publication**
   A worker or runtime can transport a CloudEvent over the shared channel using the `Message.cloudEvent` variant.

2. **RPC-style addressed delivery**
   A sender packages a `RpcRequest` with source, target, method, payload, and metadata. The recipient processes it and returns a `RpcResponse` with the same request id.

3. **Worker capability advertisement**
   Workers call `RegisterAgent` using `RegisterAgentTypeRequest` so the service knows which agent types they can host.

4. **Subscription management**
   Workers or runtimes add, remove, or query subscriptions through the relevant request/response messages.

5. **State control**
   `ControlMessage` carries save/load state requests and responses directed toward an agent or client destination.

This division is architecturally valuable because it avoids overloading one message shape with every concern. Data-plane traffic and control-plane traffic are both explicit.

## Variants, Boundaries, and Failure Modes

The protocol contracts do not describe application semantics for every message payload. They define the transport and routing boundary. That means application-level message schemas may still need shared protobuf definitions if cross-language agents exchange strongly typed payloads. The Python gRPC runtime documentation in Extensions is explicit about this point: cross-language agents require shared protobuf schemas for message types sent between agents.

Typical failure modes here include:

- payloads serialized in unsupported formats
- missing shared schemas for cross-language message types
- request/response mismatches or timeouts
- subscription ids or destinations that no longer match runtime state

## Source Files

| File | Purpose |
|------|---------|
| `protos/cloudevent.proto` | Canonical CloudEvent schema |
| `protos/agent_worker.proto` | Worker/service runtime contract and RPC service |
| `docs/design/01 - Programming Model.md` | Explains why CloudEvents are used |
| `docs/design/03 - Agent Worker Protocol.md` | Explains how the runtime protocol is meant to behave |
| `python/packages/autogen-ext/src/autogen_ext/runtimes/grpc/_worker_runtime.py` | Python-side consumer of the protocol contracts |
| `dotnet/src/Microsoft.AutoGen/Core.Grpc/` | .NET-side consumer and serializer surface |
| `dotnet/src/Microsoft.AutoGen/RuntimeGateway.Grpc/` | Service/gateway-side .NET runtime infrastructure |

## See Also

- [Distributed Runtime and Worker System](distributed-runtime-and-worker-system.md)
- [Python Extensions](python-extensions.md)
- [Dotnet Runtime Stack](dotnet-runtime-stack.md)
- [Protocol-Mediated Cross-Language Runtime](../concepts/protocol-mediated-cross-language-runtime.md)
- [Distributed Agent Worker Lifecycle](../syntheses/distributed-agent-worker-lifecycle.md)
- [Python and Dotnet Ecosystem Relationship](../syntheses/python-and-dotnet-ecosystem-relationship.md)
