from uuid import (
    UUID,
)

from fastapi import (
    APIRouter,
    HTTPException,
    Response,
    status,
)

from ducktective.api.dependencies import (
    DiffParserDependency,
    EventPublisherDependency,
    TaskQueueDependency,
    UnitOfWorkDependency,
    VcsProviderDependency,
)
from ducktective.api.schemas.review import (
    FeedbackDigestResponse,
    FeedbackResponse,
    FileContextResponse,
    FilePatchResponse,
    ReviewRunResponse,
    ReviewRunSummary,
    StartReviewRequest,
    SubmitFeedbackRequest,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.review.delete_run import (
    DeleteReviewRun,
)
from ducktective.application.review.prepare_run import (
    EmptyDiffError,
    PrepareReviewRun,
    PrepareReviewRunCommand,
)
from ducktective.application.review.read_feedback import (
    CollectFeedback,
)
from ducktective.application.review.read_file import (
    FileContentUnavailableError,
    GetFileContext,
    GetFilePatch,
)
from ducktective.application.review.read_runs import (
    GetReviewRun,
    ListReviewRuns,
)
from ducktective.application.review.submit_feedback import (
    SubmitFindingFeedback,
    SubmitFindingFeedbackCommand,
)
from ducktective.config.queues import (
    REVIEW_TASK_NAME,
)
from ducktective.core.diff.value_objects import (
    DiffSide,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
    VcsOperationError,
)
from ducktective.core.review.value_objects import (
    ReviewStatus,
)
from ducktective.core.types import (
    FindingId,
    RepositoryId,
    ReviewFileId,
    ReviewRunId,
    TenantId,
)


router = APIRouter(tags=["reviews"])

NO_STORE = "no-store"


@router.post(
    "/repositories/{repository_id}/reviews",
    response_model=ReviewRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_review(
    repository_id: UUID,
    payload: StartReviewRequest,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
    vcs_provider: VcsProviderDependency,
    diff_parser: DiffParserDependency,
) -> ReviewRunResponse:
    use_case = PrepareReviewRun(unit_of_work, event_publisher, vcs_provider, diff_parser)
    command = PrepareReviewRunCommand(
        tenant_id=TenantId(payload.tenant_id),
        repository_id=RepositoryId(repository_id),
        base=payload.base,
        head=payload.head,
        source=payload.source,
        external_pull_request_id=payload.external_pull_request_id,
    )

    try:
        run = await use_case.execute(command)
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except EmptyDiffError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except VcsOperationError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error

    return ReviewRunResponse.from_domain(run)


@router.get("/reviews/{run_id}", response_model=ReviewRunResponse)
async def get_review(
    run_id: UUID,
    tenant_id: UUID,
    unit_of_work: UnitOfWorkDependency,
) -> ReviewRunResponse:
    use_case = GetReviewRun(unit_of_work)

    try:
        run = await use_case.execute(TenantId(tenant_id), ReviewRunId(run_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return ReviewRunResponse.from_domain(run)


@router.post(
    "/reviews/{run_id}/run",
    response_model=ReviewRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_review(
    run_id: UUID,
    tenant_id: UUID,
    unit_of_work: UnitOfWorkDependency,
    task_queue: TaskQueueDependency,
) -> ReviewRunResponse:
    """Ставит прогон в очередь.

    Ревью занимает минуты, поэтому HTTP-запрос не ждёт его завершения: клиент
    опрашивает статус через GET.
    """
    try:
        run = await GetReviewRun(unit_of_work).execute(TenantId(tenant_id), ReviewRunId(run_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    if run.status is not ReviewStatus.QUEUED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Прогон в статусе {run.status} нельзя отправить на ревью",
        )

    await task_queue.enqueue_job(REVIEW_TASK_NAME, str(run_id), str(tenant_id))
    return ReviewRunResponse.from_domain(run)


@router.delete("/reviews/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    run_id: UUID,
    tenant_id: UUID,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> None:
    use_case = DeleteReviewRun(unit_of_work, event_publisher)

    try:
        await use_case.execute(TenantId(tenant_id), ReviewRunId(run_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error


@router.post(
    "/reviews/{run_id}/findings/{finding_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    run_id: UUID,
    finding_id: UUID,
    payload: SubmitFeedbackRequest,
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> FeedbackResponse:
    """Фиксирует оценку находки.

    Отметки накапливаются как размеченная выборка для измерения качества.
    """
    use_case = SubmitFindingFeedback(unit_of_work, event_publisher)
    command = SubmitFindingFeedbackCommand(
        tenant_id=TenantId(payload.tenant_id),
        run_id=ReviewRunId(run_id),
        finding_id=FindingId(finding_id),
        verdict=payload.verdict,
        comment=payload.comment,
    )

    try:
        entry = await use_case.execute(command)
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return FeedbackResponse.from_domain(entry)


@router.get("/reviews/{run_id}/files/{file_id}/patch", response_model=FilePatchResponse)
async def get_file_patch(
    run_id: UUID,
    file_id: UUID,
    tenant_id: UUID,
    response: Response,
    unit_of_work: UnitOfWorkDependency,
    vcs_provider: VcsProviderDependency,
) -> FilePatchResponse:
    use_case = GetFilePatch(unit_of_work, vcs_provider)

    try:
        view = await use_case.execute(
            TenantId(tenant_id),
            ReviewRunId(run_id),
            ReviewFileId(file_id),
        )
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    response.headers["Cache-Control"] = NO_STORE
    return FilePatchResponse.from_view(view)


@router.get("/reviews/{run_id}/files/{file_id}/content", response_model=FileContextResponse)
async def get_file_context(
    run_id: UUID,
    file_id: UUID,
    tenant_id: UUID,
    start_line: int,
    end_line: int,
    response: Response,
    unit_of_work: UnitOfWorkDependency,
    vcs_provider: VcsProviderDependency,
    side: DiffSide = DiffSide.NEW,
) -> FileContextResponse:
    use_case = GetFileContext(unit_of_work, vcs_provider)

    try:
        view = await use_case.execute(
            TenantId(tenant_id),
            ReviewRunId(run_id),
            ReviewFileId(file_id),
            side=side,
            start_line=start_line,
            end_line=end_line,
        )
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except FileContentUnavailableError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except VcsOperationError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error

    response.headers["Cache-Control"] = NO_STORE
    return FileContextResponse.from_view(view)


@router.get("/repositories/{repository_id}/reviews", response_model=list[ReviewRunSummary])
async def list_reviews(
    repository_id: UUID,
    tenant_id: UUID,
    unit_of_work: UnitOfWorkDependency,
    limit: int = 50,
) -> list[ReviewRunSummary]:
    use_case = ListReviewRuns(unit_of_work)
    runs = await use_case.execute(
        TenantId(tenant_id),
        RepositoryId(repository_id),
        limit=limit,
    )
    return [ReviewRunSummary.from_domain(run) for run in runs]


@router.get("/repositories/{repository_id}/feedback", response_model=FeedbackDigestResponse)
async def get_feedback_digest(
    repository_id: UUID,
    tenant_id: UUID,
    unit_of_work: UnitOfWorkDependency,
    response: Response,
    runs_limit: int = 50,
) -> FeedbackDigestResponse:
    use_case = CollectFeedback(unit_of_work)
    view = await use_case.execute(
        TenantId(tenant_id),
        RepositoryId(repository_id),
        runs_limit=runs_limit,
    )

    response.headers["Cache-Control"] = NO_STORE
    return FeedbackDigestResponse.from_view(view)
