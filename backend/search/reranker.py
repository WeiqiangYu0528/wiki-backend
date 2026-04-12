"""Jaccard token-overlap reranker with weighted scoring.

Adapted from Hermes's hybrid ranking pipeline:
  final_score = search_weight × normalized_score
              + jaccard_weight × jaccard_similarity
              + recency_weight × recency_factor
"""

import logging
import re

logger = logging.getLogger(__name__)

_TOKEN_PATTERN = re.compile(r"[a-z_][a-z0-9_]*", re.IGNORECASE)


def tokenize(text: str) -> set[str]:
    """Extract lowercase word tokens from text."""
    return set(_TOKEN_PATTERN.findall(text.lower()))


class JaccardReranker:
    """Reranks search results using Jaccard similarity + search score + recency.

    Args:
        search_weight: Weight for the original search score (default 0.6).
        jaccard_weight: Weight for Jaccard token overlap (default 0.3).
        recency_weight: Weight for recency factor (default 0.1).
    """

    def __init__(
        self,
        search_weight: float = 0.6,
        jaccard_weight: float = 0.3,
        recency_weight: float = 0.1,
    ) -> None:
        self.search_weight = search_weight
        self.jaccard_weight = jaccard_weight
        self.recency_weight = recency_weight

    def rerank(
        self,
        query: str,
        results: list[dict],
        top_k: int = 8,
    ) -> list[dict]:
        """Rerank results using weighted Jaccard scoring, then dedup and trim."""
        if not results:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return results[:top_k]

        for result in results:
            result_tokens = tokenize(result.get("text", ""))
            union = query_tokens | result_tokens
            intersection = query_tokens & result_tokens
            jaccard = len(intersection) / len(union) if union else 0.0

            recency = 1.0

            search_score = result.get("normalized_score", result.get("score", 0.0))
            result["final_score"] = (
                self.search_weight * search_score
                + self.jaccard_weight * jaccard
                + self.recency_weight * recency
            )

        results.sort(key=lambda r: r.get("final_score", 0), reverse=True)

        seen: set[str] = set()
        deduped: list[dict] = []
        for r in results:
            section = r.get("section")
            if section is not None:
                key = f"{r.get('file_path', '')}:{section}"
                if key in seen:
                    continue
                seen.add(key)
            deduped.append(r)

        return deduped[:top_k]
