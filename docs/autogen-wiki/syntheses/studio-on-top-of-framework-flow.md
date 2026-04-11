# Studio on Top of Framework Flow

## Overview

This synthesis explains how AutoGen Studio sits on top of the framework stack rather than replacing it. The key architectural point is that Studio owns app concerns such as CLI launch, HTTP routes, persistence, and UI serving, while team execution still happens through framework-derived components.

## Systems Involved

- [AutoGen Studio](../entities/autogen-studio.md)
- [Python AgentChat](../entities/python-agentchat.md)
- [Python Extensions](../entities/python-extensions.md)
- [Package and Distribution Surface](../entities/package-and-distribution-surface.md)

## Interaction Model

1. A Studio CLI command writes environment configuration and launches Uvicorn.
2. The FastAPI app initializes managers, auth dependencies, routes, and static serving.
3. An API request or UI action targets sessions, runs, teams, or validation routes.
4. `TeamManager` loads or materializes a team definition from JSON/YAML/component config.
5. The team is instantiated using framework components and run via AgentChat task/team methods.
6. Results, streamed messages, and LLM-call events flow back through the app layer to the client.
7. Persistence and schema changes are handled by DB and schema managers around that runtime flow.

## Key Interfaces

| Boundary | Interface |
|----------|-----------|
| CLI -> app | env file plus Uvicorn launch |
| app -> framework | team config loading and `BaseGroupChat` execution |
| app -> persistence | `DatabaseManager` and schema tooling |
| app -> client | FastAPI routes, websocket routes, static UI serving |

## Source Evidence

- `python/packages/autogen-studio/autogenstudio/cli.py` shows the launch path.
- `python/packages/autogen-studio/autogenstudio/web/app.py` assembles the FastAPI app and routes.
- `python/packages/autogen-studio/autogenstudio/teammanager/teammanager.py` loads teams and runs them.
- `python/packages/autogen-studio/autogenstudio/database/db_manager.py` shows persistence and schema responsibilities.

## See Also

- [AutoGen Studio](../entities/autogen-studio.md)
- [Python AgentChat](../entities/python-agentchat.md)
- [Studio as Prototyping Surface](../concepts/studio-as-prototyping-surface.md)
- [Layered API Architecture](../concepts/layered-api-architecture.md)
- [Package Selection and Entrypoint Flow](package-selection-and-entrypoint-flow.md)
- [Core to AgentChat to Extension Composition](core-to-agentchat-to-extension-composition.md)
