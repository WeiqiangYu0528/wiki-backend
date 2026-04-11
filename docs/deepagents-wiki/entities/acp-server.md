# ACP Server

## Overview

The ACP server package (`libs/acp/`) adapts any Deep Agent to the [Agent Client Protocol (ACP)](https://agentclientprotocol.com/overview/introduction), a standard protocol that editor clients use to embed agents as first-class participants in a user's workspace. In practice this lets a LangGraph Deep Agent run inside [Zed](https://zed.dev/) (or any other ACP-compatible host) as a persistent agent with multi-turn conversation, tool call display, plan visualization, diff-aware edits, and dynamic model switching — all without modifying the underlying agent graph. The package is published as `deepagents-acp` and the core class is `AgentServerACP`, which extends the ACP SDK's `Agent` base class and bridges every ACP lifecycle event to LangGraph invocations.

## Key Types / Key Concepts

```python
@dataclass(frozen=True, slots=True)
class AgentSessionContext:
    """Per-session context passed to an agent factory."""
    cwd: str          # working directory sent by the ACP client
    mode: str         # active session mode id
    model: str | None # selected model value (e.g. "anthropic:claude-opus-4-6")

class AgentServerACP(ACPAgent):
    """ACP agent server bridging Deep Agents to the Agent Client Protocol."""

    def __init__(
        self,
        agent: CompiledStateGraph
               | Callable[[AgentSessionContext], CompiledStateGraph],
        *,
        modes: SessionModeState | None = None,
        models: list[dict[str, str]] | None = None,
    ) -> None: ...

    # ACP lifecycle methods (called by the ACP SDK per-session):
    async def initialize(self, protocol_version: int, ...) -> InitializeResponse: ...
    async def new_session(self, cwd: str, ...) -> NewSessionResponse: ...
    async def prompt(self, session_id: str, content_blocks: ...) -> PromptResponse: ...
    async def set_session_config_option(self, ...) -> SetSessionConfigOptionResponse: ...
    async def set_session_mode(self, ...) -> SetSessionModeResponse: ...
```

**ACP content block types** (from the ACP schema, handled by `AgentServerACP`):
- `TextContentBlock` — plain text input
- `ImageContentBlock` — image data (converted to LangChain content blocks)
- `AudioContentBlock` — audio data
- `ResourceContentBlock` / `EmbeddedResourceContentBlock` — file resources
- `ToolCallStart` / `ToolCallUpdate` — streamed tool invocation events sent back to the client
- `AgentPlanUpdate` — todo-list plan updates rendered in the ACP client's plan panel

## Architecture

**Minimal usage — static agent**:
```python
from acp import run_agent
from deepagents import create_deep_agent
from deepagents_acp.server import AgentServerACP
from langgraph.checkpoint.memory import MemorySaver

agent = create_deep_agent(
    tools=[my_tool],
    checkpointer=MemorySaver(),
)
server = AgentServerACP(agent)
await run_agent(server)   # starts the ACP stdio transport
```

**Dynamic agent factory with model switching**:
```python
models = [
    {"value": "anthropic:claude-opus-4-6", "name": "Claude Opus 4"},
    {"value": "openai:gpt-4-turbo",        "name": "GPT-4 Turbo"},
]

def build_agent(context: AgentSessionContext) -> CompiledStateGraph:
    return create_deep_agent(
        model=context.model,
        checkpointer=MemorySaver(),
    )

server = AgentServerACP(agent=build_agent, models=models)
```

When `agent` is a factory callable, `AgentServerACP` calls it once per `new_session` event (passing the `AgentSessionContext`) rather than sharing a single compiled graph across sessions. This is required for per-session model or mode selection.

**Session lifecycle**:
1. ACP client connects → `on_connect(conn)` stores the client handle.
2. `initialize()` returns `AgentCapabilities` (image support declared here).
3. `new_session(cwd, mcp_servers, ...)` creates a new LangGraph thread, builds or reuses the agent, stores per-session state (cwd, mode, model, plan, allowed command types).
4. `prompt(session_id, content_blocks)` converts ACP content blocks to LangChain `HumanMessage`, invokes the agent graph in streaming mode, and streams `ToolCallStart`/`ToolCallUpdate`/`update_agent_message` events back to the client as they arrive.
5. `set_session_config_option` handles mid-session model or mode switches without losing conversation history.

**Config options panel**: When `models` or `modes` are provided, `_build_config_options()` returns `SessionConfigOption` objects (type `"select"`) that the ACP client renders as a dropdown in its UI. The model selector exposes `category="model"` and the mode selector exposes `category="mode"`.

**Tool call streaming**: The ACP SDK provides `start_tool_call`, `update_tool_call`, `start_edit_tool_call`, and `tool_diff_content` helpers. `AgentServerACP` uses these to stream shell command output, file diffs, and structured tool results to the editor as they execute. The `truncate_execute_command_for_display` utility clips long command strings to a displayable length.

**Security**: The `contains_dangerous_patterns` utility in `utils.py` screens shell commands before surfacing them to the ACP client, and `_allowed_command_types` tracks which command type/subcommand pairs have been approved per session for the permission flow.

**Zed configuration** (`settings.json`):
```json
{
  "agent_servers": {
    "DeepAgents": {
      "type": "custom",
      "command": "/absolute/path/to/deepagents-acp/run_demo_agent.sh"
    }
  }
}
```

**Toad / local testing**: The [batrachian-toad](https://pypi.org/project/batrachian-toad/) CLI wraps any ACP server for local testing without a full editor:
```bash
toad acp "uv run python path/to/your_server.py" .
```

**Transport**: ACP uses a stdio-based JSON-RPC transport. `run_agent(server)` from the ACP SDK handles the transport loop; `AgentServerACP` only implements the protocol handler methods.

## Source Files

| File | Purpose |
|------|---------|
| `libs/acp/deepagents_acp/server.py` | `AgentServerACP`: full ACP lifecycle implementation, session management, content-block conversion, streaming |
| `libs/acp/deepagents_acp/utils.py` | `contains_dangerous_patterns`, content-block converters, command truncation |
| `libs/acp/deepagents_acp/__main__.py` | Entry point: instantiates the demo agent and calls `run_agent` |
| `libs/acp/examples/demo_agent.py` | Full example: multi-model factory agent with LangSmith tracing |
| `libs/acp/examples/local_context.py` | Local filesystem backend setup for the demo agent |
| `libs/acp/run_demo_agent.sh` | Shell entrypoint for Zed `agent_servers` config |
| `libs/acp/pyproject.toml` | Package metadata: `deepagents-acp`, declares `acp` SDK dependency |
| `libs/acp/README.md` | Setup guide, Zed integration, model switching example |

## See Also

- [Subagent System](./subagent-system.md)
- [Backend System](./backend-system.md)
- [Example Agents](./example-agents.md)
