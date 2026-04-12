# backend/tests/test_meilisearch.py
"""Tests for Meilisearch client (uses mock for unit tests)."""
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from search.meilisearch_client import MeilisearchClient


def _mock_client() -> MeilisearchClient:
    """Create a MeilisearchClient with mocked HTTP client."""
    with patch("search.meilisearch_client.meilisearch") as mock_meili:
        mock_index = MagicMock()
        mock_meili.Client.return_value.index.return_value = mock_index
        client = MeilisearchClient(url="http://localhost:7700", api_key="")
        client._client = mock_meili.Client.return_value
        return client


def test_client_init():
    with patch("search.meilisearch_client.meilisearch"):
        client = MeilisearchClient(url="http://localhost:7700", api_key="test")
        assert client._url == "http://localhost:7700"


def test_index_documents():
    client = _mock_client()
    docs = [
        {"id": "doc1", "content": "hello world", "file_path": "test.py"},
        {"id": "doc2", "content": "foo bar", "file_path": "test2.py"},
    ]
    client.index_documents("wiki_docs", docs)
    client._client.index.assert_called()


def test_search_returns_results():
    client = _mock_client()
    mock_index = client._client.index.return_value
    mock_index.search.return_value = {
        "hits": [
            {"id": "doc1", "content": "result text", "file_path": "a.py", "_rankingScore": 0.9},
        ],
        "estimatedTotalHits": 1,
    }
    results = client.search("wiki_docs", "test query", limit=5)
    assert len(results) == 1
    assert results[0]["file_path"] == "a.py"
    assert results[0]["normalized_score"] == 0.9


def test_search_empty_results():
    client = _mock_client()
    mock_index = client._client.index.return_value
    mock_index.search.return_value = {"hits": [], "estimatedTotalHits": 0}
    results = client.search("wiki_docs", "nothing", limit=5)
    assert results == []


def test_search_handles_connection_error():
    client = _mock_client()
    mock_index = client._client.index.return_value
    mock_index.search.side_effect = Exception("Connection refused")
    results = client.search("wiki_docs", "test", limit=5)
    assert results == []
