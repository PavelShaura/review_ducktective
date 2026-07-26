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
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    app_log_level: str = "INFO"

    database_url: str
    database_pool_size: int = 10
    database_pool_max_overflow: int = 5

    redis_url: str

    deployment_profile: DeploymentProfile = DeploymentProfile.DEV

    ollama_base_url: str = "http://localhost:11434"
    local_embedding_model: str = "qwen3-embedding:0.6b"
    local_reranker_model: str = "bge-reranker-v2-m3"
    local_review_model: str = "qwen2.5-coder:14b"

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    otel_exporter_otlp_endpoint: str = ""

    repositories_root: Path = Path("./repos")

    @property
    def cloud_providers_allowed(self) -> bool:
        """В air-gapped профиле облачные провайдеры запрещены на уровне конфигурации."""
        return self.deployment_profile is not DeploymentProfile.AIRGAPPED
