from uuid import (
    UUID,
)

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    status,
)

from ducktective.api.dependencies import (
    EventPublisherDependency,
    SettingsDependency,
    TaskQueueDependency,
    VcsProviderDependency,
    tenant_model_choices,
)
from ducktective.api.schemas.code_repository import (
    AvailableModelResponse,
    RegisterRepositoryRequest,
    RepositoryResponse,
    ResolvedRevisionResponse,
)
from ducktective.api.schemas.indexing import (
    CancelIndexingResponse,
    DeleteIndexResponse,
    IndexStateResponse,
    StartIndexingRequest,
    StartIndexingResponse,
)
from ducktective.api.security import (
    MemberDependency,
    TenantUnitOfWorkDependency,
)
from ducktective.application.code_repository.delete import (
    DeleteCodeRepository,
)
from ducktective.application.code_repository.list_repositories import (
    ListCodeRepositories,
)
from ducktective.application.code_repository.register import (
    RegisterCodeRepository,
    RegisterCodeRepositoryCommand,
    RepositoryAlreadyRegisteredError,
)
from ducktective.application.code_repository.resolve_revision import (
    ResolveRepositoryRevision,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.indexing.cancel import (
    CancelIndexing,
)
from ducktective.application.indexing.delete import (
    DeleteIndex,
    IndexingInProgressError,
)
from ducktective.application.indexing.enqueue import (
    EnqueueIndexing,
    IndexingAlreadyQueuedError,
)
from ducktective.application.indexing.read_state import (
    GetIndexState,
)
from ducktective.config.queues import (
    INDEX_QUEUE,
    INDEX_TASK_NAME,
)
from ducktective.core.exceptions import (
    DomainError,
    EntityNotFoundError,
    InvariantViolationError,
    VcsOperationError,
)
from ducktective.core.types import (
    RepositoryId,
)
from ducktective.llm.factory import (
    build_model_router,
)


router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.post("", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
async def register_repository(
    payload: RegisterRepositoryRequest,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> RepositoryResponse:
    use_case = RegisterCodeRepository(unit_of_work, event_publisher)
    command = RegisterCodeRepositoryCommand(
        tenant_id=member.tenant_id,
        name=payload.name,
        vcs_provider=payload.vcs_provider,
        local_path=payload.local_path,
        remote_url=payload.remote_url,
        default_branch=payload.default_branch,
        egress_policy=payload.egress_policy,
    )

    try:
        repository = await use_case.execute(command)
    except RepositoryAlreadyRegisteredError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except InvariantViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error

    return RepositoryResponse.from_domain(repository)


@router.get("", response_model=list[RepositoryResponse])
async def list_repositories(
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
) -> list[RepositoryResponse]:
    use_case = ListCodeRepositories(unit_of_work)
    repositories = await use_case.execute(member.tenant_id)
    return [RepositoryResponse.from_domain(repository) for repository in repositories]


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(
    repository_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> None:
    """Убирает репозиторий вместе с индексом и делами."""
    use_case = DeleteCodeRepository(unit_of_work, event_publisher)

    try:
        await use_case.execute(member.tenant_id, RepositoryId(repository_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error


@router.post("/{repository_id}/index/cancel", response_model=CancelIndexingResponse)
async def cancel_indexing(
    repository_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> CancelIndexingResponse:
    """Просит прекратить идущую индексацию.

    Ответ приходит сразу, а воркер выходит на ближайшей отсечке: обрывать
    его посреди записи нельзя, зато записанное откатывается транзакцией.
    """
    use_case = CancelIndexing(unit_of_work, event_publisher)

    try:
        cancelled = await use_case.execute(member.tenant_id, RepositoryId(repository_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return CancelIndexingResponse(cancelled=cancelled)


@router.get("/{repository_id}/index", response_model=IndexStateResponse)
async def get_index_state(
    repository_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
) -> IndexStateResponse:
    use_case = GetIndexState(unit_of_work)

    try:
        view = await use_case.execute(member.tenant_id, RepositoryId(repository_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return IndexStateResponse.from_view(view)


@router.get("/{repository_id}/revision", response_model=ResolvedRevisionResponse)
async def resolve_revision(
    repository_id: UUID,
    member: MemberDependency,
    revision: str,
    unit_of_work: TenantUnitOfWorkDependency,
    vcs_provider: VcsProviderDependency,
) -> ResolvedRevisionResponse:
    """Разрешает ссылку на ревизию в коммит.

    `HEAD`, имя ветки и `abc123~1` — ссылки, и во что они указывают, знает
    только git. Интерфейсу это нужно, чтобы честно сравнить ревизию индекса
    с той, которую собираются ревьюить.
    """
    use_case = ResolveRepositoryRevision(unit_of_work, vcs_provider)

    try:
        view = await use_case.execute(member.tenant_id, RepositoryId(repository_id), revision)
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except (DomainError, ValueError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error

    return ResolvedRevisionResponse.from_view(view)


@router.post(
    "/{repository_id}/index",
    response_model=StartIndexingResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_indexing(
    repository_id: UUID,
    payload: StartIndexingRequest,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
    vcs_provider: VcsProviderDependency,
    task_queue: TaskQueueDependency,
) -> StartIndexingResponse:
    """Ставит индексацию в очередь.

    Запрос не ждёт результата: полная индексация чужого репозитория занимает
    минуты, а состояние потом опрашивается через GET.
    """
    use_case = EnqueueIndexing(unit_of_work, event_publisher, vcs_provider)

    try:
        snapshot_id = await use_case.execute(
            member.tenant_id,
            RepositoryId(repository_id),
            payload.revision,
        )
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except IndexingAlreadyQueuedError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except VcsOperationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error

    await task_queue.enqueue_job(
        INDEX_TASK_NAME,
        str(repository_id),
        str(member.tenant_id),
        payload.revision,
        str(snapshot_id),
        _queue_name=INDEX_QUEUE,
    )
    return StartIndexingResponse(queued=True, revision=payload.revision)


@router.delete("/{repository_id}/index", response_model=DeleteIndexResponse)
async def delete_index(
    repository_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> DeleteIndexResponse:
    """Стирает индекс, оставляя репозиторий и заведённые по нему дела.

    Нужен, когда изменились правила разбора: инкрементальная сборка не
    перечитывает неизменившиеся файлы и новых правил к ним не применит.
    """
    use_case = DeleteIndex(unit_of_work, event_publisher)

    try:
        removed = await use_case.execute(member.tenant_id, RepositoryId(repository_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except IndexingInProgressError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    return DeleteIndexResponse(removed_snapshots=removed)


@router.get("/{repository_id}/models", response_model=list[AvailableModelResponse])
async def list_available_models(
    repository_id: UUID,
    request: Request,
    member: MemberDependency,
    settings: SettingsDependency,
    unit_of_work: TenantUnitOfWorkDependency,
) -> list[AvailableModelResponse]:
    """Модели, разрешённые политикой этого репозитория.

    Список считается от политики, а не от установки целиком: предложить
    модель, а потом отказать при запуске — худший способ объяснить правило.
    """
    async with unit_of_work:
        repository = await unit_of_work.code_repositories.get(RepositoryId(repository_id))
        if repository.tenant_id != member.tenant_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Репозиторий не найден")

    router_for_policy = build_model_router(
        local_provider=settings.local_llm_provider,
        local_model=settings.local_review_model,
        local_base_url=settings.local_llm_base_url,
        local_api_key=settings.local_llm_api_key,
        cloud_enabled=settings.cloud_providers_allowed,
        remote_choices=await tenant_model_choices(
            settings,
            request.app.state.session_factory,
            member.tenant_id,
        ),
        local_supports_tools=settings.local_review_model_supports_tools,
        local_context_window=settings.local_review_model_context_window,
    )
    catalogue = router_for_policy.catalogue(allowed_trust=repository.egress_policy.max_trust)

    return [
        AvailableModelResponse(
            name=choice.name,
            model=choice.model,
            trust=choice.trust,
            supports_tools=choice.supports_tools,
            context_window=choice.context_window,
        )
        for choice in catalogue
    ]
