# backend/tests/test_compactor.py
"""Tests for context compactor (tool output pruning)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from context_engine.compactor import ContextCompactor


def _make_messages(n_turns: int, tool_output_size: int = 200) -> list[dict]:
    """Create a realistic message history with tool calls and outputs."""
    messages = []
    for i in range(n_turns):
        messages.append({"role": "user", "content": f"Question {i}"})
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"name": "smart_search", "args": f"query {i}"}],
        })
        messages.append({
            "role": "tool",
            "name": "smart_search",
            "content": "x" * tool_output_size,
        })
        messages.append({"role": "assistant", "content": f"Answer {i}"})
    return messages


def test_no_pruning_under_threshold():
    compactor = ContextCompactor(protected_turns=4, trigger_pct=0.5)
    messages = _make_messages(3, tool_output_size=100)
    result = compactor.compact(messages, token_budget=100000)
    tool_msgs = [m for m in result if m.get("role") == "tool"]
    assert all("pruned" not in m["content"].lower() for m in tool_msgs)


def test_prune_old_tool_outputs():
    compactor = ContextCompactor(protected_turns=2, trigger_pct=0.1)
    messages = _make_messages(6, tool_output_size=500)
    result = compactor.compact(messages, token_budget=100)
    pruned = [m for m in result if m.get("role") == "tool" and "pruned" in m["content"].lower()]
    assert len(pruned) > 0


def test_protected_turns_preserved():
    compactor = ContextCompactor(protected_turns=2, trigger_pct=0.1)
    messages = _make_messages(4, tool_output_size=500)
    result = compactor.compact(messages, token_budget=100)
    # Last 2 turns' tool outputs should NOT be pruned
    # Each turn = 4 messages (user, assistant+tool_call, tool, assistant)
    # Last 2 turns = last 8 messages
    last_tools = [
        m for m in result[-8:]
        if m.get("role") == "tool"
    ]
    for m in last_tools:
        assert "pruned" not in m["content"].lower()


def test_tool_call_metadata_preserved():
    compactor = ContextCompactor(protected_turns=1, trigger_pct=0.1)
    messages = _make_messages(4, tool_output_size=500)
    result = compactor.compact(messages, token_budget=100)
    tool_call_msgs = [m for m in result if m.get("tool_calls")]
    assert len(tool_call_msgs) == 4


def test_compactor_reports_savings():
    compactor = ContextCompactor(protected_turns=1, trigger_pct=0.1)
    messages = _make_messages(5, tool_output_size=500)
    result = compactor.compact(messages, token_budget=100)
    assert compactor.last_pruned_count > 0
    assert compactor.last_chars_saved > 0
