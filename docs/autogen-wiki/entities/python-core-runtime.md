# Python Core Runtime

## Overview

`autogen-core` is the substrate that makes the rest of the Python AutoGen stack possible. It does not try to be the most user-friendly layer. Instead, it owns the hard runtime questions that higher layers should not have to reinvent: how agents are identified, how messages are routed, how topics and subscriptions work, how runtimes host agents, how state can be saved and restored, how messages are serialized, and how componentized configuration is represented. The package metadata in `python/packages/autogen-core/pyproject.toml` describes it accurately as the “foundational interfaces and agent runtime implementation for AutoGen.”

The clearest architectural clue is the export surface in `src/autogen_core/__init__.py`. The names exported there are not accidental helpers; they define the canonical vocabulary of the layer: `AgentRuntime`, `SingleThreadedAgentRuntime`, `AgentId`, `AgentType`, `TopicId`, `Subscription`, `RoutedAgent`, message serializers, component config helpers, memory and model-context packages, and tracing hooks. That export surface tells you that Core is responsible for runtime mechanics and shared abstractions, not provider-specific model logic or polished chat APIs.

This page treats Core as the runtime owner for the Python stack. [Python AgentChat](python-agentchat.md) adds a higher-level user API on top of it, and [Python Extensions](python-extensions.md) adds concrete integrations, but both depend on this lower layer remaining stable and explicit about its contracts.

## Key Types

| Type | Source | Role |
|------|--------|------|
| `AgentRuntime` | `src/autogen_core/_agent_runtime.py` | Protocol defining message send/publish, agent registration, lookup, and state methods |
| `SingleThreadedAgentRuntime` | `src/autogen_core/_single_threaded_agent_runtime.py` | Default in-process runtime using one asyncio queue |
| `AgentId` / `AgentType` | `src/autogen_core/_agent_id.py`, `_agent_type.py` | Stable addressing of hosted agents |
| `TopicId` / `Subscription` | `src/autogen_core/_topic.py`, `_subscription.py` | Publish-subscribe addressing and routing surface |
| `RoutedAgent` | `src/autogen_core/_routed_agent.py` | Base class for handler-based agents |
| `Component`, `ComponentModel` | `src/autogen_core/_component_config.py` | Configuration and serialization substrate for swappable components |
| `MessageContext` | `src/autogen_core/_message_context.py` | Delivery metadata passed to handlers |

The `AgentRuntime` protocol is the most important contract in the package because it defines what “a runtime” must do regardless of implementation. Its public surface is small but decisive:

```python
class AgentRuntime(Protocol):
    async def send_message(...)
    async def publish_message(...)
    async def register_factory(...)
    async def register_agent_instance(...)
    async def get(...)
    async def save_state(...)
    async def load_state(...)
    async def agent_metadata(...)
    async def agent_save_state(...)
    async def agent_load_state(...)
```

That tells you the design center of Core. It is not built around “chat completion” or “agent loops” first. It is built around hosting, routing, and persisting addressable runtime participants.

## Architecture

Core is split into a few architectural bands.

The first band is **identity and routing**: `AgentId`, `AgentType`, `TopicId`, `Subscription`, default subscriptions, and type-prefix subscriptions. These objects let the runtime map messages either to one specific recipient (`send_message`) or to all matching subscribers (`publish_message`).

The second band is **hosting and dispatch**: `AgentRuntime`, `SingleThreadedAgentRuntime`, base agents, routed agents, and the runtime helper modules. This is where the runtime keeps track of factories, instantiated agents, and the queue or dispatch mechanism that actually delivers work.

The third band is **message and serialization support**: message context types, serializers, unknown payload handling, and serialization registries. This becomes especially important once AutoGen leaves the in-process path and uses shared protocol contracts for distributed or cross-language transport.

The fourth band is **componentization and extensibility**: `Component`, `ComponentModel`, loader and schema helpers, and provider-string machinery. This is how later layers can declaratively serialize model clients, memory stores, teams, tools, and other pluggable units.

The fifth band is **stateful execution support**: memory, model context, code executor interfaces, cancellation tokens, and telemetry helpers. These are not the high-level user surfaces you see in AgentChat, but the lower-level support contracts that those higher layers rely on.

## Runtime Behavior

The default reference implementation is `SingleThreadedAgentRuntime`. Its docstring is explicit: it is suitable for development and standalone applications, but not for high-throughput or high-concurrency scenarios. That statement matters because it clarifies what Core promises by default and what it leaves to alternate runtimes.

The runtime’s execution flow looks like this:

1. Factories or instances are registered against agent types.
2. The runtime is started, creating a `RunContext` around an internal queue-processing loop.
3. A caller either sends a message to one recipient or publishes a message to a topic.
4. The runtime wraps that delivery in a `SendMessageEnvelope`, `PublishMessageEnvelope`, or `ResponseMessageEnvelope`.
5. The queue loop processes the next envelope, resolves the target agent or matching subscribers, instantiates missing agents on demand, and constructs a `MessageContext`.
6. The target agent handler runs, possibly returning a response or publishing additional work.
7. The runtime can save or restore global or per-agent state through the state methods on the protocol.

The important ownership rule is that agents do not route themselves. The runtime does. Agents expose handlers; the runtime resolves addressing, delivery mode, cancellation, and state boundaries.

`SingleThreadedAgentRuntime` also exposes intervention hooks, telemetry, and background task tracking. Those details matter because they show that Core is already designed as an execution substrate, not just a toy dispatch loop. Even the default in-process runtime has to manage queue shutdown, background exceptions, serialization registries, and the lifecycle of instantiated agents.

## Variants, Boundaries, and Failure Modes

The main boundary is between **runtime abstraction** and **runtime implementation**. `AgentRuntime` deliberately abstracts over different backends. `SingleThreadedAgentRuntime` is just one implementation. The distributed gRPC runtime in [Python Extensions](python-extensions.md) and the .NET `InProcessRuntime` / gRPC layers implement the same conceptual job in different environments.

The main failure categories visible in the protocol and implementation are:

- undeliverable messages
- registration conflicts for agent types or subscriptions
- lookup failures when no factory exists for a requested agent type
- handler exceptions during delivery
- timeout or cancellation during runtime-managed operations

These are runtime failures, not AgentChat conversational failures. That distinction is why the Core layer belongs below chat-oriented abstractions.

## Source Files

| File | Purpose |
|------|---------|
| `python/packages/autogen-core/src/autogen_core/__init__.py` | Canonical export surface for the Core vocabulary |
| `python/packages/autogen-core/src/autogen_core/_agent_runtime.py` | `AgentRuntime` protocol with send, publish, registration, lookup, and state methods |
| `python/packages/autogen-core/src/autogen_core/_single_threaded_agent_runtime.py` | Default in-process runtime, queue loop, envelopes, tracing, intervention handlers |
| `python/packages/autogen-core/src/autogen_core/_routed_agent.py` | Routed-agent base class and handler decorators |
| `python/packages/autogen-core/src/autogen_core/_topic.py` | Topic addressing |
| `python/packages/autogen-core/src/autogen_core/_subscription.py` | Subscription contracts |
| `python/packages/autogen-core/src/autogen_core/_component_config.py` | Component config and serialization substrate |
| `python/packages/autogen-core/pyproject.toml` | Package role, dependencies, and positioning |

## See Also

- [Python AgentChat](python-agentchat.md)
- [Python Extensions](python-extensions.md)
- [Distributed Runtime and Worker System](distributed-runtime-and-worker-system.md)
- [Protocol Contracts](protocol-contracts.md)
- [Event-Driven Agent Programming Model](../concepts/event-driven-agent-programming-model.md)
- [Local to Distributed Runtime Scaling](../concepts/local-to-distributed-runtime-scaling.md)
