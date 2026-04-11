# Distributed Runtime and Worker System

## Overview

AutoGen’s distributed runtime story is one of the clearest examples of the repository’s event-driven design center. The design docs do not present multi-agent execution as “a bigger chat loop.” They present it as a multi-process system made of service processes and worker processes, with explicit placement, activation, subscription, and cross-process messaging semantics. The Python Core runtime gives you the in-process substrate; the distributed worker system extends that same model across process and potentially language boundaries.

The core conceptual sources are `docs/design/01 - Programming Model.md` and `docs/design/03 - Agent Worker Protocol.md`. The first explains the system as publish-subscribe around CloudEvents. The second explains how workers host application code, advertise agent names to a coordinating service, and activate agent instances on demand. The implementation bridge on the Python side is `autogen_ext.runtimes.grpc`, especially `GrpcWorkerAgentRuntime`.

## Key Types

| Type / contract | Source | Role |
|-----------------|--------|------|
| Worker/service model | `docs/design/03 - Agent Worker Protocol.md` | Conceptual distributed runtime architecture |
| `GrpcWorkerAgentRuntime` | `python/packages/autogen-ext/src/autogen_ext/runtimes/grpc/_worker_runtime.py` | Python worker-side runtime implementation |
| `HostConnection` | same file | gRPC channel and send/receive queue management |
| `AgentRpc` service | `protos/agent_worker.proto` | Shared RPC surface for runtime communication |
| `CloudEvent` | `protos/cloudevent.proto` | Shared event envelope for distributed messaging |

## Architecture

The distributed runtime is organized around two process roles.

The **service process** is the placement and directory owner. It tracks which workers can host which agent names, chooses a worker when an inactive agent receives a request, and remembers where active agents are currently hosted.

The **worker process** is the code host. It runs application agents, connects to the service, registers supported agent types, and activates agents lazily when messages arrive.

That separation is important because it moves several responsibilities out of local runtime code:

- placement of inactive agents
- directory lookup for active agents
- routing of RPC requests and event delivery across workers
- de-registration when workers shut down

The Python `GrpcWorkerAgentRuntime` fits into this architecture as the worker-side runtime implementation. It looks structurally similar to Core’s runtime in some ways, because it still implements `AgentRuntime`, keeps track of factories, instantiated agents, subscriptions, and pending requests. But it also has to manage a gRPC host connection, protobuf serialization format, and async receive/send loops.

## Runtime Behavior

The worker protocol has a three-phase lifecycle in the design doc: initialization, operation, and termination.

1. **Initialization**
   The worker starts, opens a bidirectional connection to the service, and registers one or more agent types it can host. In Python, `GrpcWorkerAgentRuntime` prepares host connectivity, queues, serialization, and request bookkeeping for this phase.

2. **Operation**
   Once the service knows which agent types a worker can host, requests begin to flow. A message may arrive for an agent that is already active or one that needs to be activated. The worker keeps a local catalog of active agents. If a target agent does not exist yet, it is instantiated on demand, then the message is dispatched. RPC requests produce responses; events do not.

3. **Termination**
   The worker closes the service connection and terminates. The service then removes the worker and any agent instances it was hosting from its directory.

The Python implementation mirrors that design closely. `HostConnection` manages the underlying gRPC stream and client metadata. `GrpcWorkerAgentRuntime` keeps pending request maps, instantiated agents, type registrations, subscription management, and payload serialization mode. In other words, Extensions is not inventing a different runtime story; it is implementing the design-doc story.

## Variants, Boundaries, and Failure Modes

The most important boundary is between **in-process runtime ownership** and **distributed placement ownership**.

- In the in-process case, one runtime owns dispatch and hosting locally.
- In the distributed case, workers still host code, but the service owns placement and active-directory coordination.

Common failure modes at this layer include:

- unsupported or missing payload serialization formats
- connection failures between worker and service
- timeouts for outstanding RPC requests
- registration mismatches for agent types
- inability to deserialize payloads into shared message schemas

These are distributed-systems failures, not high-level conversational failures. That is why this page belongs close to [Protocol Contracts](protocol-contracts.md) and [Protocol-Mediated Cross-Language Runtime](../concepts/protocol-mediated-cross-language-runtime.md).

## Source Files

| File | Purpose |
|------|---------|
| `autogen/docs/design/01 - Programming Model.md` | Publish-subscribe and CloudEvents-based model |
| `autogen/docs/design/03 - Agent Worker Protocol.md` | Worker/service architecture and lifecycle |
| `python/packages/autogen-ext/src/autogen_ext/runtimes/grpc/_worker_runtime.py` | Python gRPC worker runtime implementation |
| `python/packages/autogen-ext/src/autogen_ext/runtimes/grpc/__init__.py` | Export surface for worker runtime classes |
| `protos/agent_worker.proto` | Wire contract for runtime channels and control operations |
| `protos/cloudevent.proto` | Shared event schema |
| `dotnet/src/Microsoft.AutoGen/Core.Grpc/` | .NET-side shared protocol implementation surface |
| `dotnet/src/Microsoft.AutoGen/RuntimeGateway.Grpc/` | .NET runtime gateway and service infrastructure |

## See Also

- [Python Core Runtime](python-core-runtime.md)
- [Python Extensions](python-extensions.md)
- [Protocol Contracts](protocol-contracts.md)
- [Dotnet Runtime Stack](dotnet-runtime-stack.md)
- [Event-Driven Agent Programming Model](../concepts/event-driven-agent-programming-model.md)
- [Local to Distributed Runtime Scaling](../concepts/local-to-distributed-runtime-scaling.md)
- [Distributed Agent Worker Lifecycle](../syntheses/distributed-agent-worker-lifecycle.md)
