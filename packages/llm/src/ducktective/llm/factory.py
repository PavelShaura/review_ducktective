from redis.asyncio import (
    Redis,
)

from ducktective.core.review.investigation import (
    InvestigationSink,
)
from ducktective.core.review.ports import (
    CodeReviewer,
)
from ducktective.llm.agentic_reviewer import (
    DEFAULT_MAX_STEPS,
    AgenticCodeReviewer,
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
    local_supports_tools: bool = True,
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
        supports_tools=local_supports_tools,
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


def build_code_reviewers(
    *,
    redis_client: Redis | None,
    local_provider: str,
    local_model: str,
    local_base_url: str,
    local_api_key: str,
    cloud_model: str,
    cloud_api_key: str,
    cloud_enabled: bool,
    cache_ttl_seconds: int,
    timeout_seconds: float,
    local_supports_tools: bool = True,
    agentic_enabled: bool = True,
    max_agent_steps: int = DEFAULT_MAX_STEPS,
    sink: InvestigationSink | None = None,
) -> tuple[CodeReviewer, ...]:
    """Собирает ревьюеров прогона.

    Их двое и оба читают файл одним и тем же взглядом (D-022): агентный
    дозапрашивает окружение инструментами, одноразовый работает по тому, что
    собрано заранее. Второй нужен всегда — он же запасной путь для файла,
    который вместе с диалогом не помещается в окно.

    Фабрика принимает примитивы, а не объект настроек: пакет моделей не должен
    зависеть от конфигурации приложений, но собирать зависимости в каждом
    приложении заново — источник расхождений.

    Клиент один на обоих: он не хранит состояния прогона, а общий кэш ответов
    экономит повтор там, где подсказка совпала.

    Без Redis ревьюеры работают без кэша: в автономном режиме внешних сервисов
    нет, а повторные прогоны там редки.
    """
    router = build_model_router(
        local_provider=local_provider,
        local_model=local_model,
        local_base_url=local_base_url,
        local_api_key=local_api_key,
        cloud_model=cloud_model,
        cloud_api_key=cloud_api_key,
        cloud_enabled=cloud_enabled,
        local_supports_tools=local_supports_tools,
    )
    cache = (
        RedisResponseCache(redis_client, ttl_seconds=cache_ttl_seconds)
        if redis_client is not None
        else None
    )
    client = LiteLlmClient(router, cache=cache, timeout_seconds=timeout_seconds)
    single_pass = LlmCodeReviewer(client)

    if not agentic_enabled or not router.supports_tool_calling(cloud_allowed=cloud_enabled):
        return (single_pass,)

    return (
        AgenticCodeReviewer(
            client,
            fallback=single_pass,
            max_steps=max_agent_steps,
            sink=sink,
        ),
        single_pass,
    )
