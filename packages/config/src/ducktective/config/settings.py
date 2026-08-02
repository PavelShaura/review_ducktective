from enum import (
    StrEnum,
)
from pathlib import (
    Path,
)

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class DeploymentProfile(StrEnum):
    DEV = "dev"
    AIRGAPPED = "airgapped"
    FULL = "full"


class Settings(BaseSettings):
    """Единые настройки для всех приложений.

    Общий класс нужен, чтобы api и воркер собирали одинаковые зависимости:
    расхождение конфигурации между ними приводило бы к разным моделям и
    разным политикам egress в одном и том же прогоне.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    app_log_level: str = "INFO"

    database_url: str = ""
    database_pool_size: int = 10
    database_pool_max_overflow: int = 5

    redis_url: str = ""

    deployment_profile: DeploymentProfile = DeploymentProfile.DEV

    local_llm_provider: str = "ollama"
    local_llm_base_url: str = "http://localhost:11434"
    local_llm_api_key: str = ""
    local_embedding_model: str = "qwen3-embedding:0.6b"
    local_embedding_base_url: str = ""
    embedding_dimensions: int = 768
    context_token_budget: int = 2000
    local_reranker_model: str = "bge-reranker-v2-m3"
    local_review_model: str = "qwen2.5-coder:14b"
    cloud_review_model: str = "anthropic/claude-sonnet-5"
    llm_timeout_seconds: float = 180.0
    llm_cache_ttl_seconds: int = 7 * 24 * 3600
    llm_max_output_tokens: int = 4096
    """Сколько токенов ответа запрашивается у модели.

    Место под ответ резервируется в окне модели, поэтому значение вычитается
    из того, что остаётся под сам дифф: при окне 8192 запрошенные 4096 съедают
    половину. У reasoning-моделей на размышления уходит большая часть выхода,
    и там снижать это число нельзя — нужно поднимать окно.
    """

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    otel_exporter_otlp_endpoint: str = ""

    repositories_root: Path = Path("./repos")

    review_queue_name: str = "ducktective:reviews"
    review_job_timeout_seconds: int = 1800

    mcp_tenant_id: str = ""
    mcp_http_host: str = "127.0.0.1"
    mcp_http_port: int = 8090

    @property
    def cloud_providers_allowed(self) -> bool:
        """В air-gapped профиле облачные провайдеры запрещены на уровне конфигурации."""
        return self.deployment_profile is not DeploymentProfile.AIRGAPPED

    def require_database_url(self) -> str:
        """Адреса хранилищ не обязательны: автономный режим CLI работает без них."""
        if not self.database_url:
            raise ValueError("Не задан DATABASE_URL — он нужен всем режимам, кроме --no-store")
        return self.database_url

    def require_redis_url(self) -> str:
        if not self.redis_url:
            raise ValueError("Не задан REDIS_URL — он нужен всем режимам, кроме --no-store")
        return self.redis_url
