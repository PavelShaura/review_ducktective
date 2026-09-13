from uuid import (
    UUID,
)

from arq.connections import (
    ArqRedis,
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
    InvestigationLogDependency,
    TaskQueueDependency,
    VcsProviderDependency,
)
from ducktective.api.schemas.review import (
    CancelRunResponse,
    FeedbackDigestResponse,
    FeedbackResponse,
    FileContextResponse,
    FilePatchResponse,
    InvestigationResponse,
    ReviewRunResponse,
    ReviewRunSummary,
    StartReviewRequest,
    SubmitFeedbackRequest,
)
from ducktective.api.security import (
    MemberDependency,
    TenantUnitOfWorkDependency,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.indexing.ensure_for_revision import (
    EnsureIndexForRevision,
)
from ducktective.application.review.cancel_run import (
    CancelReviewRun,
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
from ducktective.application.review.read_investigation import (
    ReadInvestigation,
)
from ducktective.application.review.read_runs import (
    GetReviewRun,
    ListReviewRuns,
)
from ducktective.application.review.restart_run import (
    RestartReviewRun,
    RunNotRestartableError,
)
from ducktective.application.review.resume_run import (
    ResumeReviewRun,
    RunNotResumableError,
)
from ducktective.application.review.submit_feedback import (
    SubmitFindingFeedback,
    SubmitFindingFeedbackCommand,
)
from ducktective.config.queues import (
    FORGET_CHECKPOINT_TASK_NAME,
    INDEX_QUEUE,
    INDEX_TASK_NAME,
    REVIEW_QUEUE,
    REVIEW_TASK_NAME,
)
from ducktective.core.diff.ports import (
    VcsProvider,
)
from ducktective.core.diff.value_objects import (
    DiffSide,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
    VcsOperationError,
)
from ducktective.core.ports import (
    EventPublisher,
    UnitOfWork,
)
from ducktective.core.review.entities import (
    ReviewRun,
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
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
    vcs_provider: VcsProviderDependency,
    diff_parser: DiffParserDependency,
) -> ReviewRunResponse:
    use_case = PrepareReviewRun(unit_of_work, event_publisher, vcs_provider, diff_parser)
    command = PrepareReviewRunCommand(
        tenant_id=member.tenant_id,
        repository_id=RepositoryId(repository_id),
        base=payload.base,
        head=payload.head,
        source=payload.source,
        external_pull_request_id=payload.external_pull_request_id,
        preferred_model=payload.model,
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
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
) -> ReviewRunResponse:
    use_case = GetReviewRun(unit_of_work)

    try:
        run = await use_case.execute(member.tenant_id, ReviewRunId(run_id))
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
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
    vcs_provider: VcsProviderDependency,
    task_queue: TaskQueueDependency,
) -> ReviewRunResponse:
    """Ставит прогон в очередь.

    Ревью занимает минуты, поэтому HTTP-запрос не ждёт его завершения: клиент
    опрашивает статус через GET.
    """
    try:
        run = await GetReviewRun(unit_of_work).execute(member.tenant_id, ReviewRunId(run_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    if run.status is not ReviewStatus.QUEUED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Прогон в статусе {run.status} нельзя отправить на ревью",
        )

    await _queue_review(
        run, member.tenant_id, unit_of_work, event_publisher, vcs_provider, task_queue
    )
    return ReviewRunResponse.from_domain(run)


async def _queue_review(
    run: ReviewRun,
    tenant_id: TenantId,
    unit_of_work: UnitOfWork,
    event_publisher: EventPublisher,
    vcs_provider: VcsProvider,
    task_queue: ArqRedis,
) -> None:
    """Индекс на ревизии дела — прежде ревью.

    Сборка ставится в свою очередь, ревью — в свою; воркер ревью ждёт конца
    сборки. Ошибка постановки сборки ревью не отменяет: без индекса прогон
    идёт по git, как и раньше.
    """
    try:
        snapshot_id = await EnsureIndexForRevision(
            unit_of_work, event_publisher, vcs_provider
        ).execute(tenant_id, run.repository_id, run.head_sha)
    except (EntityNotFoundError, VcsOperationError):
        snapshot_id = None

    if snapshot_id is not None:
        await task_queue.enqueue_job(
            INDEX_TASK_NAME,
            str(run.repository_id),
            str(tenant_id),
            run.head_sha,
            str(snapshot_id),
            None,
            _queue_name=INDEX_QUEUE,
        )

    await task_queue.enqueue_job(
        REVIEW_TASK_NAME,
        str(run.id),
        str(tenant_id),
        _queue_name=REVIEW_QUEUE,
    )


@router.post(
    "/reviews/{run_id}/restart",
    response_model=ReviewRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def restart_review(
    run_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
    vcs_provider: VcsProviderDependency,
    task_queue: TaskQueueDependency,
) -> ReviewRunResponse:
    """Отправляет прекращённый или неудавшийся прогон на расследование заново.

    Файлы диффа уже разобраны и остаются на месте — повторяется только чтение
    моделью, зато всё целиком: сохранённый ход прогона забывается. Дочитать
    остаток умеет соседний эндпоинт.
    """
    use_case = RestartReviewRun(unit_of_work, event_publisher)

    try:
        run = await use_case.execute(member.tenant_id, ReviewRunId(run_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except RunNotRestartableError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    await _queue_review(
        run, member.tenant_id, unit_of_work, event_publisher, vcs_provider, task_queue
    )
    return ReviewRunResponse.from_domain(run)


@router.post(
    "/reviews/{run_id}/resume",
    response_model=ReviewRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_review(
    run_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
    task_queue: TaskQueueDependency,
) -> ReviewRunResponse:
    """Продолжает прерванное расследование с того места, где оно встало.

    Уже прочитанные пары «файл × ревьюер» не читаются второй раз: ход прогона
    сохранён чекпоинтером. Если сохранять его было нечем, продолжение
    равносильно прогону с начала — результат тот же, просто дороже.
    """
    use_case = ResumeReviewRun(unit_of_work, event_publisher)

    try:
        run = await use_case.execute(member.tenant_id, ReviewRunId(run_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except RunNotResumableError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    await task_queue.enqueue_job(
        REVIEW_TASK_NAME,
        str(run_id),
        str(member.tenant_id),
        True,
        _queue_name=REVIEW_QUEUE,
    )
    return ReviewRunResponse.from_domain(run)


@router.post("/reviews/{run_id}/cancel", response_model=CancelRunResponse)
async def cancel_review(
    run_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> CancelRunResponse:
    """Просит прекратить идущее расследование.

    Ответ приходит сразу, а воркер выходит перед следующим файлом: файл,
    который модель читает прямо сейчас, дочитывается, но результат прогона
    не сохраняется.
    """
    use_case = CancelReviewRun(unit_of_work, event_publisher)

    try:
        cancelled = await use_case.execute(member.tenant_id, ReviewRunId(run_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return CancelRunResponse(cancelled=cancelled)


@router.delete("/reviews/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    run_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
    task_queue: TaskQueueDependency,
) -> None:
    """Удаляет дело вместе с находками, разметкой и сохранённым ходом.

    Ход убирает воркер отдельной задачей: чекпоинтер открыт у него. Задача
    ставится после успешного удаления — иначе уборка случилась бы у дела,
    которое осталось жить.
    """
    use_case = DeleteReviewRun(unit_of_work, event_publisher)

    try:
        await use_case.execute(member.tenant_id, ReviewRunId(run_id))
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    await task_queue.enqueue_job(
        FORGET_CHECKPOINT_TASK_NAME,
        str(run_id),
        str(member.tenant_id),
        _queue_name=REVIEW_QUEUE,
    )


@router.post(
    "/reviews/{run_id}/findings/{finding_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    run_id: UUID,
    finding_id: UUID,
    payload: SubmitFeedbackRequest,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> FeedbackResponse:
    """Фиксирует оценку находки.

    Отметки накапливаются как размеченная выборка для измерения качества.
    """
    use_case = SubmitFindingFeedback(unit_of_work, event_publisher)
    command = SubmitFindingFeedbackCommand(
        tenant_id=member.tenant_id,
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
    member: MemberDependency,
    response: Response,
    unit_of_work: TenantUnitOfWorkDependency,
    vcs_provider: VcsProviderDependency,
) -> FilePatchResponse:
    use_case = GetFilePatch(unit_of_work, vcs_provider)

    try:
        view = await use_case.execute(
            member.tenant_id,
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
    member: MemberDependency,
    start_line: int,
    end_line: int,
    response: Response,
    unit_of_work: TenantUnitOfWorkDependency,
    vcs_provider: VcsProviderDependency,
    side: DiffSide = DiffSide.NEW,
) -> FileContextResponse:
    use_case = GetFileContext(unit_of_work, vcs_provider)

    try:
        view = await use_case.execute(
            member.tenant_id,
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


@router.get("/reviews/{run_id}/investigation", response_model=InvestigationResponse)
async def get_investigation(
    run_id: UUID,
    member: MemberDependency,
    response: Response,
    unit_of_work: TenantUnitOfWorkDependency,
    investigation_log: InvestigationLogDependency,
    after: int = 0,
) -> InvestigationResponse:
    """Ход расследования по прогону, начиная со следующего за `after` шага.

    Отдаётся кусками от курсора: лента дописывается, пока прогон идёт,
    и клиенту нужно то, что появилось с прошлого раза, а не вся трасса заново.
    """
    use_case = ReadInvestigation(unit_of_work, investigation_log)

    try:
        view = await use_case.execute(member.tenant_id, ReviewRunId(run_id), after=after)
    except EntityNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except PermissionDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    response.headers["Cache-Control"] = NO_STORE
    return InvestigationResponse.from_view(view)


@router.get("/repositories/{repository_id}/reviews", response_model=list[ReviewRunSummary])
async def list_reviews(
    repository_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    limit: int = 50,
) -> list[ReviewRunSummary]:
    use_case = ListReviewRuns(unit_of_work)
    runs = await use_case.execute(
        member.tenant_id,
        RepositoryId(repository_id),
        limit=limit,
    )
    return [ReviewRunSummary.from_domain(run) for run in runs]


@router.get("/repositories/{repository_id}/feedback", response_model=FeedbackDigestResponse)
async def get_feedback_digest(
    repository_id: UUID,
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    response: Response,
    runs_limit: int = 50,
) -> FeedbackDigestResponse:
    use_case = CollectFeedback(unit_of_work)
    view = await use_case.execute(
        member.tenant_id,
        RepositoryId(repository_id),
        runs_limit=runs_limit,
    )

    response.headers["Cache-Control"] = NO_STORE
    return FeedbackDigestResponse.from_view(view)
