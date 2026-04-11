# MkDocs AI Backend

This is the API backend for the Agentic MkDocs Chatbox. It connects the frontend UI floating widget on your documentation site with powerful Local/Remote LLMs and grants runtime abilities like executing git commits directly to the codebase.

## Quickstart

Use `uv` to manage this package.
```bash
uv sync
uv run python generate_secret.py # First-time setup for MFA
uv run fastapi run main.py
```
