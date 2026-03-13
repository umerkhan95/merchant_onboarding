from __future__ import annotations

from pydantic_settings import BaseSettings

# Maximum allowed HTTP response body size (10 MB).
# Responses larger than this are rejected before parsing to prevent
# memory exhaustion from XML bombs or oversized HTML payloads.
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB in bytes


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Application
    app_name: str = "Merchant Onboarding API"
    debug: bool = False

    # Supabase
    supabase_url: str = "http://127.0.0.1:54331"
    supabase_key: str = "your-supabase-key"
    database_url: str = "postgresql://postgres:postgres@localhost:5432/merchant_onboarding"

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

    # GDPR
    data_retention_days: int = 365
    store_raw_data: bool = False
    respect_robots_txt: bool = True
    dlq_ttl_seconds: int = 2592000  # 30 days

    # OAuth / Platform Integration
    oauth_encryption_key: str = ""  # Fernet key for encrypting OAuth tokens at rest
    jwt_secret_key: str = "change-me-in-production"  # JWT signing key for merchant sessions
    jwt_expiry_hours: int = 24
    bigcommerce_client_id: str = ""
    bigcommerce_client_secret: str = ""
    bigcommerce_callback_url: str = "http://localhost:8000/api/v1/auth/bigcommerce/callback"
    bigcommerce_account_uuid: str = ""
    shopify_client_id: str = ""
    shopify_client_secret: str = ""
    shopify_callback_url: str = "http://localhost:8000/api/v1/auth/shopify/callback"
    woocommerce_app_name: str = "Merchant Onboarding"
    woocommerce_callback_url: str = "http://localhost:8000/api/v1/auth/woocommerce/callback"
    woocommerce_return_url: str = "http://localhost:8000/api/v1/auth/woocommerce/return"
    shopware_app_name: str = "Merchant Onboarding"
    magento_callback_url: str = ""  # e.g. https://your-domain.com/api/v1/auth/magento/callback
    magento_identity_url: str = ""  # e.g. https://your-domain.com/api/v1/auth/magento/identity

    # LLM Extraction
    llm_provider: str = "openai/gpt-4o-mini"
    llm_api_key: str = ""
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4000
    llm_budget_max: float = 50.0  # Max LLM cost per job (USD)
    schema_cache_ttl: int = 604800  # 7 days in seconds

    def create_llm_config(self):
        """Create a crawl4ai LLMConfig from settings.

        Returns:
            LLMConfig instance or None if no API key configured.
        """
        if not self.llm_api_key:
            return None

        from crawl4ai import LLMConfig

        return LLMConfig(
            provider=self.llm_provider,
            api_token=self.llm_api_key,
        )


settings = Settings()
