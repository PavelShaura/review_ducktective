from typing import (
    Annotated,
)

from arq import (
    ArqRedis,
)
from fastapi import (
    Depends,
    FastAPI,
    Request,
)

from ducktective.application.chat.ask import (
    AskQuestion,
)
from ducktective.config.settings import (
    Settings,
)
from ducktective.core.review.ports import (
    CodeReviewer,
)
from ducktective.llm.embedder import (
    LiteLlmEmbedder,
)
from ducktective.llm.factory import (
    build_chat_agent,
    build_code_reviewers,
)
from ducktective.retrieval.navigation import (
    IndexedNavigators,
)
from ducktective.retrieval.session_scope import (
    SessionScopedHybridSearch,
    SessionScopedSymbolReader,
)
from ducktective.storage.events.redis_publisher import (
    RedisEventPublisher,
)
from ducktective.storage.repositories.investigation import (
    SqlAlchemyInvestigationLog,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ducktective.vcs.diff_parser import (
    UnifiedDiffParser,
)
from ducktective.vcs.git_provider import (
    LocalGitProvider,
)


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_unit_of_work(request: Request) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(request.app.state.session_factory)


def get_event_publisher(request: Request) -> RedisEventPublisher:
    return RedisEventPublisher(request.app.state.redis)


def get_vcs_provider() -> LocalGitProvider:
    return LocalGitProvider()


def get_diff_parser() -> UnifiedDiffParser:
    return UnifiedDiffParser()


def get_investigation_log(request: Request) -> SqlAlchemyInvestigationLog:
    return SqlAlchemyInvestigationLog(request.app.state.session_factory)


def get_task_queue(request: Request) -> ArqRedis:
    queue: ArqRedis = request.app.state.task_queue
    return queue


def build_navigators(app: FastAPI) -> IndexedNavigators:
    """Навигация по индексу для разговора.

    Собирается на каждый вопрос: внутри только сессии из общей фабрики,
    состояния между вопросами у неё нет, а держать её в состоянии
    приложения значит завести вторую точку правды о настройках.
    """
    settings: Settings = app.state.settings
    session_factory = app.state.session_factory
    embedder = LiteLlmEmbedder(
        model=settings.local_embedding_model,
        dimensions=settings.embedding_dimensions,
        base_url=settings.local_embedding_base_url or None,
        api_key=settings.local_llm_api_key,
    )
    return IndexedNavigators(
        symbols=SessionScopedSymbolReader(session_factory),
        search=SessionScopedHybridSearch(session_factory, embedder),
    )


def build_chat_use_case(app: FastAPI) -> AskQuestion:
    """Собирает разговор: агент, навигация и запись реплик.

    Живёт здесь, а не в зависимостях FastAPI, потому что нужен сокету:
    у веб-сокета нет цикла «запрос — ответ», в который `Depends`
    встраивается.
    """
    settings: Settings = app.state.settings
    return AskQuestion(
        SqlAlchemyUnitOfWork(app.state.session_factory),
        RedisEventPublisher(app.state.redis),
        build_chat_agent(
            local_provider=settings.local_llm_provider,
            local_model=settings.local_review_model,
            local_base_url=settings.local_llm_base_url,
            local_api_key=settings.local_llm_api_key,
            cloud_model=settings.cloud_review_model,
            cloud_api_key=settings.anthropic_api_key,
            cloud_enabled=settings.cloud_providers_allowed,
            timeout_seconds=settings.llm_timeout_seconds,
            local_supports_tools=settings.local_review_model_supports_tools,
            local_context_window=settings.local_review_model_context_window,
            cloud_context_window=settings.cloud_review_model_context_window,
        ),
        build_navigators(app),
        max_output_tokens=settings.llm_max_output_tokens,
    )


def get_code_reviewers(request: Request) -> tuple[CodeReviewer, ...]:
    settings = get_settings(request)
    return build_code_reviewers(
        redis_client=request.app.state.redis,
        local_provider=settings.local_llm_provider,
        local_model=settings.local_review_model,
        local_base_url=settings.local_llm_base_url,
        local_api_key=settings.local_llm_api_key,
        cloud_model=settings.cloud_review_model,
        cloud_api_key=settings.anthropic_api_key,
        cloud_enabled=settings.cloud_providers_allowed,
        cache_ttl_seconds=settings.llm_cache_ttl_seconds,
        timeout_seconds=settings.llm_timeout_seconds,
        local_supports_tools=settings.local_review_model_supports_tools,
        local_context_window=settings.local_review_model_context_window,
        cloud_context_window=settings.cloud_review_model_context_window,
    )


SettingsDependency = Annotated[Settings, Depends(get_settings)]
UnitOfWorkDependency = Annotated[SqlAlchemyUnitOfWork, Depends(get_unit_of_work)]
EventPublisherDependency = Annotated[RedisEventPublisher, Depends(get_event_publisher)]
VcsProviderDependency = Annotated[LocalGitProvider, Depends(get_vcs_provider)]
DiffParserDependency = Annotated[UnifiedDiffParser, Depends(get_diff_parser)]
CodeReviewersDependency = Annotated[tuple[CodeReviewer, ...], Depends(get_code_reviewers)]
TaskQueueDependency = Annotated[ArqRedis, Depends(get_task_queue)]
InvestigationLogDependency = Annotated[
    SqlAlchemyInvestigationLog,
    Depends(get_investigation_log),
]
