# Tool and Code Execution System

## Overview

AutoGen treats tools and code execution as first-class agent capabilities rather than as ad hoc callbacks. This subsystem spans [Python AgentChat](python-agentchat.md), which defines how tools participate in agent loops, and [Python Extensions](python-extensions.md), which provides concrete workbenches, MCP bridges, and code-executor implementations. The result is a layered capability model: high-level agents can invoke tools, but the actual execution surfaces are modular and can range from in-process Python callables to Docker-isolated command execution or MCP-backed remote capabilities.

## Key Types

| Type | Source | Role |
|------|--------|------|
| `BaseTool`, `FunctionTool`, `Workbench` | Core/AgentChat imports inside `AssistantAgent` | Abstract tool and workbench contracts visible to high-level agents |
| `AgentTool`, `TaskRunnerTool` | `python/packages/autogen-agentchat/src/autogen_agentchat/tools/` | Wrap agents or teams as callable tools |
| `McpWorkbench` and server params | `python/packages/autogen-ext/src/autogen_ext/tools/mcp/` | MCP-backed tool/session/workbench surface |
| `LocalCommandLineCodeExecutor` | `python/packages/autogen-ext/src/autogen_ext/code_executors/local/__init__.py` | Local host execution backend |
| Docker/Jupyter/Azure executors | `python/packages/autogen-ext/src/autogen_ext/code_executors/` | Alternative execution backends with different isolation profiles |

## Architecture

There are two overlapping architecture lines here.

The first line is the **tool loop inside AgentChat**. `AssistantAgent` can accept direct tools, workbenches, handoffs, and maximum tool-iteration settings. When the model returns tool calls, the agent executes them, optionally reflects on the results in a second inference, and can summarize or propagate those outcomes into final responses or handoffs.

The second line is the **execution and integration backend inside Extensions**. Tools are only useful if they connect to real capability surfaces. That is where MCP sessions, local shell execution, Docker execution, Jupyter kernels, and other workbench or executor objects matter.

This split keeps tool semantics distinct from tool implementation. AgentChat says how tools participate in reasoning loops. Extensions says what concrete environments or adapters those tools actually run against.

## Runtime Behavior

In `AssistantAgent`, tool behavior follows a predictable loop:

1. The model returns one or more tool calls.
2. The agent executes those calls immediately.
3. Results become either the final response summary or the input to another inference, depending on `reflect_on_tool_use`.
4. If a handoff is triggered, tool calls may still execute first and their results can be attached to the handoff context.

On the execution side, the behavior depends on which backend is used. The local command-line executor is illustrative because it makes the tradeoff explicit. It writes code blocks to files, runs them in the chosen working directory, supports Python and shell languages, can prepare user-defined functions, and warns that local execution is dangerous when driven by model-generated code. It even recommends Docker as the safer default. That warning is effectively a design note: AutoGen supports multiple execution trust models, and the caller must choose one intentionally.

MCP workbenches behave differently. Instead of executing code directly on the host, they wrap an MCP server connection or session and expose that capability to agents through a unified workbench interface. This lets AutoGen teams consume tool ecosystems without baking each external tool into the framework core.

## Variants, Boundaries, and Failure Modes

The major variants in this subsystem are:

- direct callable tools
- agent/team-as-tool wrappers
- workbench-backed tools
- code executors with different isolation properties
- MCP-backed external tool surfaces

The main architectural boundaries are:

- tool-loop semantics belong to AgentChat
- execution backend choice belongs to Extensions and the application
- capability approval or human oversight often belongs to the packaged application or team layer

Typical failure modes include invalid tool naming, backend setup failures, unavailable MCP servers, host-environment execution errors, and unsafe execution when local executors are used without enough isolation.

## Source Files

| File | Purpose |
|------|---------|
| `python/packages/autogen-agentchat/src/autogen_agentchat/agents/_assistant_agent.py` | High-level tool loop, tool-call reflection, handoff interaction |
| `python/packages/autogen-agentchat/src/autogen_agentchat/tools/_agent.py` | Agent-as-tool adapter |
| `python/packages/autogen-agentchat/src/autogen_agentchat/tools/_task_runner_tool.py` | Team/task-runner as tool wrapper |
| `python/packages/autogen-ext/src/autogen_ext/tools/mcp/__init__.py` | MCP workbench and session export surface |
| `python/packages/autogen-ext/src/autogen_ext/code_executors/local/__init__.py` | Local executor behavior and risk model |
| `python/packages/autogen-ext/src/autogen_ext/code_executors/docker/` | Safer containerized execution backend |
| `python/packages/autogen-ext/src/autogen_ext/code_executors/jupyter/` | Notebook/kernel-backed execution path |

## See Also

- [Python AgentChat](python-agentchat.md)
- [Python Extensions](python-extensions.md)
- [Model Client and Provider System](model-client-and-provider-system.md)
- [Magentic-One](magentic-one.md)
- [Tool-Augmented Agent Execution](../concepts/tool-augmented-agent-execution.md)
- [Core to AgentChat to Extension Composition](../syntheses/core-to-agentchat-to-extension-composition.md)
