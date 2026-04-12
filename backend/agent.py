import json
import os
import re
import subprocess
import time
import uuid
import warnings
from typing import AsyncGenerator, Literal, Optional

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from opentelemetry import trace
from pydantic_settings import BaseSettings

from observability import (
    get_tracer,
    AgentMetrics,
    RequestTraceStore,
    estimate_tokens,
    extract_usage_metadata,
)

from search_tools import smart_search, find_symbol, read_code_section

warnings.filterwarnings("ignore", category=UserWarning, module="langgraph")
from langgraph.prebuilt import create_react_agent  # noqa: E402

class AgentSettings(BaseSettings):
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    qwen_api_key: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"

config = AgentSettings()

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.join(ROOT_DIR, "docs")

WIKI_NAMESPACES = {
    "claude-code": "docs/claude-code",
    "deepagents": "docs/deepagents-wiki",
    "opencode": "docs/opencode-wiki",
    "openclaw": "docs/openclaw-wiki",
    "autogen": "docs/autogen-wiki",
    "hermes-agent": "docs/hermes-agent-wiki",
}

# Maps each wiki namespace to the directory containing its raw source code.
# Wiki pages reference source paths relative to these directories.
SOURCE_ROOTS = {
    "claude-code": "claude_code",
    "deepagents": "deepagents",
    "opencode": "opencode",
    "openclaw": "openclaw",
    "autogen": "autogen",
    "hermes-agent": "hermes-agent",
}

# --- TOOLS ---

def _safe_read(clean_path: str) -> str:
    """Read a file given a ROOT_DIR-relative path, with security check."""
    target = os.path.abspath(os.path.join(ROOT_DIR, clean_path))
    if not target.startswith(ROOT_DIR):
        return "Error: Access denied. Cannot read outside the workspace."
    if not os.path.exists(target):
        return ""
    with open(target, "r", encoding="utf-8") as f:
        return f.read()


@tool
def read_workspace_file(file_path: str) -> str:
    """Reads the content of a file in the workspace.

    Accepts paths in several forms:
    - Wiki doc paths: docs/claude-code/entities/tool-system.md
    - Source paths with project prefix: deepagents/libs/deepagents/deepagents/graph.py
    - Bare repo-relative source paths: libs/deepagents/deepagents/graph.py
      (the tool will attempt to resolve these against all known source roots)
    """
    try:
        clean_path = file_path
        if clean_path.startswith(ROOT_DIR):
            clean_path = clean_path[len(ROOT_DIR):].lstrip("/")
        elif clean_path.startswith("/"):
            clean_path = clean_path.lstrip("/")

        # Direct lookup first
        content = _safe_read(clean_path)
        if content:
            return content

        # Fallback: try prepending each source root for bare repo-relative paths
        if not clean_path.startswith("docs/"):
            for ns, source_dir in SOURCE_ROOTS.items():
                if clean_path.startswith(source_dir + "/"):
                    break  # already has project prefix, don't double-prefix
            else:
                for ns, source_dir in SOURCE_ROOTS.items():
                    candidate = f"{source_dir}/{clean_path}"
                    content = _safe_read(candidate)
                    if content:
                        return content

        return f"Error: File '{clean_path}' does not exist in the workspace."
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def read_source_file(namespace: str, file_path: str) -> str:
    """Reads a source code file from a specific project repository.

    Use this when wiki pages reference source paths (e.g. in Source Files tables).
    Wiki pages use paths relative to their project root — this tool resolves them.

    Args:
        namespace: Project namespace. One of: 'claude-code', 'deepagents',
            'opencode', 'openclaw', 'autogen', 'hermes-agent'.
        file_path: Path relative to the project root
            (e.g. 'libs/deepagents/deepagents/middleware/memory.py').
    """
    if namespace not in SOURCE_ROOTS:
        available = ", ".join(SOURCE_ROOTS.keys())
        return f"Unknown namespace '{namespace}'. Available: {available}"
    try:
        clean_path = file_path.lstrip("/")
        full_path = f"{SOURCE_ROOTS[namespace]}/{clean_path}"
        content = _safe_read(full_path)
        if content:
            return content
        return f"Error: File '{clean_path}' does not exist in the '{namespace}' source tree ({SOURCE_ROOTS[namespace]}/)."
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def search_knowledge_base(query: str, namespace: str = "") -> str:
    """Searches the wiki documentation for a text query.

    Args:
        query: Text or keyword to search for.
        namespace: Optional wiki namespace to scope the search. One of:
            'claude-code', 'deepagents', 'opencode', 'openclaw', 'autogen', 'hermes-agent'.
            Leave empty to search all namespaces.
    """
    try:
        if namespace and namespace in WIKI_NAMESPACES:
            search_dir = os.path.join(ROOT_DIR, WIKI_NAMESPACES[namespace])
            path_prefix = WIKI_NAMESPACES[namespace] + "/"
        else:
            search_dir = DOCS_DIR
            path_prefix = "docs/"

        res = subprocess.run(
            ["grep", "-r", "-i", "-n", "--include=*.md", query, "."],
            cwd=search_dir,
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            return "No matches found."

        lines = res.stdout.split("\n")
        # Normalise paths so they are ROOT_DIR-relative (e.g. docs/claude-code/…)
        normalised = []
        for line in lines:
            if line.startswith("./"):
                line = path_prefix + line[2:]
            normalised.append(line)

        result = "\n".join(normalised[:50])
        if len(normalised) > 50:
            result += "\n... (truncated)"
        return result
    except Exception as e:
        return f"Error searching: {e}"


@tool
def list_wiki_pages(namespace: str) -> str:
    """Lists all available wiki pages in a given namespace.

    Args:
        namespace: One of 'claude-code', 'deepagents', 'opencode', 'openclaw', 'autogen', 'hermes-agent'.
    """
    if namespace not in WIKI_NAMESPACES:
        available = ", ".join(WIKI_NAMESPACES.keys())
        return f"Unknown namespace '{namespace}'. Available: {available}"

    ns_dir = os.path.join(ROOT_DIR, WIKI_NAMESPACES[namespace])
    pages = []
    for root, _, files in os.walk(ns_dir):
        for fname in sorted(files):
            if fname.endswith(".md"):
                rel = os.path.relpath(os.path.join(root, fname), ROOT_DIR)
                pages.append(rel)
    return "\n".join(pages) if pages else "No pages found."


@tool
def propose_doc_change(changes: str) -> str:
    """Proposes documentation changes for user approval. The user will see
    a diff and must click Approve before any files are written or git
    operations are performed.

    IMPORTANT: You must ALWAYS use this tool when you want to update wiki
    documentation. You cannot write files or run git commands directly.

    Args:
        changes: A JSON string with the structure:
            {
                "summary": "Brief description of what changed and why",
                "commit_message": "docs(namespace): concise commit message",
                "files": [
                    {
                        "path": "docs/deepagents-wiki/entities/memory-system.md",
                        "content": "The complete new content of the file"
                    }
                ]
            }
    """
    import json as _json
    from proposals import proposal_store, FileChange, compute_diff, ALLOWED_PATH_PREFIX

    try:
        data = _json.loads(changes)
    except _json.JSONDecodeError as e:
        return f"Error: Invalid JSON — {e}"

    summary = data.get("summary", "")
    commit_message = data.get("commit_message", "")
    files_data = data.get("files", [])

    if not files_data:
        return "Error: No files specified in the proposal."
    if not summary:
        return "Error: A summary is required."
    if not commit_message:
        return "Error: A commit_message is required."

    file_changes: list[FileChange] = []
    for f in files_data:
        path = f.get("path", "")
        if not path.startswith(ALLOWED_PATH_PREFIX):
            return f"Error: Path '{path}' is outside the allowed '{ALLOWED_PATH_PREFIX}' directory."

        new_content = f.get("content", "")
        original = _safe_read(path)
        if original.startswith("Error:"):
            original = ""

        diff = compute_diff(path, original, new_content)
        file_changes.append(FileChange(
            path=path,
            original_content=original,
            proposed_content=new_content,
            diff=diff,
        ))

    proposal = proposal_store.create(
        summary=summary, commit_message=commit_message, files=file_changes,
    )

    response_parts = [
        f"📋 **Documentation Change Proposal** (ID: `{proposal.id}`)\n",
        f"**Summary:** {summary}\n",
        f"**Commit:** `{commit_message}`\n",
        "**Proposed changes:**\n",
    ]
    for fc in file_changes:
        response_parts.append(f"### `{fc.path}`\n```diff\n{fc.diff}\n```\n")
    response_parts.append(f"⏳ Awaiting your approval. Proposal ID: `{proposal.id}`")

    return "\n".join(response_parts)


tools = [
    smart_search,
    find_symbol,
    read_code_section,
    read_workspace_file,
    read_source_file,
    list_wiki_pages,
    propose_doc_change,
]

# --- MODEL ROUTING ---

def get_chat_model(model_id: Literal["deepseek", "qwen", "openai", "ollama"]) -> ChatOpenAI:
    if model_id == "ollama":
        from security import settings as _settings
        chat_url = _settings.ollama_chat_url or _settings.ollama_base_url
        return ChatOpenAI(
            model=_settings.ollama_chat_model,
            api_key="ollama",
            base_url=f"{chat_url}/v1",
            max_tokens=2000,
        )
    if model_id == "deepseek":
        return ChatOpenAI(
            model="deepseek-chat",
            api_key=config.deepseek_api_key,
            base_url="https://api.deepseek.com",
            max_tokens=2000,
        )
    if model_id == "qwen":
        return ChatOpenAI(
            model="qwen-plus",
            api_key=config.qwen_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            max_tokens=2000,
        )
    return ChatOpenAI(model="gpt-4o", api_key=config.openai_api_key, max_tokens=2000)


# --- SYSTEM PROMPT ---

def build_system_prompt(page_context: Optional[dict] = None) -> str:
    prompt = """You are a Wiki Knowledge Assistant embedded in a documentation site that covers multiple AI agent codebases.

Available wiki namespaces:
- **Claude Code** (docs/claude-code/) — Claude Code CLI: agent system, tool system, permission model, MCP, skills, memory, state management
- **Deep Agents** (docs/deepagents-wiki/) — DeepAgents framework: graph factory, subagent system, session persistence, ACP server, evals
- **OpenCode** (docs/opencode-wiki/) — OpenCode AI coding assistant: session system, provider system, LSP integration, plugin system
- **OpenClaw** (docs/openclaw-wiki/) — OpenClaw personal assistant: gateway control plane, channel system, routing, voice/media stack
- **AutoGen** (docs/autogen-wiki/) — Microsoft AutoGen: core runtime, AgentChat, distributed workers, model clients, AutoGen Studio
- **Hermes Agent** (docs/hermes-agent-wiki/) — Hermes conversational agent: agent loop, prompt assembly, tool registry, memory/learning

Each namespace contains:
- summaries/ — architecture overview, codebase map, glossary
- entities/ — deep dives into specific systems/components
- concepts/ — cross-cutting design patterns
- syntheses/ — how multiple systems work together end-to-end

Source code repositories:
Each wiki documents a project whose source code is available in the workspace under its own directory:
- claude-code → claude_code/
- deepagents → deepagents/
- opencode → opencode/
- openclaw → openclaw/
- autogen → autogen/
- hermes-agent → hermes-agent/

Wiki pages reference source files using paths relative to their project root (e.g. a Deep Agents page
may cite `libs/deepagents/deepagents/middleware/memory.py` — the actual file is at `deepagents/libs/deepagents/deepagents/middleware/memory.py`).

When answering:
1. Use the available tools to look up relevant wiki pages before answering.
2. Prefer `list_wiki_pages` to discover pages, then `read_workspace_file` to read them.
3. Use `smart_search` when looking for a specific term or concept across all pages.
4. When you need to read actual source code referenced in a wiki page, use `read_source_file` with the
   appropriate namespace and the repo-relative path shown in the wiki page.
5. Provide clear, accurate answers grounded in the documentation.
6. End your response with a "**Sources:**" section listing each relative file path you read (e.g. `docs/claude-code/entities/tool-system.md`).

Code search strategy:
1. When asked about a specific function, class, or symbol, use `find_symbol` first.
2. If `find_symbol` returns no results, use `smart_search` with scope="code".
3. If you still can't find it, try `smart_search` with a broader scope="auto".
4. Once you find the file, use `read_code_section` to read just that symbol — do NOT read the entire file.
5. Do NOT retry the same search more than twice with the same query. Rephrase or use a different tool.
6. If you cannot find the code after 3 different search attempts, explain what you searched for and that it was not found.

Documentation updates:
- You operate in READ-ONLY mode by default. You CANNOT write files or run git commands directly.
- When you believe documentation should be updated, use `propose_doc_change` to create a proposal.
- The proposal shows the user a diff. Changes are ONLY applied after the user clicks Approve.
- You may ONLY propose changes to files under the `docs/` directory.
- Always provide the COMPLETE new file content in the proposal, not just the changed section.
- Use conventional commit messages: `docs(namespace): description`."""

    if page_context:
        title = page_context.get("title", "").strip()
        url = page_context.get("url", "").strip()
        if title or url:
            prompt += f"\n\nThe user is currently reading: **{title}**"
            if url:
                prompt += f" ({url})"
            prompt += "\nPrioritise answering in the context of this page when relevant."

    return prompt


def _measure_prompt(system_prompt: str, history: list, query: str) -> dict:
    """Measure prompt assembly sizes for observability."""
    history_chars = sum(len(content) for _, content in history)
    return {
        "system_prompt_chars": len(system_prompt),
        "history_turns": len(history),
        "history_chars": history_chars,
        "query_chars": len(query),
        "total_chars": len(system_prompt) + history_chars + len(query),
    }


# --- HISTORY HELPERS ---

def _format_history(chat_history: list) -> list:
    """Convert [{role, content}] dicts to LangChain (role, content) tuples."""
    result = []
    for msg in chat_history:
        role = "user" if msg.get("role") == "user" else "assistant"
        content = msg.get("content", "").strip()
        if content:
            result.append((role, content))
    return result


# --- AGENT RUNNERS ---

def run_agent(
    query: str,
    chat_history: list,
    model_id: str = "deepseek",
    page_context: Optional[dict] = None,
    agent_metrics: Optional[AgentMetrics] = None,
    trace_store: Optional[RequestTraceStore] = None,
    context_engine: Optional["ContextEngine"] = None,
) -> str:
    """Blocking agent execution (kept for backward compatibility with /chat endpoint)."""
    tracer = get_tracer()
    request_id = str(uuid.uuid4())
    start_time = time.time()

    with tracer.start_as_current_span("agent.react_loop") as span:
        span.set_attribute("request.id", request_id)
        span.set_attribute("request.model", model_id)
        span.set_attribute("request.query", query[:200])

        llm = get_chat_model(model_id)
        agent = create_react_agent(llm, tools=tools, recursion_limit=25)

        system_prompt = build_system_prompt(page_context)
        history = _format_history(chat_history)

        if context_engine:
            assembled = context_engine.assemble(
                system_prompt=system_prompt,
                messages=[{"role": r, "content": c} for r, c in history],
                query=query,
            )
            messages = [(m["role"], m["content"]) for m in assembled["messages"]]
            prompt_info = _measure_prompt(system_prompt, history, query)
            prompt_info["total_chars"] = assembled["total_tokens"] * 4
        else:
            messages = [("system", system_prompt)]
            messages.extend(history)
            messages.append(("user", query))
            prompt_info = _measure_prompt(system_prompt, history, query)

        span.set_attribute("prompt.total_chars", prompt_info["total_chars"])
        span.set_attribute("prompt.history_turns", prompt_info["history_turns"])
        span.set_attribute("prompt.system_prompt_chars", prompt_info["system_prompt_chars"])
        span.set_attribute("llm.messages", json.dumps(messages, ensure_ascii=False))

        try:
            response = agent.invoke({"messages": messages})
            reply = response["messages"][-1].content
            span.set_attribute("llm.response", str(reply))
            duration_ms = int((time.time() - start_time) * 1000)

            # Extract token usage from ALL AI messages (multi-turn ReAct loop)
            total_input = 0
            total_output = 0
            for msg in response["messages"]:
                msg_usage = extract_usage_metadata(msg)
                total_input += msg_usage["input_tokens"]
                total_output += msg_usage["output_tokens"]
            usage = {
                "input_tokens": total_input,
                "output_tokens": total_output,
                "total_tokens": total_input + total_output,
            }

            span.set_attribute("llm.total_tokens", usage["total_tokens"])
            span.set_attribute("agent.duration_ms", duration_ms)

            if agent_metrics:
                agent_metrics.requests_total.add(1, {"model": model_id, "status": "success"})
                agent_metrics.request_duration.record(duration_ms / 1000, {"model": model_id})
                if usage["total_tokens"]:
                    agent_metrics.tokens_total.add(usage["input_tokens"], {"model": model_id, "direction": "input"})
                    agent_metrics.tokens_total.add(usage["output_tokens"], {"model": model_id, "direction": "output"})

            if trace_store:
                trace_store.write(
                    request_id=request_id,
                    model=model_id,
                    query=query,
                    status="success",
                    total_tokens=usage["total_tokens"],
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    prompt_chars=prompt_info["total_chars"],
                    duration_ms=duration_ms,
                )

            return reply
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            span.set_status(trace.StatusCode.ERROR, str(e))
            span.record_exception(e)
            if agent_metrics:
                agent_metrics.requests_total.add(1, {"model": model_id, "status": "error"})
                agent_metrics.errors_total.add(1, {"stage": "agent", "error_type": type(e).__name__})
            if trace_store:
                trace_store.write(
                    request_id=request_id, model=model_id, query=query, status="error",
                    duration_ms=duration_ms, error_message=str(e)[:500],
                )
            return f"Agent execution failed: {e}"


async def run_agent_stream(
    query: str,
    chat_history: list,
    model_id: str = "deepseek",
    page_context: Optional[dict] = None,
    agent_metrics: Optional[AgentMetrics] = None,
    trace_store: Optional[RequestTraceStore] = None,
    context_engine: Optional["ContextEngine"] = None,
) -> AsyncGenerator[dict, None]:
    """Streaming agent execution with full observability."""
    tracer = get_tracer()
    request_id = str(uuid.uuid4())
    start_time = time.time()

    # Accumulators for trace summary
    total_input_tokens = 0
    total_output_tokens = 0
    llm_call_count = 0
    tool_call_count = 0
    search_call_count = 0
    tools_used: list[str] = []
    retrieval_chars = 0

    with tracer.start_as_current_span("agent.react_loop") as root_span:
        root_span.set_attribute("request.id", request_id)
        root_span.set_attribute("request.model", model_id)
        root_span.set_attribute("request.query", query[:200])

        llm = get_chat_model(model_id)
        agent = create_react_agent(llm, tools=tools, recursion_limit=25)

        system_prompt = build_system_prompt(page_context)
        history = _format_history(chat_history)

        if context_engine:
            assembled = context_engine.assemble(
                system_prompt=system_prompt,
                messages=[{"role": r, "content": c} for r, c in history],
                query=query,
            )
            messages = [(m["role"], m["content"]) for m in assembled["messages"]]
            prompt_info = _measure_prompt(system_prompt, history, query)
            prompt_info["total_chars"] = assembled["total_tokens"] * 4
        else:
            messages = [("system", system_prompt)]
            messages.extend(history)
            messages.append(("user", query))
            prompt_info = _measure_prompt(system_prompt, history, query)

        root_span.set_attribute("prompt.total_chars", prompt_info["total_chars"])
        root_span.set_attribute("prompt.history_turns", prompt_info["history_turns"])
        root_span.set_attribute("prompt.system_prompt_chars", prompt_info["system_prompt_chars"])
        root_span.set_attribute("llm.messages", json.dumps(messages, ensure_ascii=False))

        cited_files: set[str] = set()
        active_tool_spans: dict[str, trace.Span] = {}
        tool_start_times: dict[str, float] = {}
        full_reply = ""

        try:
            async for event in agent.astream_events({"messages": messages}, version="v2"):
                event_type = event["event"]

                if event_type == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    content = chunk.content if hasattr(chunk, "content") else ""
                    if isinstance(content, str) and content:
                        full_reply += content
                        yield {"type": "token", "content": content}

                    # Check for usage metadata on stream end
                    if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                        usage = chunk.usage_metadata
                        total_input_tokens += usage.get("input_tokens", 0) or 0
                        total_output_tokens += usage.get("output_tokens", 0) or 0

                elif event_type == "on_chat_model_start":
                    llm_call_count += 1
                    if agent_metrics:
                        agent_metrics.llm_calls_total.add(1, {"model": model_id, "iteration": str(llm_call_count)})

                elif event_type == "on_tool_start":
                    tool_name = event["name"]
                    tool_input = event["data"].get("input", {})
                    run_id = event.get("run_id", tool_name)

                    tool_call_count += 1
                    tools_used.append(tool_name)

                    # Create a child span for this tool call
                    tool_span = tracer.start_span(
                        f"tool.{tool_name}",
                        attributes={
                            "tool.name": tool_name,
                            "tool.input": str(tool_input)[:500],
                        },
                    )
                    active_tool_spans[run_id] = tool_span
                    tool_start_times[run_id] = time.time()

                    if tool_name in ("search_knowledge_base", "smart_search", "find_symbol"):
                        search_call_count += 1

                    yield {"type": "tool_call", "name": tool_name, "input": str(tool_input)[:200]}

                    if tool_name == "read_workspace_file" and isinstance(tool_input, dict):
                        path = tool_input.get("file_path", "").strip().lstrip("/")
                        if path:
                            cited_files.add(path)
                    elif tool_name == "read_source_file" and isinstance(tool_input, dict):
                        ns = tool_input.get("namespace", "")
                        path = tool_input.get("file_path", "").strip().lstrip("/")
                        if ns and path and ns in SOURCE_ROOTS:
                            cited_files.add(f"{SOURCE_ROOTS[ns]}/{path}")

                elif event_type == "on_tool_end":
                    tool_name = event["name"]
                    output = event["data"].get("output", "")
                    run_id = event.get("run_id", tool_name)

                    output_size = len(output) if isinstance(output, str) else 0
                    retrieval_chars += output_size

                    # Close the tool span
                    tool_span = active_tool_spans.pop(run_id, None)
                    if tool_span:
                        tool_duration = max(0.0, time.time() - tool_start_times.pop(run_id, start_time))
                        tool_span.set_attribute("tool.output_size", output_size)
                        tool_span.set_attribute("tool.status", "success")
                        tool_span.end()
                        if agent_metrics:
                            agent_metrics.tool_calls_total.add(1, {"tool_name": tool_name, "status": "success"})
                            agent_metrics.tool_call_duration.record(tool_duration, {"tool_name": tool_name})

                    if tool_name == "search_knowledge_base" and isinstance(output, str):
                        for line in output.splitlines():
                            m = re.match(r"^(docs/[\w/\-]+\.md):", line)
                            if m:
                                cited_files.add(m.group(1))

                    elif tool_name == "propose_doc_change" and isinstance(output, str):
                        pid_match = re.search(r"Proposal ID: `(\w+)`", output)
                        if pid_match:
                            from proposals import proposal_store as _ps
                            pid = pid_match.group(1)
                            prop = _ps.get(pid)
                            if prop:
                                yield {
                                    "type": "proposal",
                                    "proposal_id": pid,
                                    "summary": prop.summary,
                                    "commit_message": prop.commit_message,
                                    "files": [
                                        {"path": f.path, "diff": f.diff}
                                        for f in prop.files
                                    ],
                                }

            # --- Request complete: record summary ---
            duration_ms = int((time.time() - start_time) * 1000)
            total_tokens = total_input_tokens + total_output_tokens

            root_span.set_attribute("llm.response", full_reply)

            # If no usage metadata was available, estimate from prompt size
            estimated = total_tokens == 0
            if estimated:
                total_input_tokens = estimate_tokens(
                    system_prompt + query + "".join(c for _, c in history)
                )
                total_tokens = total_input_tokens
            root_span.set_attribute("agent.tokens_estimated", estimated)

            root_span.set_attribute("agent.total_tokens", total_tokens)
            root_span.set_attribute("agent.input_tokens", total_input_tokens)
            root_span.set_attribute("agent.output_tokens", total_output_tokens)
            root_span.set_attribute("agent.llm_calls", llm_call_count)
            root_span.set_attribute("agent.tool_calls", tool_call_count)
            root_span.set_attribute("agent.search_calls", search_call_count)
            root_span.set_attribute("agent.retrieval_chars", retrieval_chars)
            root_span.set_attribute("agent.citations_count", len(cited_files))
            root_span.set_attribute("agent.duration_ms", duration_ms)

            if agent_metrics:
                agent_metrics.requests_total.add(1, {"model": model_id, "status": "success"})
                agent_metrics.request_duration.record(duration_ms / 1000, {"model": model_id})
                agent_metrics.tokens_total.add(total_input_tokens, {"model": model_id, "direction": "input"})
                agent_metrics.tokens_total.add(total_output_tokens, {"model": model_id, "direction": "output"})
                agent_metrics.prompt_tokens_hist.record(estimate_tokens(system_prompt + query + "".join(c for _, c in history)), {"model": model_id})
                agent_metrics.retrieval_chars_hist.record(retrieval_chars)

            if trace_store:
                trace_store.write(
                    request_id=request_id,
                    model=model_id,
                    query=query,
                    status="success",
                    total_tokens=total_tokens,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    llm_calls=llm_call_count,
                    tool_calls=tool_call_count,
                    search_calls=search_call_count,
                    prompt_chars=prompt_info["total_chars"],
                    retrieval_chars=retrieval_chars,
                    citations_count=len(cited_files),
                    duration_ms=duration_ms,
                    tools_used=",".join(tools_used),
                )

            if cited_files:
                yield {"type": "citations", "sources": sorted(cited_files)}
            yield {"type": "done"}

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            root_span.set_status(trace.StatusCode.ERROR, str(e))
            root_span.record_exception(e)

            # Clean up any open tool spans
            for span_obj in active_tool_spans.values():
                span_obj.set_attribute("tool.status", "error")
                span_obj.end()

            if agent_metrics:
                agent_metrics.requests_total.add(1, {"model": model_id, "status": "error"})
                agent_metrics.errors_total.add(1, {"stage": "agent", "error_type": type(e).__name__})

            if trace_store:
                trace_store.write(
                    request_id=request_id, model=model_id, query=query, status="error",
                    llm_calls=llm_call_count, tool_calls=tool_call_count,
                    duration_ms=duration_ms, error_message=str(e)[:500],
                )

            yield {"type": "error", "detail": str(e)}
            yield {"type": "done"}
