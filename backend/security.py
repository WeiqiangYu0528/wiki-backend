from datetime import datetime, timedelta
from jose import JWTError, jwt
import pyotp
from passlib.context import CryptContext
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_admin_username: str = "admin"
    app_admin_password: str = "password"
    app_mfa_secret: str = ""
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440

    # Publish repo and GitHub config (approval-gated wiki writes)
    publish_repo_dir: str = ""
    github_token: str = ""
    publish_repo: str = ""

    # Ollama / Embeddings
    ollama_base_url: str = "http://localhost:11434"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_chat_model: str = "qwen3.5"
    ollama_chat_url: str = ""  # If empty, uses ollama_base_url
    embedding_dimensions: int = 768
    embedding_provider: str = "ollama"

    # CORS
    cors_origins: str = "http://localhost:8000,http://localhost:8001"

    # Environment mode
    environment: str = "development"

    # Search
    search_max_results: int = 8
    search_max_chars: int = 2000
    search_result_max_chars: int = 200

    # Cache
    cache_l1_max_entries: int = 200
    cache_l2_ttl_seconds: int = 3600
    cache_db_path: str = "data/cache.db"

    # Context Engine
    context_budget_system_pct: float = 0.03
    context_budget_memory_pct: float = 0.05
    context_budget_history_pct: float = 0.35
    context_budget_search_pct: float = 0.25
    context_budget_output_pct: float = 0.30
    context_budget_safety_pct: float = 0.02
    max_history_turns: int = 6
    compactor_protected_turns: int = 4

    # Memory
    memory_db_path: str = "data/memory.db"
    memory_max_items: int = 1000

    # Meilisearch
    meilisearch_url: str = "http://localhost:7700"
    meilisearch_api_key: str = ""

    # Code reading
    read_code_default_lines: int = 50
    read_code_max_symbol_lines: int = 100

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# JWT Config
SECRET_KEY = settings.jwt_secret_key
ALGORITHM = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.jwt_access_token_expire_minutes

def verify_password(plain_password, stored_password):
    # In a real app with multiple users, you'd use bcrypt hashing. 
    # Since this is a local tool with a single admin controlled via .env, a direct string compare works for the MVP.
    return plain_password == stored_password

def verify_totp(secret: str, code: str) -> bool:
    if not secret:
        # If no secret is configured, assume MFA is disabled (for dev fallback)
        return True
    totp = pyotp.TOTP(secret)
    return totp.verify(code)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
