"""Token counting and estimation utilities."""

import math
from typing import Any


def estimate_tokens(text: str) -> int:
    """Estimate token count from text using chars/4 heuristic.

    This is a rough approximation. For exact counts, use tiktoken,
    but this avoids adding a heavy dependency for observability.
    """
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def extract_usage_metadata(message: Any) -> dict[str, int]:
    """Extract token usage from a LangChain AIMessage or dict.

    LangChain AIMessage objects have a `usage_metadata` attribute when
    the provider returns token counts. Falls back to zeros if unavailable.
    """
    empty = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    if isinstance(message, dict):
        usage = message.get("usage_metadata", {})
    elif hasattr(message, "usage_metadata") and message.usage_metadata:
        usage = message.usage_metadata
    else:
        return empty

    if not isinstance(usage, dict):
        return empty

    return {
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "total_tokens": usage.get("total_tokens", 0) or 0,
    }
