import os
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
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from ducktective.application.chat.ask import (
    AskQuestion,
)
from ducktective.application.models.load import (
    LoadTenantModels,
)
from ducktective.config.models import (
    legacy_remote_model,
    load_remote_models,
)
from ducktective.config.settings import (
    Settings,
)
from ducktective.core.review.ports import (
    CodeReviewer,
)
from ducktective.core.types import (
    TenantId,
)
from ducktective.llm.embedder import (
    LiteLlmEmbedder,
)
from ducktective.llm.factory import (
    build_chat_agent,
    build_code_reviewers,
)
from ducktective.llm.registry import (
    build_remote_choices,
    build_tenant_choices,
)
from ducktective.llm.router import (
    ModelChoice,
)
from ducktective.retrieval.navigation import (
    IndexedNavigators,
)
from ducktective.retrieval.session_scope import (
    SessionScopedHybridSearch,
    SessionScopedSymbolReader,
)
from ducktective.storage.cipher import (
    FernetSecretCipher,
)
from ducktective.storage.events.null_publisher import (
    NullEventPublisher,
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


def secret_cipher(settings: Settings) -> FernetSecretCipher | None:
    """Шифрование ключей провайдеров, если секрет задан.

    Отсутствие секрета не мешает работать: модели установки и локальная
    сборка его не требуют. Мешает оно ровно одному — сохранить ключ,
    введённый в интерфейсе, и об этом ручка говорит прямо.
    """
    if not settings.models_secret_key:
        return None
    return FernetSecretCipher(settings.models_secret_key)


async def tenant_model_choices(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
) -> tuple[ModelChoice, ...]:
    """Модели организации плюс модели установки.

    Порядок важен: свои идут первыми, потому что заводили их сознательно,
    а реестр установки — то, что досталось от администратора.
    """
    resolved = await LoadTenantModels(
        SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id),
        NullEventPublisher(),
        secret_cipher(settings),
    ).execute(tenant_id)

    return build_tenant_choices(resolved) + remote_model_choices(settings)


def remote_model_choices(settings: Settings) -> tuple[ModelChoice, ...]:
    """Удалённые модели установки: реестр, а при его отсутствии — прежняя пара настроек.

    Ключи берутся из окружения по именам, названным в реестре: файл реестра
    лежит рядом с настройками и попадает в резервные копии, а секретам там
    не место (D-028).
    """
    specs = list(load_remote_models(settings.remote_models_file))
    if not specs and settings.anthropic_api_key:
        specs.append(
            legacy_remote_model(
                model=settings.cloud_review_model,
                context_window=settings.cloud_review_model_context_window,
                api_key_env="ANTHROPIC_API_KEY",
            )
        )

    return build_remote_choices(specs, environment=os.environ)


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_unit_of_work(request: Request) -> SqlAlchemyUnitOfWork:
    """Единица работы контура входа — без названного тенанта.

    Такая транзакция не видит ни строки с кодом: политики базы сравнивают
    каждую с пустым значением. Ей это и не нужно — она читает учётные
    записи и приглашения, то есть выясняет, кто пришёл. Данными
    занимается `tenant_unit_of_work` из `security`.
    """
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


def build_navigators(app: FastAPI, tenant_id: TenantId) -> IndexedNavigators:
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
        symbols=SessionScopedSymbolReader(session_factory, tenant_id=tenant_id),
        search=SessionScopedHybridSearch(session_factory, embedder, tenant_id=tenant_id),
    )


async def build_chat_use_case(app: FastAPI, tenant_id: TenantId) -> AskQuestion:
    """Собирает разговор: агент, навигация и запись реплик.

    Живёт здесь, а не в зависимостях FastAPI, потому что нужен сокету:
    у веб-сокета нет цикла «запрос — ответ», в который `Depends`
    встраивается.
    """
    settings: Settings = app.state.settings
    return AskQuestion(
        SqlAlchemyUnitOfWork(app.state.session_factory, tenant_id=tenant_id),
        RedisEventPublisher(app.state.redis),
        build_chat_agent(
            local_provider=settings.local_llm_provider,
            local_model=settings.local_chat_model or settings.local_review_model,
            local_base_url=settings.local_llm_base_url,
            local_api_key=settings.local_llm_api_key,
            cloud_enabled=settings.cloud_providers_allowed,
            remote_choices=await tenant_model_choices(
                settings,
                app.state.session_factory,
                tenant_id,
            ),
            timeout_seconds=settings.llm_timeout_seconds,
            local_supports_tools=settings.local_review_model_supports_tools,
            local_context_window=settings.local_review_model_context_window,
        ),
        build_navigators(app, tenant_id),
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
        cloud_enabled=settings.cloud_providers_allowed,
        remote_choices=remote_model_choices(settings),
        cache_ttl_seconds=settings.llm_cache_ttl_seconds,
        timeout_seconds=settings.llm_timeout_seconds,
        local_supports_tools=settings.local_review_model_supports_tools,
        local_context_window=settings.local_review_model_context_window,
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
