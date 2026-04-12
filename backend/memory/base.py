"""Abstract Memory Manager protocol (inspired by AutoGen)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class MemoryItem:
    """A single memory entry."""
    id: str
    content: str
    metadata: dict = field(default_factory=dict)
    score: float = 0.0


class MemoryManager(ABC):
    """Abstract protocol for memory storage and retrieval."""

    @abstractmethod
    def query(self, query: str, top_k: int = 5) -> list[dict]:
        """Retrieve relevant memories for a query."""
        ...

    @abstractmethod
    def add(self, content: str, metadata: dict | None = None) -> None:
        """Store a new memory."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Remove all memories."""
        ...

    @abstractmethod
    def count(self) -> int:
        """Return total number of stored memories."""
        ...
