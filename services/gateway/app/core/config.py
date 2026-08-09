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
    jobs_service_url: str = "http://jobs-service:8000"
    notification_service_url: str = "http://notification-service:8000"

    # 60/minute was set thinking about a single API caller and is far too low for a
    # browser. One Analytics page load fires SIX requests at once (one per chart), the
    # dashboard fires several more, and the notification bell polls every 60 seconds — so
    # normal clicking through four or five pages exhausted the budget and the user got
    # "Rate limit exceeded, slow down" while doing nothing unusual.
    #
    # A rate limit that triggers on ordinary use is not protecting anything, it is just a
    # bug with a plausible error message. 300 still stops a scraper or a runaway loop
    # (that is 5 requests/second sustained) while leaving normal browsing far below the
    # ceiling.
    #
    # Both values are read from the environment, so a deployment can tighten them without
    # a code change.
    rate_limit_requests: int = 300
    rate_limit_window_seconds: int = 60

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
