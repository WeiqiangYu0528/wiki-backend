# AutoGen Studio

## Overview

AutoGen Studio is the repository’s most explicit end-user application surface: a web UI and API layer for prototyping, configuring, and running AutoGen teams. Its own README frames it carefully. Studio is AutoGen-powered and useful for rapid experimentation, but it is explicitly not a production-ready app. That framing is architecturally important because it prevents readers from mistaking Studio for the framework center of gravity. Studio consumes the framework; it is not the substrate that Core or AgentChat are built on.

The package combines a CLI, a FastAPI backend, a built frontend, persistence and schema management, team configuration loading, validation flows, gallery support, MCP integration, and a lightweight “lite” mode for quick experimentation. This breadth makes it one of the richer hub entities in the repo because it demonstrates how the framework stack becomes a real application with app-level concerns such as auth, DB initialization, request routing, and UI serving.

## Key Types

| Type / subsystem | Source | Role |
|------------------|--------|------|
| CLI commands | `python/packages/autogen-studio/autogenstudio/cli.py` | Launch UI, serving mode, lite mode, and version commands |
| FastAPI app | `python/packages/autogen-studio/autogenstudio/web/app.py` | Main application assembly, routes, middleware, and static serving |
| `DatabaseManager` | `python/packages/autogen-studio/autogenstudio/database/db_manager.py` | Persistence bootstrap, schema initialization, CRUD helpers |
| `TeamManager` | `python/packages/autogen-studio/autogenstudio/teammanager/teammanager.py` | Team loading, env injection, run and run-stream orchestration |
| `LiteStudio` | `python/packages/autogen-studio/autogenstudio/lite/studio.py` | Lightweight launch path for quick experiments |

## Architecture

Studio has three main architectural bands.

The first is the **launch and environment band**. The CLI in `cli.py` exposes `ui`, `serve`, `lite`, and `version` commands. These commands primarily do one thing: translate user intent into environment variables and then launch the right FastAPI or Uvicorn entrypoint. This makes Studio’s CLI more like an app bootstrapper than like a framework command surface.

The second is the **web application band**. `web/app.py` composes the FastAPI app: it initializes managers in the lifespan function, registers auth dependencies, adds CORS and auth middleware, builds an `/api` sub-application, mounts routers for sessions, runs, teams, validation, settings, gallery, auth, websocket, and MCP routes, and finally serves the frontend and file surfaces as static content. This file makes the ownership boundary unmistakable: Studio owns HTTP surfaces, auth middleware, and UI serving in addition to agent execution.

The third is the **team and persistence band**. `DatabaseManager` owns SQLModel-backed database initialization, schema checks, migrations, and CRUD-like operations. `TeamManager` loads team definitions from JSON/YAML or `ComponentModel`, injects environment variables when needed, instantiates a `BaseGroupChat`, wires input functions into user proxies, and runs teams either synchronously or as streams while surfacing LLM-call events.

## Runtime Behavior

Studio’s runtime story is application-oriented rather than framework-oriented.

1. A CLI command such as `autogenstudio ui` or `autogenstudio lite` is invoked.
2. The CLI writes a temporary env file containing app configuration such as host, port, docs visibility, app directory, DB URI, auth config, or lite-mode flags.
3. Uvicorn launches `autogenstudio.web.app:app`.
4. The FastAPI lifespan hook initializes managers, auth dependencies, and app resources.
5. Incoming API calls are routed to session, run, team, validation, or MCP handlers.
6. Team execution is delegated through `TeamManager`, which loads a team config, constructs a concrete team, runs it, and streams back messages and LLM events.
7. Persistence and schema management are delegated to `DatabaseManager` and related DB/schema classes.

`LiteStudio` is a useful contrast path. Instead of requiring a full persistent app setup, it can synthesize or serialize a team definition into a temporary JSON file, write environment variables that put Studio into lite mode, and launch the same app with an in-memory SQLite DB and auto-opened browser. That shows that Studio’s runtime has a deliberately lighter “demo/prototype” path alongside the fuller appdir/database path.

## Variants, Boundaries, and Failure Modes

The main boundary is between **framework execution** and **application hosting**. Studio delegates actual team logic to AutoGen framework components, but it owns:

- HTTP and websocket routing
- UI static serving
- auth middleware and config
- database bootstrap and schema evolution
- team-file loading and runtime environment assembly

The README’s security note is also an architectural warning. Studio does not claim production-grade security or auth isolation, and it explicitly tells developers to build their own applications on top of the framework for serious deployments.

## Source Files

| File | Purpose |
|------|---------|
| `python/packages/autogen-studio/README.md` | Architectural positioning and explicit non-production warning |
| `python/packages/autogen-studio/autogenstudio/cli.py` | CLI bootstrap for UI, serve, and lite modes |
| `python/packages/autogen-studio/autogenstudio/web/app.py` | FastAPI app assembly, lifespan, routes, middleware, static mounts |
| `python/packages/autogen-studio/autogenstudio/database/db_manager.py` | DB initialization, schema management, persistence helpers |
| `python/packages/autogen-studio/autogenstudio/teammanager/teammanager.py` | Team config loading and execution orchestration |
| `python/packages/autogen-studio/autogenstudio/lite/studio.py` | Lightweight Studio path for rapid experiments |
| `python/packages/autogen-studio/frontend/` | Frontend build assets and Gatsby/Tailwind UI surface |

## See Also

- [Python AgentChat](python-agentchat.md)
- [Python Extensions](python-extensions.md)
- [Package and Distribution Surface](package-and-distribution-surface.md)
- [Studio as Prototyping Surface](../concepts/studio-as-prototyping-surface.md)
- [Studio on Top of Framework Flow](../syntheses/studio-on-top-of-framework-flow.md)
- [Package Selection and Entrypoint Flow](../syntheses/package-selection-and-entrypoint-flow.md)
