# Testing Guide

This document describes the test strategy, how to run tests, test categories,
key fixtures, and how to add new tests.

---

## Overview

The backend has **114 tests** across **14 test files** in `backend/tests/`.
Tests are written with `pytest` and cover unit, integration, search validation,
system validation, and observability concerns.

---

## Running Tests

### Full Suite

```bash
cd backend
uv run python -m pytest tests/ -v
```

### With Coverage

```bash
cd backend
uv run python -m pytest tests/ -v --cov=. --cov-report=term-missing
```

### Specific File

```bash
cd backend
uv run python -m pytest tests/test_agent.py -v
```

### Specific Test

```bash
cd backend
uv run python -m pytest tests/test_agent.py::TestAgentTools::test_search_knowledge_base -v
```

### Filtered by Keyword

```bash
# Run all tests with "cache" in the name
cd backend
uv run python -m pytest tests/ -v -k "cache"

# Run all tests with "search" in the name
cd backend
uv run python -m pytest tests/ -v -k "search"
```

### Parallel Execution

```bash
# Install pytest-xdist if available
cd backend
uv run python -m pytest tests/ -v -n auto
```

---

## Test Categories

### Unit Tests (53 tests)

Isolated tests for individual functions and classes. External dependencies
(Ollama, Meilisearch, ChromaDB) are mocked.

| File                        | Tests | Covers                                    |
|-----------------------------|-------|-------------------------------------------|
| `test_agent.py`             | ~12   | Agent tools, model routing, system prompt |
| `test_cache.py`             | ~8    | L1 LRU, L2 SQLite, cache keys            |
| `test_context_engine.py`    | ~8    | Budget calc, compaction, assembly         |
| `test_memory.py`            | ~6    | FTS5 store/recall, capacity limits        |
| `test_security.py`          | ~5    | JWT creation/validation, auth             |
| `test_proposals.py`         | ~4    | Proposal CRUD, lifecycle                  |
| `test_reranker.py`          | ~4    | Jaccard scoring, final ranking            |
| `test_chunker.py`           | ~3    | Markdown/code chunking                    |
| `test_registry.py`          | ~3    | Namespace resolution, repo paths          |

### Integration Tests (19 tests)

Test interactions between components. May use real SQLite databases but mock
external services.

| File                              | Tests | Covers                                  |
|-----------------------------------|-------|-----------------------------------------|
| `test_main.py`                    | ~8    | HTTP endpoints, auth flow, streaming    |
| `test_search_orchestrator.py`     | ~6    | Full search pipeline with mocked backends |
| `test_git_workflow.py`            | ~5    | Git operations with temp repos          |

### Search Validation (19 tests)

Validate the search pipeline's correctness: query classification, result
quality, deduplication, and reranking behavior.

| File                              | Tests | Covers                                  |
|-----------------------------------|-------|-----------------------------------------|
| `test_search_validation.py`       | ~10   | Query classification accuracy           |
| `test_search_integration.py`      | ~9    | End-to-end search with mocked backends  |

### System Validation (12 tests)

End-to-end tests that validate the complete request flow from HTTP request
to agent response.

| File                              | Tests | Covers                                  |
|-----------------------------------|-------|-----------------------------------------|
| `test_system.py`                  | ~7    | Full chat flow, tool execution          |
| `test_streaming.py`              | ~5    | NDJSON streaming, event types           |

### Observability Tests (11 tests)

Verify that tracing, metrics, and the trace store work correctly.

| File                              | Tests | Covers                                  |
|-----------------------------------|-------|-----------------------------------------|
| `test_observability.py`           | ~6    | OTEL init, span creation, metric recording |
| `test_trace_store.py`             | ~5    | RequestTraceStore CRUD, querying        |

---

## Test Directory Structure

```
backend/tests/
├── conftest.py                    # Shared fixtures
├── test_agent.py                  # Agent tools, model routing
├── test_main.py                   # HTTP endpoints
├── test_cache.py                  # Search cache (L1 + L2)
├── test_context_engine.py         # Context assembly, budget, compaction
├── test_memory.py                 # SQLite FTS5 memory
├── test_security.py               # JWT, auth
├── test_proposals.py              # Proposal lifecycle
├── test_search_orchestrator.py    # Search pipeline
├── test_search_validation.py      # Query classification, result quality
├── test_search_integration.py     # End-to-end search
├── test_reranker.py               # Jaccard reranking
├── test_observability.py          # OTEL tracing and metrics
├── test_trace_store.py            # RequestTraceStore
├── test_system.py                 # System-level integration
├── test_streaming.py              # Streaming chat responses
├── test_git_workflow.py           # Git operations
├── test_chunker.py                # Document chunking
└── test_registry.py               # Namespace registry
```

---

## Key Fixtures (conftest.py)

### `test_client`

FastAPI `TestClient` with the app configured for testing. Overrides external
service URLs to prevent real connections.

```python
@pytest.fixture
def test_client():
    """FastAPI test client with mocked external services."""
    app.dependency_overrides[get_settings] = lambda: TestSettings()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
```

### `auth_headers`

Pre-authenticated JWT headers for endpoints that require auth.

```python
@pytest.fixture
def auth_headers(test_client):
    """JWT auth headers for authenticated requests."""
    response = test_client.post("/login", json={
        "username": "admin",
        "password": "password"
    })
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
```

### `mock_search_orchestrator`

Mocked search orchestrator that returns predictable results.

```python
@pytest.fixture
def mock_search_orchestrator():
    """Search orchestrator returning canned results."""
    with patch("agent.search_orchestrator") as mock:
        mock.search.return_value = [
            {
                "title": "Test Document",
                "path": "test/doc.md",
                "section": "Overview",
                "snippet": "This is a test document.",
                "score": 0.95,
            }
        ]
        yield mock
```

### `memory_db`

Temporary SQLite database for memory tests.

```python
@pytest.fixture
def memory_db(tmp_path):
    """Temporary SQLite memory database."""
    db_path = tmp_path / "test_memory.db"
    memory = SQLiteMemory(db_path=str(db_path))
    yield memory
```

### `cache_instance`

Clean cache instance for cache tests.

```python
@pytest.fixture
def cache_instance(tmp_path):
    """Fresh L1+L2 cache for testing."""
    db_path = tmp_path / "test_cache.db"
    return SearchCache(
        l1_max_entries=10,
        l2_db_path=str(db_path),
        l2_ttl_seconds=60,
    )
```

---

## Test Patterns

### Mocking External Services

All tests mock external services (Ollama, Meilisearch, ChromaDB) to avoid
needing a running infrastructure stack:

```python
@patch("search.meilisearch_client.MeilisearchClient")
@patch("search.semantic.ChromaDBClient")
@patch("search.embedding_cache.get_embedding")
async def test_search_pipeline(mock_embed, mock_chroma, mock_meili):
    mock_embed.return_value = [0.1] * 768  # Fake embedding
    mock_meili.return_value.search.return_value = [...]
    mock_chroma.return_value.query.return_value = [...]

    results = await orchestrator.search("test query", scope="claude-code")
    assert len(results) <= 8
```

### Testing Streaming Responses

```python
def test_chat_stream(test_client, auth_headers):
    response = test_client.post(
        "/chat/stream",
        json={"query": "How does the agent work?"},
        headers=auth_headers,
    )
    assert response.status_code == 200

    events = []
    for line in response.iter_lines():
        if line:
            events.append(json.loads(line))

    # Verify event types
    types = [e["type"] for e in events]
    assert "done" in types
    assert any(t == "token" for t in types)
```

### Testing Cache Behavior

```python
async def test_cache_l1_lru(cache_instance):
    # Fill cache to capacity
    for i in range(10):
        cache_instance.set(f"key{i}", {"result": i})

    # All entries should be present
    assert cache_instance.get("key0") is not None

    # Add one more to trigger eviction
    cache_instance.set("key10", {"result": 10})

    # Oldest entry (key0) should be evicted
    assert cache_instance.get("key0") is None
    assert cache_instance.get("key10") is not None
```

### Testing Token Budget

```python
def test_budget_allocation():
    budget = calculate_budget(max_tokens=128000)
    assert budget["system"] == pytest.approx(3840, rel=0.01)
    assert budget["memory"] == pytest.approx(6400, rel=0.01)
    assert budget["history"] == pytest.approx(44800, rel=0.01)
    assert budget["search"] == pytest.approx(32000, rel=0.01)
    assert budget["output"] == pytest.approx(38400, rel=0.01)
    assert budget["safety"] == pytest.approx(2560, rel=0.01)
    assert sum(budget.values()) == pytest.approx(128000, rel=0.01)
```

---

## Adding New Tests

### 1. Choose the Right File

- Testing a specific module? Add to the existing test file for that module.
- Testing a new module? Create a new `test_<module>.py` file.
- Testing cross-module integration? Add to `test_system.py` or create a new
  integration test file.

### 2. Follow Naming Conventions

```python
# File: test_<module>.py
# Class: Test<Component>
# Method: test_<behavior>

class TestSearchCache:
    def test_l1_hit_returns_cached_result(self):
        ...

    def test_l2_expired_entry_returns_none(self):
        ...

    def test_cache_key_includes_scope(self):
        ...
```

### 3. Use Fixtures

Always use fixtures from `conftest.py` for:
- Test clients (`test_client`)
- Auth headers (`auth_headers`)
- Database instances (`memory_db`, `cache_instance`)
- Mocked services (`mock_search_orchestrator`)

### 4. Mock External Dependencies

Never depend on running external services in tests:
- Use `@patch` to mock Ollama, Meilisearch, ChromaDB
- Use `tmp_path` for SQLite databases
- Use `TestClient` for HTTP endpoint tests

### 5. Assert Specific Behavior

```python
# Good: specific assertion
assert result["score"] >= 0.0
assert result["score"] <= 1.0
assert result["path"].endswith(".md")

# Bad: vague assertion
assert result is not None
assert len(results) > 0
```

### 6. Run Tests Before Committing

```bash
# Run full suite
cd backend && uv run python -m pytest tests/ -v

# Ensure no failures
# All 114 tests should pass
```

---

## Continuous Integration

Tests can be run in CI with:

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: |
          cd backend
          uv sync
          uv run python -m pytest tests/ -v --tb=short
```

---

## Related Documentation

- [Backend Overview](backend-overview.md) — Project structure
- [Components](components.md) — What each module does
- [Known Issues](known-issues.md) — Python 3.14 compatibility
