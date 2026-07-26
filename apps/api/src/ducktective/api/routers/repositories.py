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
    UnitOfWorkDependency,
)
from ducktective.api.schemas.code_repository import (
    RegisterRepositoryRequest,
    RepositoryResponse,
)
from ducktective.application.code_repository.list_repositories import (
    ListCodeRepositories,
)
from ducktective.application.code_repository.register import (
    RegisterCodeRepository,
    RegisterCodeRepositoryCommand,
    RepositoryAlreadyRegisteredError,
)
from ducktective.core.exceptions import (
    InvariantViolationError,
)
from ducktective.core.types import (
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
