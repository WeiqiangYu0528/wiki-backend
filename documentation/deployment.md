# Deployment Guide

This guide covers how to deploy the wiki agent backend using Docker Compose,
manage the Ollama model, configure for production, and monitor the system.

---

## Docker Compose Setup

### Prerequisites

- Docker Engine 24+ and Docker Compose V2
- At least 8 GB RAM (Ollama needs ~3.6 GB for nomic-embed-text)
- At least 10 GB disk space (Docker images + data volumes)
- Ports available: 8001, 7700, 11434, 16686, 9090, 19999, 4317, 4318, 8889

### Services Overview

| Service          | Image                     | Port(s)          | Memory Limit | Purpose                    |
|------------------|---------------------------|------------------|-------------|----------------------------|
| `backend`        | Custom (Python 3.14-slim) | 8001             | —           | FastAPI + LangGraph agent  |
| `ollama`         | ollama/ollama             | 11434            | 6 GB        | Embedding model inference  |
| `ollama-pull`    | ollama/ollama             | —                | —           | Init: pulls nomic-embed-text |
| `meilisearch`    | getmeili/meilisearch      | 7700             | 256 MB      | BM25 + vector search       |
| `jaeger`         | jaegertracing/all-in-one  | 16686            | —           | Trace visualization        |
| `prometheus`     | prom/prometheus           | 9090             | —           | Metrics storage            |
| `grafana`        | grafana/grafana           | 19999            | —           | Metrics dashboards         |
| `otel-collector` | otel/opentelemetry-collector | 4317, 4318, 8889 | —        | Telemetry routing          |

### Starting the Stack

```bash
# Start all services in detached mode
docker compose up -d

# Watch startup logs (especially ollama-pull for first run)
docker compose logs -f

# Check that all services are healthy
docker compose ps
```

### First-Run Initialization

On the first run, the `ollama-pull` init container pulls the `nomic-embed-text`
model. This can take 1–5 minutes depending on network speed.

```bash
# Monitor the model pull
docker compose logs -f ollama-pull

# When complete, you should see:
# ollama-pull-1  | pulling manifest
# ollama-pull-1  | pulling ...
# ollama-pull-1  | success
# ollama-pull-1 exited with code 0
```

### Verifying the Stack

```bash
# 1. Backend health check
curl http://localhost:8001/health
# → {"status": "ok", "environment": "development"}

# 2. Meilisearch health
curl http://localhost:7700/health
# → {"status": "available"}

# 3. Ollama model check
curl http://localhost:11434/api/tags
# → Should list "nomic-embed-text"

# 4. Jaeger UI
open http://localhost:16686

# 5. Prometheus UI
open http://localhost:9090

# 6. Grafana UI
open http://localhost:19999
# Default credentials: admin / admin
```

---

## Ollama Model Management

### Embedding Model (Required)

The `nomic-embed-text` model is required for all embedding operations. It is
automatically pulled by the `ollama-pull` init container.

```bash
# Manual pull (if needed)
docker compose exec ollama ollama pull nomic-embed-text

# Verify model is loaded
docker compose exec ollama ollama list
```

### Chat Models (Optional, on Ollama)

By default, the backend uses `qwen3.5` as the chat model. Ollama in Docker is
configured with a 6 GB memory limit, which constrains which chat models can
run alongside the embedding model.

```bash
# The embedding model uses ~3.6 GB, leaving ~2.4 GB for a chat model
# Small models that fit:
docker compose exec ollama ollama pull qwen2.5:3b
docker compose exec ollama ollama pull phi3:mini
docker compose exec ollama ollama pull gemma2:2b

# These will NOT fit in 6 GB alongside the embedding model:
# - llama3:8b (~5 GB)
# - qwen3.5:7b (~4.5 GB)
# - mistral:7b (~4.1 GB)
```

### Using Host Ollama for Chat

For larger chat models, run Ollama on the host machine (with GPU access) and
point the backend to it via `host.docker.internal`:

```bash
# On the host machine
ollama serve
ollama pull qwen3.5

# In .env
OLLAMA_CHAT_URL=http://host.docker.internal:11434/v1
OLLAMA_CHAT_MODEL=qwen3.5
```

### Using External API Providers for Chat

For the best quality and lowest latency, use an external LLM API:

```bash
# DeepSeek
OLLAMA_CHAT_URL=https://api.deepseek.com/v1
OLLAMA_CHAT_MODEL=deepseek-chat
# Set OPENAI_API_KEY=<your-deepseek-key>

# OpenAI
OLLAMA_CHAT_URL=https://api.openai.com/v1
OLLAMA_CHAT_MODEL=gpt-4o
# Set OPENAI_API_KEY=<your-openai-key>
```

---

## Docker Compose File Structure

### Backend Service

```yaml
backend:
  build:
    context: ./backend
    dockerfile: Dockerfile
  ports:
    - "8001:8001"
  volumes:
    - ./site:/app/site:ro          # Built MkDocs site (read-only)
    - ./docs:/app/docs:ro          # Source markdown files (read-only)
    - backend-data:/app/data       # SQLite databases (persistent)
  environment:
    - OLLAMA_BASE_URL=http://ollama:11434
    - MEILISEARCH_URL=http://meilisearch:7700
    - OTEL_OTEL_ENDPOINT=http://otel-collector:4317
  depends_on:
    ollama-pull:
      condition: service_completed_successfully
    meilisearch:
      condition: service_started
```

### Backend Dockerfile

```dockerfile
FROM python:3.14-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY . .
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
```

### Volume Mounts

| Mount                  | Container Path | Mode | Purpose                         |
|------------------------|----------------|------|---------------------------------|
| `./site`               | `/app/site`    | ro   | Built MkDocs site for serving   |
| `./docs`               | `/app/docs`    | ro   | Source markdown for agent tools  |
| `backend-data` (named) | `/app/data`    | rw   | SQLite databases                |

---

## Production Checklist

### Security (Critical)

- [ ] **Change JWT secret**: `JWT_SECRET_KEY=<openssl rand -hex 32>`
- [ ] **Change admin password**: `APP_ADMIN_PASSWORD=<strong-password>`
- [ ] **Enable MFA**: `APP_MFA_SECRET=<base32-secret>`
- [ ] **Restrict CORS**: `CORS_ORIGINS=https://your-domain.com`
- [ ] **Set environment**: `ENVIRONMENT=production`
- [ ] **Secure Meilisearch**: `MEILISEARCH_API_KEY=<master-key>`
- [ ] **Change Grafana password**: Update from default `admin/admin`
- [ ] **Review exposed ports**: Only expose 8001 externally; keep 7700, 16686,
      9090, 19999 on internal network or behind a reverse proxy

### Performance

- [ ] **Use external LLM API**: Set `OLLAMA_CHAT_URL` to a fast API provider
- [ ] **Tune cache sizes**: Increase `CACHE_L1_MAX_ENTRIES` for high traffic
- [ ] **Tune cache TTL**: Adjust `CACHE_L2_TTL_SECONDS` based on content
      update frequency
- [ ] **Increase Ollama memory**: If running chat models in Docker, increase
      the memory limit from 6 GB
- [ ] **Pre-index content**: Run the indexer before accepting traffic

### Reliability

- [ ] **Set up health checks**: Monitor `/health` endpoint
- [ ] **Configure log retention**: Docker logs can fill disk; set `--log-opt max-size`
- [ ] **Back up data volumes**: The `backend-data` volume contains caches and
      memory databases
- [ ] **Set restart policies**: Ensure `restart: unless-stopped` on all services
- [ ] **Monitor disk space**: Meilisearch and SQLite databases grow over time

### Networking

- [ ] **Use a reverse proxy**: Place nginx, Caddy, or Traefik in front of the
      backend for TLS termination
- [ ] **Enable HTTPS**: The backend serves HTTP only; TLS must be handled by
      the reverse proxy
- [ ] **Configure DNS**: Point your wiki domain to the server

---

## Resource Requirements

### Minimum (Development)

| Resource | Requirement                          |
|----------|--------------------------------------|
| CPU      | 2 cores                              |
| RAM      | 8 GB                                 |
| Disk     | 10 GB                                |
| GPU      | Not required (CPU inference is slow) |

### Recommended (Production)

| Resource | Requirement                          |
|----------|--------------------------------------|
| CPU      | 4+ cores                             |
| RAM      | 16 GB (allows larger Ollama models)  |
| Disk     | 50 GB (content + indexes + data)     |
| GPU      | NVIDIA GPU with 8+ GB VRAM (optional)|

### Per-Service Memory

| Service          | Minimum | Recommended | Notes                           |
|------------------|---------|-------------|---------------------------------|
| backend          | 256 MB  | 512 MB      | Python + LangGraph overhead     |
| ollama           | 4 GB    | 8 GB        | Model loading + inference       |
| meilisearch      | 256 MB  | 512 MB      | Depends on index size           |
| jaeger           | 128 MB  | 256 MB      | Trace storage                   |
| prometheus       | 128 MB  | 256 MB      | Metric storage                  |
| grafana          | 128 MB  | 256 MB      | Dashboard rendering             |
| otel-collector   | 64 MB   | 128 MB      | Telemetry routing               |

---

## Health Checks

### Backend

```bash
# Simple health check
curl -f http://localhost:8001/health

# Full connectivity test
curl -X POST http://localhost:8001/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "password"}'
```

### Docker Compose Health Checks

Add to `docker-compose.yml` for automatic restarts:

```yaml
backend:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 30s

meilisearch:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:7700/health"]
    interval: 30s
    timeout: 10s
    retries: 3
```

---

## Upgrading

### Updating the Backend

```bash
# Pull latest code
git pull

# Rebuild and restart backend only
docker compose build backend
docker compose up -d backend
```

### Updating Ollama Models

```bash
# Pull latest version of the embedding model
docker compose exec ollama ollama pull nomic-embed-text

# After model update, clear the embedding cache (vectors may differ)
docker compose exec backend rm -f /app/data/cache.db
docker compose restart backend
```

### Full Stack Update

```bash
# Pull latest images
docker compose pull

# Rebuild custom images
docker compose build

# Restart everything
docker compose up -d
```

---

## Stopping and Cleanup

```bash
# Stop all services
docker compose down

# Stop and remove volumes (CAUTION: deletes all data)
docker compose down -v

# Remove unused images
docker image prune -f
```

---

## Troubleshooting

### Backend Won't Start

1. Check logs: `docker compose logs backend`
2. Common causes:
   - Ollama not ready (ollama-pull still running)
   - Meilisearch not responding
   - Port 8001 already in use
   - Python dependency issues

### Ollama Out of Memory

1. Check: `docker compose logs ollama`
2. The default 6 GB limit supports the embedding model (~3.6 GB) with some
   headroom. Loading a large chat model will cause OOM.
3. Solutions:
   - Use `host.docker.internal` for chat models (run Ollama on host)
   - Use an external API provider
   - Increase the memory limit in `docker-compose.yml`

### Meilisearch Not Indexing

1. Check: `curl http://localhost:7700/indexes`
2. If no indexes exist, run the indexer manually
3. Check Meilisearch logs: `docker compose logs meilisearch`

### No Traces in Jaeger

1. Check OTEL Collector: `docker compose logs otel-collector`
2. Check backend `OTEL_ENABLED=true`
3. Check connectivity: backend must reach `otel-collector:4317`

---

## Related Documentation

- [Configuration](configuration.md) — All environment variables
- [Observability](observability.md) — Monitoring the deployment
- [Known Issues](known-issues.md) — Known limitations
- [Testing](testing.md) — Running tests before deployment
