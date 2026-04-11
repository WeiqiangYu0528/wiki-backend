"""Observability configuration loaded from environment variables."""

import os
from pydantic_settings import BaseSettings


class ObservabilityConfig(BaseSettings):
    service_name: str = "mkdocs-agent"
    otel_endpoint: str = "http://localhost:4317"
    otel_insecure: bool = True
    sqlite_path: str = os.path.join(os.path.dirname(__file__), "..", "data", "traces.db")
    enabled: bool = True

    class Config:
        env_prefix = "OTEL_"
        env_file = ".env"
        extra = "ignore"
