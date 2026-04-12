# Known Issues & Limitations

This document catalogs known issues, limitations, and areas for improvement
in the wiki agent backend. Each item includes its impact, affected components,
and suggested mitigations or future fixes.

---

## Security Issues

### 1. JWT Stored in localStorage

**Severity**: Medium
**Component**: `docs/javascripts/chatbox.js` (frontend)

The Axiom chat widget stores JWT tokens in `localStorage`, which is vulnerable
to XSS (Cross-Site Scripting) attacks. If an attacker can inject JavaScript
into a wiki page, they can steal the JWT token.

**Impact**: Token theft could allow unauthorized access to the chat API and
proposal endpoints.

**Mitigation**:
- Ensure MkDocs content is sanitized (no raw HTML injection)
- Set short JWT expiry (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`)
- Consider migrating to HTTP-only secure cookies for token storage

**Future Fix**: Move JWT storage to HTTP-only cookies with `SameSite=Strict`
and `Secure` flags. This requires backend changes to set/read cookies instead
of `Authorization` headers.

---

### 2. Plaintext Password Comparison

**Severity**: High
**Component**: `backend/security.py`

Admin credentials are compared using simple string equality against the
`APP_ADMIN_PASSWORD` environment variable. Passwords are not hashed or salted.

```python
# Current (insecure):
if password == settings.APP_ADMIN_PASSWORD:
    return True

# Should be:
if bcrypt.checkpw(password.encode(), hashed_password):
    return True
```

**Impact**: If the environment or memory is compromised, the plaintext password
is directly exposed. No protection against timing attacks.

**Mitigation**:
- Use a strong, unique password
- Enable MFA (`APP_MFA_SECRET`) as a second factor
- Restrict access to the server environment

**Future Fix**: Implement bcrypt password hashing. Store a hashed password in
the environment variable or a separate credentials file.

---

### 3. No Rate Limiting

**Severity**: Medium
**Component**: `backend/main.py`

There is no rate limiting on any endpoint. The `/chat` and `/chat/stream`
endpoints are particularly expensive (they trigger LLM calls), making the
system vulnerable to:

- Denial of Service (DoS) via rapid chat requests
- LLM cost abuse (if using paid API providers)
- Search backend overload

**Mitigation**:
- Place a reverse proxy (nginx, Caddy) in front of the backend with rate
  limiting rules
- Use cloud provider rate limiting (e.g., AWS API Gateway, Cloudflare)

**Future Fix**: Add `slowapi` or similar rate-limiting middleware to FastAPI:
```python
from slowapi import Limiter
limiter = Limiter(key_func=get_remote_address)

@app.post("/chat")
@limiter.limit("10/minute")
async def chat(request: Request, ...):
    ...
```

---

### 4. Grafana Default Credentials

**Severity**: Low (development) / High (production)
**Component**: `docker-compose.yml` (Grafana service)

Grafana is deployed with default credentials (`admin`/`admin`). In development
this is acceptable, but in production it exposes the monitoring dashboards
to unauthorized access.

**Impact**: An attacker could view system metrics, create alerts, or modify
dashboards.

**Mitigation**:
- Change the Grafana admin password immediately after first login
- Add environment variables to the Grafana service:
  ```yaml
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=your-strong-password
  ```
- Restrict Grafana port (19999) to internal networks only

---

## Infrastructure Issues

### 5. Docker Ollama Memory Limit (6 GB)

**Severity**: Medium
**Component**: `docker-compose.yml` (Ollama service)

The Ollama container has a 6 GB memory limit. The `nomic-embed-text` embedding
model uses approximately 3.6 GB, leaving only ~2.4 GB for a chat model. This
means most 7B+ parameter chat models cannot run alongside the embedding model
in the Docker container.

**Impact**: Users cannot use large local chat models without changing the
configuration.

**Affected Models**:
| Model           | Size   | Fits in 6 GB? |
|-----------------|--------|---------------|
| nomic-embed-text| ~3.6 GB| ✅ (required)  |
| qwen2.5:3b     | ~2.0 GB| ✅ (tight)     |
| phi3:mini       | ~2.3 GB| ✅ (very tight)|
| llama3:8b       | ~5.0 GB| ❌             |
| qwen3.5:7b     | ~4.5 GB| ❌             |
| mistral:7b      | ~4.1 GB| ❌             |

**Mitigation**:
- Run Ollama on the host machine for chat models and use
  `OLLAMA_CHAT_URL=http://host.docker.internal:11434/v1`
- Use an external API provider (DeepSeek, OpenAI) for chat
- Increase the Docker memory limit if the host has sufficient RAM

**Future Fix**: Split Ollama into two containers: one for embeddings (fixed
3.6 GB) and one for chat (configurable memory).

---

### 6. ChromaDB Cold Start

**Severity**: Low
**Component**: `backend/search/semantic.py`

When ChromaDB is first started with no indexed data, semantic search returns
empty results. There is no automatic indexing on startup.

**Impact**: The first few queries after a fresh deployment may lack semantic
search results, falling back to Meilisearch and ripgrep only.

**Mitigation**:
- Run the indexer after deployment: ensures ChromaDB collections are populated
- The search orchestrator gracefully handles empty ChromaDB results

**Future Fix**: Add an automatic indexing step to the backend startup lifecycle
(or as an init container in Docker Compose).

---

### 7. Python 3.14 Compatibility Warnings

**Severity**: Low
**Component**: Various dependencies

The backend uses Python 3.14, which is the latest version and may trigger
deprecation warnings or compatibility issues in some dependencies:

- **Pydantic V2**: Some V1 compatibility shims emit deprecation warnings
- **SQLite**: The `sqlite3` module in 3.14 may have API changes
- **asyncio**: Some async patterns may emit warnings

**Impact**: Log noise from deprecation warnings. No functional breakage
observed in the 114-test suite.

**Mitigation**:
- Suppress specific warnings in `pytest.ini` or test configuration
- Pin dependency versions in `pyproject.toml`
- Monitor upstream library releases for 3.14 compatibility fixes

---

## Functional Limitations

### 8. Pydantic V2 Deprecation Warnings

**Severity**: Low
**Component**: `backend/security.py`

The `Settings` class may use Pydantic V1-style configuration (e.g., inner
`Config` class) that triggers deprecation warnings in Pydantic V2.

```python
# V1 style (deprecated):
class Settings(BaseSettings):
    class Config:
        env_file = ".env"

# V2 style (preferred):
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
```

**Impact**: Warning messages in logs. No functional impact.

**Future Fix**: Migrate all Pydantic models to V2-style `model_config`.

---

### 9. FTS5 Keyword-Only Memory

**Severity**: Medium
**Component**: `backend/memory/sqlite_memory.py`

The memory system uses SQLite FTS5 for recall, which is keyword-based only.
It cannot perform semantic search over memories. This means:

- Memory recall only works when the query shares keywords with stored memories
- Semantically similar but lexically different queries will miss relevant
  memories
- Example: Storing "The agent uses a ReAct loop" won't be recalled by
  "How does the reasoning process work?"

**Impact**: Memory recall has lower recall (in the IR sense) than a semantic
memory system would.

**Mitigation**:
- Store memories with rich keyword metadata
- The FTS5 BM25 ranking still provides reasonable results for most queries
- Search results (from the semantic search pipeline) compensate for memory gaps

**Future Fix**: Add an embedding-based memory recall path alongside FTS5.
Use ChromaDB or a dedicated vector store for memory embeddings.

---

### 10. No WebSocket Support

**Severity**: Low
**Component**: `backend/main.py`, `docs/javascripts/chatbox.js`

The streaming chat uses NDJSON over HTTP (`POST /chat/stream`) rather than
WebSocket. This means:

- Each message requires a new HTTP connection
- No server-initiated messages (notifications, updates)
- Slightly higher overhead per message compared to WebSocket

**Impact**: Higher latency for the first token in a response. No ability to
push updates to the client.

**Future Fix**: Add a WebSocket endpoint (`WS /chat/ws`) for lower-latency
bidirectional communication.

---

### 11. Single-User Authentication

**Severity**: Low
**Component**: `backend/security.py`

The system only supports a single admin user configured via environment
variables. There is no user registration, multi-user support, or role-based
access control.

**Impact**: All authenticated users share the same identity and permissions.

**Future Fix**: Implement a user database with registration, roles (admin,
editor, viewer), and per-user memory isolation.

---

### 12. No Automatic Cache Invalidation

**Severity**: Medium
**Component**: `backend/search/cache.py`

When wiki content changes (files edited, pages added/removed), the search
cache is not automatically invalidated. Cached results may be stale until
the L2 TTL expires (default 1 hour) or the backend is restarted (L1).

**Impact**: Users may receive outdated search results for up to 1 hour after
content changes.

**Mitigation**:
- Reduce `CACHE_L2_TTL_SECONDS` for wikis with frequent content changes
- Manually restart the backend after major content updates
- Clear the cache database manually: `rm data/cache.db`

**Future Fix**: Implement file-watcher based cache invalidation or webhook
triggers on git push.

---

## Summary Table

| #  | Issue                           | Severity | Component          | Status      |
|----|---------------------------------|----------|--------------------|-------------|
| 1  | JWT in localStorage             | Medium   | Frontend           | Documented  |
| 2  | Plaintext password comparison   | High     | security.py        | Documented  |
| 3  | No rate limiting                | Medium   | main.py            | Documented  |
| 4  | Grafana default credentials     | Low/High | docker-compose.yml | Documented  |
| 5  | Docker Ollama 6 GB limit        | Medium   | docker-compose.yml | Documented  |
| 6  | ChromaDB cold start             | Low      | search/semantic.py | Documented  |
| 7  | Python 3.14 compatibility       | Low      | Various            | Documented  |
| 8  | Pydantic V2 deprecation         | Low      | security.py        | Documented  |
| 9  | FTS5 keyword-only memory        | Medium   | memory/            | Documented  |
| 10 | No WebSocket support            | Low      | main.py, frontend  | Documented  |
| 11 | Single-user authentication      | Low      | security.py        | Documented  |
| 12 | No automatic cache invalidation | Medium   | search/cache.py    | Documented  |

---

## Reporting New Issues

When discovering a new issue:

1. Add it to this document with:
   - Clear title
   - Severity (Low / Medium / High / Critical)
   - Affected component(s)
   - Impact description
   - Mitigation steps (if any)
   - Future fix suggestion
2. Update the summary table

---

## Related Documentation

- [Configuration](configuration.md) — Security-related settings
- [Deployment](deployment.md) — Production security checklist
- [Caching](caching.md) — Cache invalidation details
- [Testing](testing.md) — Verifying fixes
