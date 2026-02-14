from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Application
    app_name: str = "Merchant Onboarding API"
    debug: bool = False

    # Supabase
    supabase_url: str = "http://127.0.0.1:54331"
    supabase_key: str = "your-supabase-key"
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54332/postgres"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Security
    api_keys: str = ""  # Comma-separated valid API keys

    @property
    def valid_api_keys(self) -> set[str]:
        if not self.api_keys:
            return set()
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    # Rate limiting
    rate_limit_default: str = "10/minute"
    rate_limit_onboard: str = "2/minute"

    # Crawling
    max_concurrent_browsers: int = 10
    memory_threshold_percent: float = 70.0
    crawl_batch_size: int = 50
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: int = 60


settings = Settings()
