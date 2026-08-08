from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://careerlens:change_me@postgres:5432/careerlens"
    redis_url: str = "redis://redis:6379/0"

    jobs_service_url: str = "http://jobs-service:8000"
    auth_service_url: str = "http://auth-service:8000"

    # one of: gemini | fireworks | anthropic | openai
    # gemini is the default because it's the only one with a genuinely permanent free
    # tier — the others give trial credits and then bill per token.
    llm_provider: str = "gemini"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    fireworks_api_key: str = ""
    fireworks_model: str = "accounts/fireworks/models/deepseek-v4-flash"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
