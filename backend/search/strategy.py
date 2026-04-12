"""Search strategy engine with loop prevention and escalation."""


class SearchStrategyEngine:
    """Tracks search attempts per request and manages strategy escalation.
    
    Instantiate one per agent request. Tracks which queries have been tried,
    how many results each returned, and when to escalate or give up.
    """

    STRATEGIES = [
        "symbol_exact",
        "lexical_code",
        "semantic_code",
        "lexical_broad",
        "semantic_broad",
    ]
    MAX_ATTEMPTS_PER_STRATEGY = 3

    def __init__(self) -> None:
        self.attempts: list[dict] = []
        self.current_strategy_idx: int = 0
        self._consecutive_failures: int = 0

    @property
    def current_strategy(self) -> str:
        idx = min(self.current_strategy_idx, len(self.STRATEGIES) - 1)
        return self.STRATEGIES[idx]

    @property
    def exhausted(self) -> bool:
        return self.current_strategy_idx >= len(self.STRATEGIES)

    @property
    def total_attempts(self) -> int:
        return len(self.attempts)

    def record_attempt(self, query: str, result_count: int) -> str | None:
        """Record a search attempt. Returns a hint string or None.
        
        Returns:
            None if no action needed.
            "ESCALATED to <strategy>" if strategy was switched.
            "EXHAUSTED" if all strategies are exhausted.
        """
        self.attempts.append({
            "query": query,
            "result_count": result_count,
            "strategy": self.current_strategy if not self.exhausted else "none",
        })

        if result_count == 0:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.MAX_ATTEMPTS_PER_STRATEGY:
                self._consecutive_failures = 0
                self.current_strategy_idx += 1
                if self.exhausted:
                    return "EXHAUSTED"
                return f"ESCALATED to {self.current_strategy}"
        else:
            self._consecutive_failures = 0

        return None

    def summary(self) -> str:
        """Generate a human-readable summary of all search attempts."""
        if not self.attempts:
            return "No search attempts recorded."
        
        lines = []
        for i, a in enumerate(self.attempts, 1):
            status = f"{a['result_count']} results" if a['result_count'] > 0 else "no results"
            lines.append(f"  {i}. [{a['strategy']}] \"{a['query']}\" → {status}")
        
        total = len(self.attempts)
        found = sum(1 for a in self.attempts if a["result_count"] > 0)
        lines.insert(0, f"Search attempts: {total} total, {found} successful")
        
        if self.exhausted:
            lines.append("  ⚠️ All strategies exhausted.")
        
        return "\n".join(lines)
