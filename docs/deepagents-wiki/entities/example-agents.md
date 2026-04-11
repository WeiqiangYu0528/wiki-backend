# Example Agents

## Overview

The `examples/` directory contains six reference agent implementations that demonstrate how the Deep Agents SDK's abstractions — memory (`AGENTS.md`), skills (`SKILL.md`), subagents, filesystem backends, and sandbox execution — are meant to be composed in real applications. Each example is a self-contained project with its own `pyproject.toml`, `uv.lock`, and README. They are not toy scripts: they illustrate distinct architectural patterns such as the research-delegation loop, file-system-as-memory, structured-output pipelines, the autonomous looping (Ralph) pattern, multi-model orchestration with GPU execution, and the self-hosted async subagent server pattern.

## Key Types / Key Concepts

Core patterns illustrated across the examples:

- **Research loop** (`deep_research`, `nvidia_deep_agent`): orchestrator delegates to parallel sub-agents, synthesizes results, reflects via a `think_tool`.
- **Memory + skills** (`content-builder-agent`, `downloading_agents`): agent behavior driven entirely by files — `AGENTS.md` for persistent context, `skills/*/SKILL.md` for on-demand workflows.
- **Structured output / planning** (`text-to-sql-agent`): `write_todos` for planning, skill-defined SQL workflow, Chinook demo database.
- **Autonomous looping** (`ralph_mode`): fresh context each iteration, filesystem + git as the only persistence layer.
- **Self-hosted async subagent** (`async-subagent-server`): Agent Protocol HTTP server exposing a researcher agent for delegation by a supervisor.
- **Multi-model + GPU execution** (`nvidia_deep_agent`): frontier model orchestrates, Nemotron Super handles research volume, data-processor subagent runs RAPIDS scripts in a Modal GPU sandbox.

## Architecture

### `deep_research`

Multi-step web research agent using Tavily for URL discovery and full-page content fetching. The orchestrator follows a 5-step workflow (save request → plan with todos → delegate to sub-agents → synthesize → respond). Individual researcher sub-agents each perform 2–5 targeted Tavily searches followed by `think_tool` reflection before returning findings. Maximum 3 parallel sub-agents, maximum 3 iteration rounds.

**Key configuration:**
```python
agent = create_deep_agent(
    model=model,   # Claude or Gemini
    tools=[tavily_search, think_tool],
)
```
Custom instruction sets live in `research_agent/prompts.py`: `RESEARCH_WORKFLOW_INSTRUCTIONS`, `SUBAGENT_DELEGATION_INSTRUCTIONS`, and `RESEARCHER_INSTRUCTIONS`.

**Demonstrates:** Subagent delegation at scale, multi-provider model support (Claude + Gemini), strategic reflection tooling.

**Run:**
```bash
cd examples/deep_research
langgraph dev   # opens LangGraph Studio
```

---

### `content-builder-agent`

Content writing agent for blog posts, LinkedIn posts, and tweets with AI-generated cover images. The entire agent is configured by files on disk rather than code:

```
content-builder-agent/
├── AGENTS.md                    # brand voice & style guide (always loaded)
├── subagents.yaml               # researcher subagent definition
└── skills/
    ├── blog-post/SKILL.md       # blog structure, SEO, research-first workflow
    └── social-media/SKILL.md    # platform formats, character limits, hashtags
```

```python
agent = create_deep_agent(
    memory=["./AGENTS.md"],
    skills=["./skills/"],
    tools=[generate_cover, generate_social_image],
    subagents=load_subagents("./subagents.yaml"),
    backend=FilesystemBackend(root_dir="./"),
)
```

**Flow:** Agent receives task → loads matching skill → delegates research to `researcher` subagent (saves to `research/`) → writes content → generates cover image via Gemini Imagen.

**Demonstrates:** Memory (`AGENTS.md`), skills, subagents, and custom tools all working together. Adding a new content type requires only a new `skills/<name>/SKILL.md` file.

---

### `text-to-sql-agent`

Natural language to SQL agent against the [Chinook database](https://github.com/lerocha/chinook-database) (a digital media store). Uses `write_todos` for planning complex multi-step queries and a skill-defined SQL workflow. The Chinook SQLite file is downloaded separately.

**Demonstrates:** Planning middleware, skill-based structured workflows, filesystem backend for context management, structured output validation.

**Run:**
```bash
cd examples/text-to-sql-agent
python agent.py "What are the top 5 best-selling artists?"
```

---

### `ralph_mode`

The autonomous looping pattern. Ralph runs an agent in an infinite loop where each iteration starts with completely fresh context — no conversation history is carried forward. The filesystem and git serve as the only memory and work log between iterations.

The core concept (from [Geoff Huntley](https://ghuntley.com)):
```bash
while :; do cat PROMPT.md | agent; done
```

The deepagents implementation adds model selection, iteration limits, remote sandbox support, and a shell allow-list:

```bash
python ralph_mode.py "Build a REST API" --iterations 5
python ralph_mode.py "Build an app" --sandbox modal
python ralph_mode.py "Build an app" --shell-allow-list recommended
```

**Demonstrates:** Autonomous looping pattern, fresh-context context management, remote sandbox integration (AgentCore, Modal, Daytona, Runloop), filesystem-as-memory.

---

### `nvidia_deep_agent`

Multi-model agent showcasing GPU code execution. A frontier model (Claude) orchestrates; NVIDIA Nemotron Super handles research volume; a `data-processor-agent` subagent writes and executes Python scripts on a Modal GPU sandbox (NVIDIA RAPIDS — cuDF, cuML).

```
create_deep_agent (orchestrator: frontier model)
    |-- researcher-agent (Nemotron Super via NVIDIA NIM)
    |-- data-processor-agent (frontier model + GPU Modal sandbox)
    |-- skills/: cudf-analytics, cuml-machine-learning, data-visualization, gpu-document-processing
    |-- memory/: AGENTS.md (self-improving: agent edits its own skill files)
    backend: Modal Sandbox (A10G GPU or CPU, switchable via context_schema)
```

The agent has self-improving memory: when the `data-processor-agent` discovers a library limitation during execution, it updates the relevant `SKILL.md` so the same mistake is not repeated.

**Demonstrates:** Multi-model orchestration, GPU sandbox execution, self-improving skills, the `context_schema` pattern for runtime configuration, skills as GPU API guides.

---

### `async-subagent-server`

A self-hosted [Agent Protocol](https://github.com/langchain-ai/agent-protocol) HTTP server that exposes a Deep Agents researcher as an async subagent. The package includes both sides of the pattern:
- `server.py` — FastAPI server implementing Agent Protocol endpoints
- `supervisor.py` — interactive REPL demonstrating how a supervisor connects and delegates

**Implemented Agent Protocol endpoints:**

| Endpoint | Purpose |
|----------|---------|
| `POST /threads` | Create a thread for a new task |
| `POST /threads/{thread_id}/runs` | Start or interrupt+restart a run |
| `GET /threads/{thread_id}/runs/{run_id}` | Poll run status |
| `GET /threads/{thread_id}` | Fetch thread state (`values.messages`) |
| `POST /threads/{thread_id}/runs/{run_id}/cancel` | Cancel a run |
| `GET /ok` | Health check |

**Demonstrates:** Self-hosted async subagent pattern, Agent Protocol HTTP interface, supervisor–worker delegation, separation of server and client concerns.

---

### `downloading_agents` (bonus)

Illustrates that an agent is just a folder. A zip containing only `AGENTS.md` and `skills/*/SKILL.md` is downloaded, unzipped to `.deepagents/`, and run immediately with `deepagents` — no code, no setup beyond the CLI.

```bash
git init && curl -L .../content-writer.zip -o agent.zip \
  && unzip agent.zip -d .deepagents && rm agent.zip && deepagents
```

**Demonstrates:** Agent portability, the file-system primitive model, zero-code agent distribution.

## Source Files

| File | Purpose |
|------|---------|
| `examples/README.md` | Index of all examples with one-line descriptions |
| `examples/deep_research/` | Multi-step web research agent (Tavily + parallel subagents + reflection) |
| `examples/deep_research/research_agent/prompts.py` | Workflow, delegation, and researcher instruction sets |
| `examples/content-builder-agent/` | Memory + skills + subagents content writing agent |
| `examples/content-builder-agent/content_writer.py` | Agent wiring: memory, skills, tools, subagents |
| `examples/content-builder-agent/AGENTS.md` | Brand voice and style guide (agent memory) |
| `examples/content-builder-agent/skills/` | Blog-post and social-media skill definitions |
| `examples/text-to-sql-agent/` | Natural language to SQL with Chinook database |
| `examples/ralph_mode/ralph_mode.py` | Autonomous looping runner with sandbox support |
| `examples/nvidia_deep_agent/src/agent.py` | Multi-model orchestrator with Modal GPU sandbox |
| `examples/nvidia_deep_agent/skills/` | cudf-analytics, cuml-ml, visualization, gpu-document-processing |
| `examples/async-subagent-server/server.py` | Agent Protocol FastAPI server |
| `examples/async-subagent-server/supervisor.py` | Supervisor REPL for delegation |
| `examples/downloading_agents/content-writer.zip` | Distributable agent artifact (AGENTS.md + skills/) |

## See Also

- [Memory System](./memory-system.md)
- [Skills System](./skills-system.md)
- [Subagent System](./subagent-system.md)
- [Sandbox Partners](./sandbox-partners.md)
- [ACP Server](./acp-server.md)
