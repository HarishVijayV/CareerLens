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

    # Encrypts third-party tokens at rest. Falls back to jwt_secret_key in dev — see
    # app/core/crypto.py for why that's a convenience, not a recommendation.
    token_encryption_key: str = ""

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # Where to send the browser after the OAuth dance finishes.
    frontend_url: str = "http://localhost:3000"

    @property
    def google_oauth_configured(self) -> bool:
        """Lets routes return a clear 'not configured' instead of a confusing failure
        when the operator hasn't set up Google credentials yet."""
        return bool(self.google_client_id and self.google_client_secret)

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
