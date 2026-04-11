# Tool-Augmented Agent Execution

## Overview

AutoGen treats tool use as part of the main execution loop rather than as an optional add-on. High-level agents can call tools, reflect on their results, hand work off to other agents, and rely on specialized execution backends or workbenches to make those capabilities real. This pattern is one of the main bridges between [Python AgentChat](../entities/python-agentchat.md) and [Python Extensions](../entities/python-extensions.md).

## Mechanism

The mechanism has three steps.

1. The agent receives a task and invokes its configured model client.
2. The model may return tool calls instead of, or before, a final text response.
3. The agent executes those tool calls through direct tools, workbenches, MCP surfaces, or code executors, then either returns a summary or performs another inference using the results.

`AssistantAgent` documents this explicitly, including reflective tool use, tool-call summaries, and maximum tool iterations. Extensions then supplies the concrete backends: MCP workbenches, local executors, Docker executors, Jupyter executors, and specialized packaged teams such as Magentic-One.

## Involved Entities

- [Python AgentChat](../entities/python-agentchat.md)
- [Python Extensions](../entities/python-extensions.md)
- [Tool and Code Execution System](../entities/tool-and-code-execution-system.md)
- [Magentic-One](../entities/magentic-one.md)

## Source Evidence

- `python/packages/autogen-agentchat/src/autogen_agentchat/agents/_assistant_agent.py` documents the tool-call loop, reflective tool use, summaries, and handoff interaction.
- `python/packages/autogen-ext/src/autogen_ext/tools/mcp/__init__.py` shows MCP workbench exports.
- `python/packages/autogen-ext/src/autogen_ext/code_executors/local/__init__.py` documents local code execution behavior and risk.
- `python/packages/autogen-ext/src/autogen_ext/teams/magentic_one.py` composes tool-using specialized agents into one packaged team.

## See Also

- [Tool and Code Execution System](../entities/tool-and-code-execution-system.md)
- [Python AgentChat](../entities/python-agentchat.md)
- [Python Extensions](../entities/python-extensions.md)
- [Magentic-One](../entities/magentic-one.md)
- [Core to AgentChat to Extension Composition](../syntheses/core-to-agentchat-to-extension-composition.md)
- [Benchmark and Agent Runtime Feedback Loop](../syntheses/benchmark-and-agent-runtime-feedback-loop.md)
