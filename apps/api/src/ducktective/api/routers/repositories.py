from uuid import (
    UUID,
)

from fastapi import (
    APIRouter,
    HTTPException,
    status,
)

from ducktective.api.dependencies import (
    EventPublisherDependency,
    TaskQueueDependency,
    UnitOfWorkDependency,
)
from ducktective.api.schemas.code_repository import (
    RegisterRepositoryRequest,
    RepositoryResponse,
)
from ducktective.api.schemas.indexing import (
    CancelIndexingResponse,
    IndexStateResponse,
    StartIndexingRequest,
    StartIndexingResponse,
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
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.indexing.cancel import (
    CancelIndexing,
)
from ducktective.application.indexing.read_state import (
    GetIndexState,
)
from ducktective.config.queues import (
    INDEX_QUEUE,
    INDEX_TASK_NAME,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
    InvariantViolationError,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.post("", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
async def register_repository(
    payload: RegisterRepositoryRequest,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> RepositoryResponse:
    use_case = RegisterCodeRepository(unit_of_work, event_publisher)
    command = RegisterCodeRepositoryCommand(
        tenant_id=TenantId(payload.tenant_id),
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
    tenant_id: UUID,
    unit_of_work: UnitOfWorkDependency,
) -> list[RepositoryResponse]:
    use_case = ListCodeRepositories(unit_of_work)
    repositories = await use_case.execute(TenantId(tenant_id))
    return [RepositoryResponse.from_domain(repository) for repository in repositories]


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(
    repository_id: UUID,
    tenant_id: UUID,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> None:
    """Убирает репозиторий вместе с индексом и делами."""
    use_case = DeleteCodeRepository(unit_of_work, event_publisher)

    try:
        await use_case.execute(TenantId(tenant_id), RepositoryId(repository_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error


@router.post("/{repository_id}/index/cancel", response_model=CancelIndexingResponse)
async def cancel_indexing(
    repository_id: UUID,
    tenant_id: UUID,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> CancelIndexingResponse:
    """Просит прекратить идущую индексацию.

    Ответ приходит сразу, а воркер выходит на ближайшей отсечке: обрывать
    его посреди записи нельзя, зато записанное откатывается транзакцией.
    """
    use_case = CancelIndexing(unit_of_work, event_publisher)

    try:
        cancelled = await use_case.execute(TenantId(tenant_id), RepositoryId(repository_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return CancelIndexingResponse(cancelled=cancelled)


@router.get("/{repository_id}/index", response_model=IndexStateResponse)
async def get_index_state(
    repository_id: UUID,
    tenant_id: UUID,
    unit_of_work: UnitOfWorkDependency,
) -> IndexStateResponse:
    use_case = GetIndexState(unit_of_work)

    try:
        view = await use_case.execute(TenantId(tenant_id), RepositoryId(repository_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return IndexStateResponse.from_view(view)


@router.post(
    "/{repository_id}/index",
    response_model=StartIndexingResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_indexing(
    repository_id: UUID,
    payload: StartIndexingRequest,
    unit_of_work: UnitOfWorkDependency,
    task_queue: TaskQueueDependency,
) -> StartIndexingResponse:
    """Ставит индексацию в очередь.

    Запрос не ждёт результата: полная индексация чужого репозитория занимает
    минуты, а состояние потом опрашивается через GET.
    """
    try:
        await GetIndexState(unit_of_work).execute(
            TenantId(payload.tenant_id),
            RepositoryId(repository_id),
        )
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    await task_queue.enqueue_job(
        INDEX_TASK_NAME,
        str(repository_id),
        str(payload.tenant_id),
        payload.revision,
        _queue_name=INDEX_QUEUE,
    )
    return StartIndexingResponse(queued=True, revision=payload.revision)
