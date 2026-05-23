from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: str = "development"
    app_debug: bool = False
    secret_key: str = ""

    # GitHub
    github_webhook_secret: str = ""
    github_token: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://agent:agent@localhost:5432/agent"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # LLM — provider selection: "anthropic" | "openai" | "gemini"
    llm_provider: str = "anthropic"

    # API keys (only the one matching llm_provider is required)
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Model overrides (sensible defaults per provider)
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_model: str = "gpt-4o"
    gemini_model: str = "gemini-2.0-flash"

    # Shared LLM tunables
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.0  # deterministic for planning / analysis

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


settings = Settings()