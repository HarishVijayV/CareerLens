from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    jwt_secret_key: str = "change_me"
    jwt_algorithm: str = "HS256"

    redis_url: str = "redis://redis:6379/0"

    # frontend origin — the ONLY origin allowed to call this API from a browser
    frontend_origin: str = "http://localhost:3000"

    # downstream service base URLs (Docker Compose service names resolve on the shared network)
    auth_service_url: str = "http://auth-service:8000"
    agent_service_url: str = "http://agent-service:8000"
    notification_service_url: str = "http://notification-service:8000"

    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
