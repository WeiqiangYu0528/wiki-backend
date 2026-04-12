# backend/tests/test_context_engine.py
"""Tests for context engine (assemble + compact + budget)."""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_engine.engine import ContextEngine
from context_engine.budget import TokenBudget
from context_engine.compactor import ContextCompactor
from memory.sqlite_memory import SQLiteMemory


def _make_engine(tmp_dir: str) -> ContextEngine:
    memory = SQLiteMemory(db_path=os.path.join(tmp_dir, "mem.db"))
    compactor = ContextCompactor(protected_turns=2, trigger_pct=0.1)
    budget = TokenBudget(context_limit=10000)
    return ContextEngine(memory=memory, compactor=compactor, budget=budget)


def test_assemble_basic():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(tmp)
        result = engine.assemble(
            system_prompt="You are helpful.",
            messages=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
            query="What is search?",
        )
        assert "messages" in result
        assert "budget_summary" in result
        assert len(result["messages"]) >= 3


def test_assemble_with_memory():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(tmp)
        engine.memory.add("User prefers concise answers", {"source": "user"})
        engine.memory.add("Search uses Meilisearch for hybrid results", {"source": "system"})
        result = engine.assemble(
            system_prompt="You are helpful.",
            messages=[],
            query="How does search work?",
        )
        all_content = " ".join(m.get("content", "") for m in result["messages"])
        assert "Meilisearch" in all_content or "search" in all_content.lower()


def test_assemble_applies_compaction():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(tmp)
        messages = []
        for i in range(10):
            messages.append({"role": "user", "content": f"Question {i}"})
            messages.append({
                "role": "assistant", "content": "",
                "tool_calls": [{"name": "smart_search", "args": f"q{i}"}],
            })
            messages.append({"role": "tool", "name": "smart_search", "content": "x" * 2000})
            messages.append({"role": "assistant", "content": f"Answer {i}"})

        result = engine.assemble(
            system_prompt="You are helpful.",
            messages=messages,
            query="Next question?",
        )
        tool_msgs = [m for m in result["messages"] if m.get("role") == "tool"]
        pruned = [m for m in tool_msgs if "pruned" in m.get("content", "").lower()]
        assert len(pruned) > 0


def test_assemble_budget_tracking():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(tmp)
        result = engine.assemble(
            system_prompt="Short prompt.",
            messages=[{"role": "user", "content": "Hi"}],
            query="Test",
        )
        summary = result["budget_summary"]
        assert "system" in summary
        assert "history" in summary
        assert summary["system"]["used"] > 0


def test_assemble_empty_history():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(tmp)
        result = engine.assemble(
            system_prompt="System.",
            messages=[],
            query="First message",
        )
        assert len(result["messages"]) >= 2


def test_search_budget_allocation():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(tmp)
        search_budget = engine.get_search_budget()
        assert search_budget > 0
        assert search_budget == int(10000 * 0.25)


def test_assemble_returns_token_count():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(tmp)
        result = engine.assemble(
            system_prompt="System prompt here.",
            messages=[{"role": "user", "content": "Hello"}],
            query="What is X?",
        )
        assert result["total_tokens"] > 0
