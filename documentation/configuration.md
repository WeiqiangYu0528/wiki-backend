# Configuration Reference

All configuration is done via environment variables, loaded through Pydantic
`BaseSettings` in `backend/security.py`. Every setting has a sensible default
for local development.

---

## Complete Environment Variable Reference

### Authentication

| Variable               | Default      | Description                                          |
|------------------------|--------------|------------------------------------------------------|
| `APP_ADMIN_USERNAME`   | `"admin"`    | Admin username for login                             |
| `APP_ADMIN_PASSWORD`   | `"password"` | Admin password for login (plaintext comparison)      |
| `APP_MFA_SECRET`       | `""`         | TOTP MFA secret. If empty, MFA is disabled           |

### JWT

| Variable                        | Default                   | Description                            |
|---------------------------------|---------------------------|----------------------------------------|
| `JWT_SECRET_KEY`                | `"change-me-in-production"` | Secret key for signing JWT tokens    |
| `JWT_ALGORITHM`                 | `"HS256"`                 | JWT signing algorithm                  |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `1440`                  | Token expiry in minutes (24 hours)     |

### LLM / Ollama

| Variable              | Default                      | Description                                    |
|-----------------------|------------------------------|------------------------------------------------|
| `OLLAMA_BASE_URL`     | `"http://localhost:11434"`   | Ollama server URL for embeddings               |
| `OLLAMA_EMBED_MODEL`  | `"nomic-embed-text"`         | Embedding model name                           |
| `OLLAMA_CHAT_MODEL`   | `"qwen3.5"`                  | Default chat model name                        |
| `OLLAMA_CHAT_URL`     | `""`                         | Separate URL for chat model. If empty, falls back to `OLLAMA_BASE_URL` |

### Embeddings

| Variable               | Default          | Description                               |
|------------------------|------------------|-------------------------------------------|
| `EMBEDDING_DIMENSIONS` | `768`            | Embedding vector dimensions               |
| `EMBEDDING_PROVIDER`   | `"ollama"`       | Embedding provider (`ollama`)             |

### CORS

| Variable        | Default                                        | Description                   |
|-----------------|------------------------------------------------|-------------------------------|
| `CORS_ORIGINS`  | `"http://localhost:8000,http://localhost:8001"` | Comma-separated allowed origins |

### Environment

| Variable       | Default          | Description                                    |
|----------------|------------------|------------------------------------------------|
| `ENVIRONMENT`  | `"development"`  | Environment name (development, production)     |

### Search

| Variable                  | Default | Description                                     |
|---------------------------|---------|-------------------------------------------------|
| `SEARCH_MAX_RESULTS`      | `8`     | Maximum search results returned per query       |
| `SEARCH_MAX_CHARS`        | `2000`  | Maximum total characters in formatted results   |
| `SEARCH_RESULT_MAX_CHARS` | `200`   | Maximum characters per individual result snippet|

### Cache

| Variable               | Default          | Description                          |
|------------------------|------------------|--------------------------------------|
| `CACHE_L1_MAX_ENTRIES` | `200`            | Maximum entries in L1 in-memory LRU  |
| `CACHE_L2_TTL_SECONDS` | `3600`           | TTL for L2 SQLite cache (seconds)    |
| `CACHE_DB_PATH`        | `"data/cache.db"`| Path to SQLite cache database        |

### Context Budget

| Variable                       | Default | Description                              |
|--------------------------------|---------|------------------------------------------|
| `CONTEXT_BUDGET_SYSTEM_PCT`    | `0.03`  | System prompt budget (3% of 128K)        |
| `CONTEXT_BUDGET_MEMORY_PCT`    | `0.05`  | Memory injection budget (5%)             |
| `CONTEXT_BUDGET_HISTORY_PCT`   | `0.35`  | Conversation history budget (35%)        |
| `CONTEXT_BUDGET_SEARCH_PCT`    | `0.25`  | Search results budget (25%)              |
| `CONTEXT_BUDGET_OUTPUT_PCT`    | `0.30`  | Reserved for LLM output (30%)           |
| `CONTEXT_BUDGET_SAFETY_PCT`    | `0.02`  | Safety margin for tokenization (2%)      |

### History & Compaction

| Variable                     | Default | Description                              |
|------------------------------|---------|------------------------------------------|
| `MAX_HISTORY_TURNS`          | `6`     | Maximum conversation history turns       |
| `COMPACTOR_PROTECTED_TURNS`  | `4`     | Recent turns protected from compaction   |

### Memory

| Variable           | Default            | Description                            |
|--------------------|--------------------|----------------------------------------|
| `MEMORY_DB_PATH`   | `"data/memory.db"` | Path to SQLite memory database         |
| `MEMORY_MAX_ITEMS` | `1000`             | Maximum stored memory items            |

### Meilisearch

| Variable             | Default                    | Description                    |
|----------------------|----------------------------|--------------------------------|
| `MEILISEARCH_URL`    | `"http://localhost:7700"`  | Meilisearch server URL         |
| `MEILISEARCH_API_KEY`| `""`                       | Meilisearch API key (optional) |

### File Reading

| Variable                    | Default | Description                              |
|-----------------------------|---------|------------------------------------------|
| `READ_CODE_DEFAULT_LINES`   | `50`    | Default lines when reading workspace files|
| `READ_CODE_MAX_SYMBOL_LINES`| `100`   | Max lines for symbol context display     |

### Publishing / Git

| Variable           | Default | Description                                      |
|--------------------|---------|--------------------------------------------------|
| `PUBLISH_REPO_DIR` | `""`    | Local path to git repository for proposals       |
| `GITHUB_TOKEN`     | `""`    | GitHub personal access token for push/PR         |
| `PUBLISH_REPO`     | `""`    | Remote repository ref (e.g., `owner/repo`)       |

### Observability

| Variable             | Default                    | Description                    |
|----------------------|----------------------------|--------------------------------|
| `OTEL_OTEL_ENDPOINT` | `"http://localhost:4317"`  | OTLP gRPC collector endpoint   |
| `OTEL_ENABLED`       | `true`                     | Enable/disable OTEL telemetry  |

---

## Production vs Development

### Development Defaults

The default configuration is optimized for local development:

- Single admin user with simple credentials
- JWT secret is a placeholder
- CORS allows localhost origins
- OTEL exports to localhost endpoints
- SQLite databases in `data/` directory
- No MFA required
- No GitHub integration

### Production Overrides

For production deployments, override these critical settings:

```bash
# REQUIRED: Change these for security
JWT_SECRET_KEY=<random-64-char-string>
APP_ADMIN_PASSWORD=<strong-password>
APP_MFA_SECRET=<base32-totp-secret>

# REQUIRED: Restrict CORS
CORS_ORIGINS=https://your-wiki.example.com

# RECOMMENDED: Set environment
ENVIRONMENT=production

# RECOMMENDED: External LLM provider (faster than local Ollama)
OLLAMA_CHAT_URL=https://api.deepseek.com/v1
OLLAMA_CHAT_MODEL=deepseek-chat

# RECOMMENDED: Meilisearch API key
MEILISEARCH_API_KEY=<your-meilisearch-master-key>

# OPTIONAL: GitHub integration for proposals
GITHUB_TOKEN=ghp_xxxxxxxxxxxx
PUBLISH_REPO=your-org/your-wiki-repo
PUBLISH_REPO_DIR=/app/wiki

# OPTIONAL: Adjust for traffic
CACHE_L1_MAX_ENTRIES=500
CACHE_L2_TTL_SECONDS=7200
MEMORY_MAX_ITEMS=5000
```

---

## .env.example Template

Create a `.env` file in the project root. Docker Compose and the backend will
read from it automatically.

```bash
# ==============================================================================
# Wiki Agent Backend Configuration
# ==============================================================================
# Copy this file to .env and customize for your environment.
# All values shown are the defaults.

# --- Authentication ---
APP_ADMIN_USERNAME=admin
APP_ADMIN_PASSWORD=password        # CHANGE in production!
APP_MFA_SECRET=                    # Set a base32 secret to enable TOTP MFA

# --- JWT ---
JWT_SECRET_KEY=change-me-in-production  # CHANGE in production! Use: openssl rand -hex 32
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440

# --- LLM / Ollama ---
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_CHAT_MODEL=qwen3.5
OLLAMA_CHAT_URL=                   # Leave empty to use OLLAMA_BASE_URL for chat

# --- Embeddings ---
EMBEDDING_DIMENSIONS=768
EMBEDDING_PROVIDER=ollama

# --- CORS ---
CORS_ORIGINS=http://localhost:8000,http://localhost:8001

# --- Environment ---
ENVIRONMENT=development

# --- Search ---
SEARCH_MAX_RESULTS=8
SEARCH_MAX_CHARS=2000
SEARCH_RESULT_MAX_CHARS=200

# --- Cache ---
CACHE_L1_MAX_ENTRIES=200
CACHE_L2_TTL_SECONDS=3600
CACHE_DB_PATH=data/cache.db

# --- Context Budget (must sum to ~1.0) ---
CONTEXT_BUDGET_SYSTEM_PCT=0.03
CONTEXT_BUDGET_MEMORY_PCT=0.05
CONTEXT_BUDGET_HISTORY_PCT=0.35
CONTEXT_BUDGET_SEARCH_PCT=0.25
CONTEXT_BUDGET_OUTPUT_PCT=0.30
CONTEXT_BUDGET_SAFETY_PCT=0.02

# --- History ---
MAX_HISTORY_TURNS=6
COMPACTOR_PROTECTED_TURNS=4

# --- Memory ---
MEMORY_DB_PATH=data/memory.db
MEMORY_MAX_ITEMS=1000

# --- Meilisearch ---
MEILISEARCH_URL=http://localhost:7700
MEILISEARCH_API_KEY=

# --- File Reading ---
READ_CODE_DEFAULT_LINES=50
READ_CODE_MAX_SYMBOL_LINES=100

# --- Publishing ---
PUBLISH_REPO_DIR=
GITHUB_TOKEN=
PUBLISH_REPO=

# --- Observability ---
OTEL_OTEL_ENDPOINT=http://localhost:4317
OTEL_ENABLED=true
```

---

## Generating a JWT Secret

```bash
# Option 1: OpenSSL
openssl rand -hex 32

# Option 2: Python
python -c "import secrets; print(secrets.token_hex(32))"

# Option 3: /dev/urandom
head -c 32 /dev/urandom | xxd -p -c 64
```

---

## Generating an MFA Secret

```bash
# Generate a base32 TOTP secret
python -c "import pyotp; print(pyotp.random_base32())"

# Or manually:
python -c "import base64, os; print(base64.b32encode(os.urandom(20)).decode())"
```

After setting `APP_MFA_SECRET`, use a TOTP authenticator app (Google
Authenticator, Authy, etc.) to scan the secret and generate codes.

---

## Context Budget Tuning

The six budget percentages must sum to approximately 1.0. Adjust based on
your usage patterns:

| Scenario                          | System | Memory | History | Search | Output | Safety |
|-----------------------------------|--------|--------|---------|--------|--------|--------|
| **Default (balanced)**            | 3%     | 5%     | 35%     | 25%    | 30%    | 2%     |
| **Search-heavy (RAG-focused)**    | 3%     | 3%     | 20%     | 40%    | 32%    | 2%     |
| **Conversation-heavy (chatbot)**  | 3%     | 5%     | 45%     | 15%    | 30%    | 2%     |
| **Long-form output**              | 2%     | 3%     | 25%     | 20%    | 48%    | 2%     |

---

## Docker Compose Environment

In Docker Compose, environment variables can be set in three ways:

1. **`.env` file** (recommended): Automatically loaded by Docker Compose.
2. **`docker-compose.yml` `environment:` block**: Hardcoded in the compose file.
3. **Shell environment**: `VARIABLE=value docker compose up`

Priority order: Shell > docker-compose.yml > .env file.

### Docker-Specific Overrides

When running in Docker, some URLs need to reference Docker service names:

```bash
# In Docker Compose, services communicate by name
OLLAMA_BASE_URL=http://ollama:11434          # Not localhost
MEILISEARCH_URL=http://meilisearch:7700      # Not localhost
OTEL_OTEL_ENDPOINT=http://otel-collector:4317 # Not localhost

# For chat models running on the host machine
OLLAMA_CHAT_URL=http://host.docker.internal:11434/v1
```

---

## Related Documentation

- [Deployment](deployment.md) — Using these settings in production
- [Caching](caching.md) — Cache tuning details
- [Observability](observability.md) — OTEL settings
- [Known Issues](known-issues.md) — Security concerns with defaults
