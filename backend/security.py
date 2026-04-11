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
