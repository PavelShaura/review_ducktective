from collections.abc import (
    Sequence,
)

from redis.asyncio import (
    Redis,
)

from ducktective.core.chat.ports import (
    ChatAgent,
)
from ducktective.core.code_repository.value_objects import (
    ModelTrust,
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
from ducktective.llm.chat_agent import (
    AgenticChatAgent,
    PresetChatAgent,
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
    cloud_enabled: bool,
    remote_choices: Sequence[ModelChoice] = (),
    local_supports_tools: bool = True,
    local_context_window: int = 0,
) -> ModelRouter:
    """Собирает роутер.

    Локальный инференс может обслуживаться разными серверами: Ollama на этой же
    машине или OpenAI-совместимый сервер вроде LM Studio на соседнем хосте.
    Для LiteLLM это разные префиксы модели, поэтому провайдер задаётся явно.

    Удалённые модели приходят готовым списком: их описывает реестр установки,
    и знать про файл настроек пакету моделей незачем.
    """
    local_choice = ModelChoice(
        name="local",
        model=f"{local_provider}/{local_model}",
        provider=local_provider,
        api_base=local_base_url,
        api_key=local_api_key or None,
        trust=ModelTrust.LOCAL,
        supports_tools=local_supports_tools,
        context_window=local_context_window,
    )
    return ModelRouter(
        local_choice=local_choice,
        remote_choices=remote_choices,
        remote_enabled=cloud_enabled,
    )


def build_chat_agent(
    *,
    local_provider: str,
    local_model: str,
    local_base_url: str,
    local_api_key: str,
    cloud_enabled: bool,
    timeout_seconds: float,
    remote_choices: Sequence[ModelChoice] = (),
    local_supports_tools: bool = True,
    local_context_window: int = 0,
) -> ChatAgent:
    """Собирает агента разговора.

    Кэш ответов не подключается: два одинаковых вопроса в разговоре означают,
    что первый ответ не устроил, и выдать тот же второй раз — худшее, что
    можно сделать. Ревью повторяет один и тот же дифф, разговор — нет.

    Агент выбирается один раз и по тому же признаку, что и ревьюер: цикл
    с инструментами там, где модель их умеет, преднабор — где нет.
    """
    router = build_model_router(
        local_provider=local_provider,
        local_model=local_model,
        local_base_url=local_base_url,
        local_api_key=local_api_key,
        cloud_enabled=cloud_enabled,
        remote_choices=remote_choices,
        local_supports_tools=local_supports_tools,
        local_context_window=local_context_window,
    )
    client = LiteLlmClient(router, timeout_seconds=timeout_seconds)
    preset = PresetChatAgent(client)

    if not router.supports_tool_calling(allowed_trust=ModelTrust.TRAINING_REMOTE):
        return preset

    return AgenticChatAgent(client, fallback=preset)


def build_code_reviewers(
    *,
    redis_client: Redis | None,
    local_provider: str,
    local_model: str,
    local_base_url: str,
    local_api_key: str,
    cloud_enabled: bool,
    cache_ttl_seconds: int,
    timeout_seconds: float,
    remote_choices: Sequence[ModelChoice] = (),
    local_supports_tools: bool = True,
    local_context_window: int = 0,
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
        cloud_enabled=cloud_enabled,
        remote_choices=remote_choices,
        local_supports_tools=local_supports_tools,
        local_context_window=local_context_window,
    )
    cache = (
        RedisResponseCache(redis_client, ttl_seconds=cache_ttl_seconds)
        if redis_client is not None
        else None
    )
    client = LiteLlmClient(router, cache=cache, timeout_seconds=timeout_seconds)
    single_pass = LlmCodeReviewer(client)

    if not agentic_enabled or not router.supports_tool_calling(
        allowed_trust=ModelTrust.TRAINING_REMOTE
    ):
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
