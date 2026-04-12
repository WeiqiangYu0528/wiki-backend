"""Token budget allocation and tracking for context window management."""

import math
from dataclasses import dataclass, field


def estimate_tokens(text: str) -> int:
    """Estimate token count using chars/4 heuristic (from OpenCode pattern)."""
    if not text:
        return 0
    return math.ceil(len(text) / 4)


# Default budget percentages (from design spec section 6.2)
DEFAULT_BUDGET_PCTS = {
    "system": 0.03,
    "memory": 0.05,
    "history": 0.35,
    "search": 0.25,
    "output": 0.30,
    "safety": 0.02,
}


@dataclass
class TokenBudget:
    """Tracks token allocation across context categories.

    Usage:
        budget = TokenBudget(context_limit=128000)
        alloc = budget.allocate()
        budget.use("system", 300)
        if budget.is_over_budget():
            ...  # trigger compaction
    """

    context_limit: int = 128000
    budget_pcts: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_BUDGET_PCTS))
    _used: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def allocate(self) -> dict[str, int]:
        """Return token allocation per category."""
        return {
            category: int(self.context_limit * pct)
            for category, pct in self.budget_pcts.items()
        }

    def use(self, category: str, tokens: int) -> None:
        """Record token usage for a category."""
        self._used[category] = self._used.get(category, 0) + tokens

    def used(self, category: str) -> int:
        """Return tokens used in a category."""
        return self._used.get(category, 0)

    def remaining(self, category: str) -> int:
        """Return remaining tokens in a category's budget."""
        alloc = self.allocate()
        budget = alloc.get(category, 0)
        return max(0, budget - self.used(category))

    # Categories reserved for output/safety that are not "consumed" by inputs
    _RESERVED: frozenset[str] = frozenset({"output", "safety"})

    def is_over_budget(self) -> bool:
        """Check if total input usage has exceeded the input allocation.

        Input budget = total context minus reserved output and safety tokens.
        This signals that compaction is needed before further input can be added.
        """
        alloc = self.allocate()
        input_budget = sum(v for k, v in alloc.items() if k not in self._RESERVED)
        return self.total_used() > input_budget

    def total_used(self) -> int:
        """Return total tokens used across all categories."""
        return sum(self._used.values())

    def summary(self) -> dict[str, dict[str, int]]:
        """Return a summary of budget vs usage per category."""
        alloc = self.allocate()
        return {
            category: {
                "budget": alloc.get(category, 0),
                "used": self.used(category),
                "remaining": self.remaining(category),
            }
            for category in self.budget_pcts
        }
