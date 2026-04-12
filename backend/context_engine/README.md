# Context Engine Package

Token-budgeted prompt assembly with memory injection and history compaction.

## Components

- **engine.py** — `ContextEngine.assemble()` builds the full prompt with budget tracking. Injects relevant memories, compacts old tool outputs, enforces token limits.
- **compactor.py** — `ContextCompactor.compact()` prunes old tool outputs using backward-scan. Protects the last N turns (default 4).
- **budget.py** — `TokenBudget` manages per-category token allocation: system (3%), memory (5%), history (35%), search (25%), output (30%), safety (2%).

## Usage

```python
from context_engine import ContextEngine, TokenBudget, ContextCompactor
from memory import SQLiteMemory

engine = ContextEngine(
    memory=SQLiteMemory(db_path="data/memory.db"),
    compactor=ContextCompactor(protected_turns=4),
    budget=TokenBudget(context_limit=128000),
)

result = engine.assemble(
    system_prompt="You are helpful.",
    messages=chat_history,
    query="How does search work?",
)
# result["messages"], result["total_tokens"], result["budget_summary"]
```
