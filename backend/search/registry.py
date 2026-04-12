"""Repository registry with metadata and query-to-repo targeting."""

import re
from dataclasses import dataclass, field


@dataclass
class RepoMeta:
    namespace: str
    source_dir: str
    wiki_dir: str
    languages: list[str]
    keywords: list[str]
    description: str
    file_count: int = 0


_REPO_DEFS: list[dict] = [
    {
        "namespace": "claude-code",
        "source_dir": "claude_code",
        "wiki_dir": "docs/claude-code",
        "languages": ["typescript", "python"],
        "keywords": [
            "claude code", "tool system", "mcp", "permissions", "permission model",
            "skills", "cli", "state management", "slash commands", "tengu",
        ],
        "description": "Claude Code CLI: agent system, tool system, permission model, MCP, skills, memory, state management",
    },
    {
        "namespace": "deepagents",
        "source_dir": "deepagents",
        "wiki_dir": "docs/deepagents-wiki",
        "languages": ["python", "typescript"],
        "keywords": [
            "deep agents", "deepagents", "graph factory", "subagent", "session persistence",
            "acp server", "evals", "middleware", "backend protocol",
        ],
        "description": "DeepAgents framework: graph factory, subagent system, session persistence, ACP server, evals",
    },
    {
        "namespace": "opencode",
        "source_dir": "opencode",
        "wiki_dir": "docs/opencode-wiki",
        "languages": ["typescript"],
        "keywords": [
            "opencode", "session system", "provider system", "lsp", "plugin system",
            "tui", "terminal ui", "bun",
        ],
        "description": "OpenCode AI coding assistant: session system, provider system, LSP integration, plugin system",
    },
    {
        "namespace": "openclaw",
        "source_dir": "openclaw",
        "wiki_dir": "docs/openclaw-wiki",
        "languages": ["typescript", "javascript"],
        "keywords": [
            "openclaw", "gateway", "control plane", "channel system", "routing",
            "voice", "media stack", "eliza", "pnpm",
        ],
        "description": "OpenClaw personal assistant: gateway control plane, channel system, routing, voice/media stack",
    },
    {
        "namespace": "autogen",
        "source_dir": "autogen",
        "wiki_dir": "docs/autogen-wiki",
        "languages": ["python", "csharp"],
        "keywords": [
            "autogen", "agentchat", "distributed workers", "model clients",
            "autogen studio", "microsoft", "magentic", "core runtime",
        ],
        "description": "Microsoft AutoGen: core runtime, AgentChat, distributed workers, model clients, AutoGen Studio",
    },
    {
        "namespace": "hermes-agent",
        "source_dir": "hermes-agent",
        "wiki_dir": "docs/hermes-agent-wiki",
        "languages": ["python"],
        "keywords": [
            "hermes", "hermes agent", "agent loop", "prompt assembly",
            "tool registry", "memory", "learning", "conversational",
        ],
        "description": "Hermes conversational agent: agent loop, prompt assembly, tool registry, memory/learning",
    },
]


class RepoRegistry:
    def __init__(self) -> None:
        self.repos: list[RepoMeta] = [RepoMeta(**d) for d in _REPO_DEFS]
        self._by_namespace: dict[str, RepoMeta] = {r.namespace: r for r in self.repos}

    def get_by_namespace(self, namespace: str) -> RepoMeta | None:
        return self._by_namespace.get(namespace)

    def target(
        self,
        query: str,
        page_url: str = "",
        namespace: str = "",
    ) -> list[RepoMeta]:
        if namespace:
            repo = self.get_by_namespace(namespace)
            return [repo] if repo else self.repos

        primary_from_url: RepoMeta | None = None
        if page_url:
            for repo in self.repos:
                wiki_suffix = repo.wiki_dir.replace("docs/", "")
                if wiki_suffix in page_url:
                    primary_from_url = repo
                    break

        query_lower = query.lower()
        scores: list[tuple[float, RepoMeta]] = []
        for repo in self.repos:
            score = 0.0
            for kw in repo.keywords:
                if kw in query_lower:
                    score += len(kw)
            if repo.namespace in query_lower:
                score += 20
            scores.append((score, repo))

        scores.sort(key=lambda x: x[0], reverse=True)

        result: list[RepoMeta] = []
        seen: set[str] = set()

        if primary_from_url:
            result.append(primary_from_url)
            seen.add(primary_from_url.namespace)

        for score, repo in scores:
            if repo.namespace not in seen:
                if score > 0 or not result:
                    result.append(repo)
                    seen.add(repo.namespace)

        return result if result else self.repos


repo_registry = RepoRegistry()
