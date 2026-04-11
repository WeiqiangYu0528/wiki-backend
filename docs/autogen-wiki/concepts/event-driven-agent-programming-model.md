# Event-Driven Agent Programming Model

## Overview

The deepest common design idea in AutoGen is that agents are runtime participants in an event-driven system, not just wrappers around chat completions. This is easiest to miss if you only read the high-level AgentChat examples, but it is stated plainly in `docs/design/01 - Programming Model.md`: the programming model is basically publish-subscribe, with agents subscribing to events, publishing events, and using prompts, memory, data sources, and skills as supporting assets.

## Mechanism

The mechanism unfolds in layers.

1. Events are modeled as typed messages, and in the distributed design they use the CloudEvents schema.
2. Agents subscribe to topics or event patterns they care about.
3. A runtime owns delivery. It routes direct messages to recipients or publishes messages to matching subscribers.
4. Agents handle the incoming event, update state, call tools or models, and may emit further events.
5. Orchestrator-style agents can impose higher-level workflows on top of this substrate by deciding which events to emit next and which participants should react.

In Python Core, this shows up in the `AgentRuntime` protocol and the `SingleThreadedAgentRuntime` implementation. The runtime owns `send_message`, `publish_message`, subscription lookup, agent activation, and state persistence. In the distributed design, the same model is projected across process boundaries through worker/service runtime coordination and shared protobuf contracts.

## Involved Entities

- [Python Core Runtime](../entities/python-core-runtime.md)
- [Distributed Runtime and Worker System](../entities/distributed-runtime-and-worker-system.md)
- [Protocol Contracts](../entities/protocol-contracts.md)
- [Dotnet Runtime Stack](../entities/dotnet-runtime-stack.md)

## Source Evidence

- `autogen/docs/design/01 - Programming Model.md` explicitly says the programming model is publish-subscribe and that events are delivered as CloudEvents.
- `python/packages/autogen-core/src/autogen_core/_agent_runtime.py` defines `send_message` and `publish_message` as the core runtime verbs.
- `python/packages/autogen-core/src/autogen_core/_single_threaded_agent_runtime.py` shows queue-based event delivery and per-envelope processing.
- `protos/cloudevent.proto` formalizes the event envelope used by the distributed model.

## See Also

- [Python Core Runtime](../entities/python-core-runtime.md)
- [Distributed Runtime and Worker System](../entities/distributed-runtime-and-worker-system.md)
- [Protocol Contracts](../entities/protocol-contracts.md)
- [Local to Distributed Runtime Scaling](local-to-distributed-runtime-scaling.md)
- [Distributed Agent Worker Lifecycle](../syntheses/distributed-agent-worker-lifecycle.md)
- [Protocol-Mediated Cross-Language Runtime](protocol-mediated-cross-language-runtime.md)
