# Studio as Prototyping Surface

## Overview

AutoGen Studio is intentionally positioned as a prototyping application, not as the canonical framework runtime for production deployments. This distinction is explicit in its README and shapes how the rest of the architecture should be interpreted. Studio demonstrates how the framework stack can become an app, but it should not be mistaken for the layer that owns the core runtime design.

## Mechanism

Studio acts as a prototyping surface by doing three things:

1. It accepts declarative team definitions and related environment/config input.
2. It wraps framework execution in a web app with persistence, validation, and user-facing run/session management.
3. It offers a lighter “lite” mode so users can rapidly test team configurations without the full persistent app setup.

The framework logic itself still comes from AgentChat, Core, and Extensions. Studio provides the application shell, not the underlying runtime semantics.

## Involved Entities

- [AutoGen Studio](../entities/autogen-studio.md)
- [Python AgentChat](../entities/python-agentchat.md)
- [Python Extensions](../entities/python-extensions.md)
- [Package and Distribution Surface](../entities/package-and-distribution-surface.md)

## Source Evidence

- `python/packages/autogen-studio/README.md` states that Studio is not meant to be a production-ready app.
- `python/packages/autogen-studio/autogenstudio/web/app.py` shows app-level concerns such as HTTP routes, middleware, and static serving.
- `python/packages/autogen-studio/autogenstudio/teammanager/teammanager.py` shows that actual team execution is delegated into framework-derived team objects.
- `python/packages/autogen-studio/autogenstudio/lite/studio.py` shows the lightweight experimentation path.

## See Also

- [AutoGen Studio](../entities/autogen-studio.md)
- [Package and Distribution Surface](../entities/package-and-distribution-surface.md)
- [Layered API Architecture](layered-api-architecture.md)
- [Studio on Top of Framework Flow](../syntheses/studio-on-top-of-framework-flow.md)
- [Package Selection and Entrypoint Flow](../syntheses/package-selection-and-entrypoint-flow.md)
