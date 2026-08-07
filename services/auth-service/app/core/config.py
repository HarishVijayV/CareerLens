"""
Central config, loaded once from environment variables (see infra/.env.example).
Every other module imports `settings` from here instead of reading os.environ directly —
one source of truth, and it's trivially mockable in tests.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://careerlens:change_me@postgres:5432/careerlens"
    redis_url: str = "redis://redis:6379/0"

    jwt_secret_key: str = "change_me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    cookie_secure: bool = False
    cookie_domain: str = "localhost"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
