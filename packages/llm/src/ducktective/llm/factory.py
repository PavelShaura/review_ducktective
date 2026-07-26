from redis.asyncio import (
    Redis,
)

from ducktective.llm.cache import (
    RedisResponseCache,
)
from ducktective.llm.client import (
    LiteLlmClient,
)
from ducktective.llm.code_reviewer import (
    LlmCodeReviewer,
)
from ducktective.llm.router import (
    ModelChoice,
    ModelRouter,
)


def build_model_router(
    *,
    local_provider: str,
    local_model: str,
    local_base_url: str,
    local_api_key: str,
    cloud_model: str,
    cloud_api_key: str,
    cloud_enabled: bool,
) -> ModelRouter:
    """Собирает роутер.

    Локальный инференс может обслуживаться разными серверами: Ollama на этой же
    машине или OpenAI-совместимый сервер вроде LM Studio на соседнем хосте.
    Для LiteLLM это разные префиксы модели, поэтому провайдер задаётся явно.
    """
    local_choice = ModelChoice(
        model=f"{local_provider}/{local_model}",
        provider=local_provider,
        api_base=local_base_url,
        api_key=local_api_key or None,
    )
    cloud_choice = (
        ModelChoice(model=cloud_model, provider="anthropic", api_key=cloud_api_key)
        if cloud_api_key
        else None
    )
    return ModelRouter(
        local_choice=local_choice,
        cloud_choice=cloud_choice,
        cloud_enabled=cloud_enabled and cloud_choice is not None,
    )


def build_code_reviewer(
    *,
    redis_client: Redis,
    local_provider: str,
    local_model: str,
    local_base_url: str,
    local_api_key: str,
    cloud_model: str,
    cloud_api_key: str,
    cloud_enabled: bool,
    cache_ttl_seconds: int,
    timeout_seconds: float,
) -> LlmCodeReviewer:
    """Собирает ревьюера целиком.

    Фабрика принимает примитивы, а не объект настроек: пакет моделей не должен
    зависеть от конфигурации приложений, но собирать зависимости в каждом
    приложении заново — источник расхождений.
    """
    router = build_model_router(
        local_provider=local_provider,
        local_model=local_model,
        local_base_url=local_base_url,
        local_api_key=local_api_key,
        cloud_model=cloud_model,
        cloud_api_key=cloud_api_key,
        cloud_enabled=cloud_enabled,
    )
    client = LiteLlmClient(
        router,
        cache=RedisResponseCache(redis_client, ttl_seconds=cache_ttl_seconds),
        timeout_seconds=timeout_seconds,
    )
    return LlmCodeReviewer(client)
