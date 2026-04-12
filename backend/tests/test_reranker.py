"""Tests for Jaccard reranker with weighted scoring."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from search.reranker import JaccardReranker, tokenize


def _make_result(text: str, score: float, file_path: str = "test.py") -> dict:
    return {"text": text, "normalized_score": score, "file_path": file_path}


def test_tokenize():
    tokens = tokenize("hello, world! foo_bar")
    assert "hello" in tokens
    assert "world" in tokens
    assert "foo_bar" in tokens


def test_rerank_order():
    reranker = JaccardReranker()
    results = [
        _make_result("unrelated content about cats", 0.5),
        _make_result("how to search for documents in code", 0.4),
    ]
    ranked = reranker.rerank("search documents", results, top_k=2)
    assert "search" in ranked[0]["text"]


def test_rerank_top_k():
    reranker = JaccardReranker()
    results = [_make_result(f"result {i}", 0.5) for i in range(10)]
    ranked = reranker.rerank("test", results, top_k=3)
    assert len(ranked) == 3


def test_rerank_empty():
    reranker = JaccardReranker()
    assert reranker.rerank("query", [], top_k=5) == []


def test_dedup_by_file_section():
    reranker = JaccardReranker()
    results = [
        {"text": "same content", "normalized_score": 0.8, "file_path": "a.py", "section": "intro"},
        {"text": "same content dupe", "normalized_score": 0.7, "file_path": "a.py", "section": "intro"},
        {"text": "different file", "normalized_score": 0.6, "file_path": "b.py", "section": "intro"},
    ]
    ranked = reranker.rerank("test", results, top_k=10)
    file_sections = [(r["file_path"], r.get("section", "")) for r in ranked]
    assert len(file_sections) == len(set(file_sections))


def test_custom_weights():
    reranker = JaccardReranker(
        search_weight=0.3,
        jaccard_weight=0.6,
        recency_weight=0.1,
    )
    results = [
        _make_result("exact match query terms", 0.2),
        _make_result("no overlap at all xyz", 0.9),
    ]
    ranked = reranker.rerank("exact match query terms", results, top_k=2)
    assert "exact match" in ranked[0]["text"]
