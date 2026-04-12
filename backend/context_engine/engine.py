# backend/context_engine/engine.py
"""Context engine: pluggable prompt assembly with token budgeting.

Inspired by OpenClaw's assemble()/compact() lifecycle.
Orchestrates: memory injection, history compaction, budget tracking.
"""

import logging

from context_engine.budget import TokenBudget, estimate_tokens
from context_engine.compactor import ContextCompactor
from memory.base import MemoryManager

logger = logging.getLogger(__name__)


class ContextEngine:
    """Orchestrates prompt assembly with token budget enforcement.

    Args:
        memory: Memory manager for retrieving relevant memories.
        compactor: Context compactor for pruning old tool outputs.
        budget: Token budget configuration.
    """

    def __init__(
        self,
        memory: MemoryManager,
        compactor: ContextCompactor,
        budget: TokenBudget,
    ) -> None:
        self.memory = memory
        self.compactor = compactor
        self.budget = budget

    def assemble(
        self,
        system_prompt: str,
        messages: list[dict],
        query: str,
        search_results: str = "",
    ) -> dict:
        """Assemble the full prompt with budget tracking.

        Returns:
            dict with keys:
              - messages: list[dict] — the assembled message list
              - total_tokens: int — estimated total token count
              - budget_summary: dict — per-category budget usage
        """
        self.budget._used.clear()

        augmented_system = self._build_system_prompt(system_prompt, query)
        self.budget.use("system", estimate_tokens(augmented_system))

        history_budget = self.budget.allocate()["history"]
        compacted_messages = self.compactor.compact(messages, token_budget=history_budget)
        history_tokens = sum(estimate_tokens(m.get("content", "")) for m in compacted_messages)
        self.budget.use("history", history_tokens)

        if search_results:
            self.budget.use("search", estimate_tokens(search_results))

        assembled: list[dict] = [{"role": "system", "content": augmented_system}]
        assembled.extend(compacted_messages)
        assembled.append({"role": "user", "content": query})

        total_tokens = sum(estimate_tokens(m.get("content", "")) for m in assembled)

        return {
            "messages": assembled,
            "total_tokens": total_tokens,
            "budget_summary": self.budget.summary(),
        }

    def get_search_budget(self) -> int:
        """Return the token budget available for search results."""
        return self.budget.remaining("search")

    def _build_system_prompt(self, base_prompt: str, query: str) -> str:
        """Augment system prompt with relevant memories."""
        memory_budget = self.budget.allocate()["memory"]

        memories = self.memory.query(query, top_k=5)
        if not memories:
            return base_prompt

        memory_lines: list[str] = []
        memory_tokens = 0
        for mem in memories:
            line = f"- {mem['content']}"
            line_tokens = estimate_tokens(line)
            if memory_tokens + line_tokens > memory_budget:
                break
            memory_lines.append(line)
            memory_tokens += line_tokens

        if not memory_lines:
            return base_prompt

        self.budget.use("memory", memory_tokens)
        memory_section = "\n\nRelevant context from memory:\n" + "\n".join(memory_lines)
        return base_prompt + memory_section
