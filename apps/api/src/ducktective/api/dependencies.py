from typing import (
    Annotated,
)

from arq import (
    ArqRedis,
)
from fastapi import (
    Depends,
    Request,
)

from ducktective.config.settings import (
    Settings,
)
from ducktective.llm.code_reviewer import (
    LlmCodeReviewer,
)
from ducktective.llm.factory import (
    build_code_reviewers,
)
from ducktective.storage.events.redis_publisher import (
    RedisEventPublisher,
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


def get_task_queue(request: Request) -> ArqRedis:
    queue: ArqRedis = request.app.state.task_queue
    return queue


def get_code_reviewers(request: Request) -> tuple[LlmCodeReviewer, ...]:
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
    )


SettingsDependency = Annotated[Settings, Depends(get_settings)]
UnitOfWorkDependency = Annotated[SqlAlchemyUnitOfWork, Depends(get_unit_of_work)]
EventPublisherDependency = Annotated[RedisEventPublisher, Depends(get_event_publisher)]
VcsProviderDependency = Annotated[LocalGitProvider, Depends(get_vcs_provider)]
DiffParserDependency = Annotated[UnifiedDiffParser, Depends(get_diff_parser)]
CodeReviewersDependency = Annotated[tuple[LlmCodeReviewer, ...], Depends(get_code_reviewers)]
TaskQueueDependency = Annotated[ArqRedis, Depends(get_task_queue)]
