"""Tests for token budget allocation and tracking."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_engine.budget import TokenBudget, estimate_tokens


def test_estimate_tokens_simple():
    assert estimate_tokens("hello world") == 3  # ceil(11 / 4)


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_budget_allocation_default():
    budget = TokenBudget(context_limit=128000)
    alloc = budget.allocate()
    assert alloc["system"] == int(128000 * 0.03)
    assert alloc["memory"] == int(128000 * 0.05)
    assert alloc["history"] == int(128000 * 0.35)
    assert alloc["search"] == int(128000 * 0.25)
    assert alloc["output"] == int(128000 * 0.30)
    assert alloc["safety"] == int(128000 * 0.02)
    total = sum(alloc.values())
    assert total <= 128000


def test_budget_remaining_after_usage():
    budget = TokenBudget(context_limit=10000)
    budget.use("system", 300)
    budget.use("history", 2000)
    remaining = budget.remaining("search")
    alloc = budget.allocate()
    assert remaining == alloc["search"]  # search hasn't been used


def test_budget_overflow_detection():
    budget = TokenBudget(context_limit=1000)
    budget.use("history", 400)
    assert not budget.is_over_budget()
    budget.use("history", 300)  # total 700, budget for history = 350 → over
    assert budget.is_over_budget()
