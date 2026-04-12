# backend/context_engine/compactor.py
"""Context compactor: prunes old tool outputs to reduce token waste.

Phase 1: Backward-scan tool output pruning.
  - Scans from newest to oldest messages.
  - Protects last N turns (default 4).
  - Replaces old tool results with a pruned placeholder.
  - Preserves tool call metadata (name, args summary).

Phase 2 (future plugin): LLM summarization of pruned regions.
"""

import logging
import math

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / 4)


class ContextCompactor:
    """Prunes old tool outputs to fit within token budget.

    Args:
        protected_turns: Number of recent turns to never prune.
        trigger_pct: Fraction of token_budget that triggers pruning
            when history exceeds this percentage.
    """

    def __init__(
        self,
        protected_turns: int = 4,
        trigger_pct: float = 0.5,
    ) -> None:
        self.protected_turns = protected_turns
        self.trigger_pct = trigger_pct
        self.last_pruned_count = 0
        self.last_chars_saved = 0

    def compact(
        self,
        messages: list[dict],
        token_budget: int,
    ) -> list[dict]:
        """Prune old tool outputs if history exceeds trigger threshold.

        Returns a new list of messages (does not mutate the input).
        """
        self.last_pruned_count = 0
        self.last_chars_saved = 0

        total_chars = sum(len(m.get("content", "")) for m in messages)
        total_tokens = _estimate_tokens("x" * total_chars)

        trigger_threshold = int(token_budget * self.trigger_pct)
        if total_tokens <= trigger_threshold:
            return list(messages)

        # Find turn boundaries (each user message starts a new turn)
        turn_starts: list[int] = []
        for i, m in enumerate(messages):
            if m.get("role") == "user":
                turn_starts.append(i)

        if not turn_starts:
            return list(messages)

        # Protected zone: last N turns
        if len(turn_starts) <= self.protected_turns:
            return list(messages)

        protected_start_idx = turn_starts[-self.protected_turns]

        # Prune tool outputs before the protected zone
        result: list[dict] = []
        for i, m in enumerate(messages):
            if (
                i < protected_start_idx
                and m.get("role") == "tool"
                and len(m.get("content", "")) > 50
            ):
                original_size = len(m["content"])
                tool_name = m.get("name", "unknown")
                pruned_msg = dict(m)
                pruned_msg["content"] = (
                    f"[Tool output pruned — {tool_name}, {original_size} chars]"
                )
                result.append(pruned_msg)
                self.last_pruned_count += 1
                self.last_chars_saved += original_size - len(pruned_msg["content"])
            else:
                result.append(dict(m))

        if self.last_pruned_count > 0:
            logger.info(
                "Compactor pruned %d tool outputs, saved ~%d chars",
                self.last_pruned_count,
                self.last_chars_saved,
            )

        return result
