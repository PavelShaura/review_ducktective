from datetime import (
    timedelta,
)
from pathlib import (
    Path,
)
from typing import (
    Any,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.review.cancel_run import (
    CancelReviewRun,
)
from ducktective.application.review.restart_run import (
    RestartReviewRun,
    RunNotRestartableError,
)
from ducktective.application.review.resume_run import (
    ResumeReviewRun,
    RunNotResumableError,
)
from ducktective.application.review.run_review import (
    ReviewCancelledError,
    ReviewOutcome,
    RunNotReviewableError,
    RunReview,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import (
    EgressPolicy,
)
from ducktective.core.code_repository.value_objects import VcsProvider as VcsProviderKind
from ducktective.core.diff.value_objects import (
    DiffSide,
)
from ducktective.core.exceptions import (
    VcsOperationError,
)
from ducktective.core.indexing.entities import (
    IndexSnapshot,
)
from ducktective.core.indexing.value_objects import (
    SnapshotStatus,
)
from ducktective.core.retrieval.context import (
    ContextOrigin,
    ContextPiece,
    DiffContext,
)
from ducktective.core.retrieval.ports import (
    ContextBuilder,
)
from ducktective.core.review.degradation import (
    ReviewStage,
)
from ducktective.core.review.drafts import (
    EvidenceDraft,
    FindingDraft,
)
from ducktective.core.review.entities import (
    ReviewFile,
    ReviewRun,
)
from ducktective.core.review.pipeline import (
    PipelineOutcome,
    PipelineRequest,
)
from ducktective.core.review.ports import (
    CancellationCheck,
)
from ducktective.core.review.value_objects import (
    EvidenceKind,
    FindingCategory,
    FindingStatus,
    ReviewSource,
    ReviewStatus,
    Severity,
)
from ducktective.core.types import (
    CommitSha,
    QualifiedName,
    RepositoryId,
    ReviewRunId,
    TenantId,
)
from ducktective.review_graph import (
    LangGraphReviewPipeline,
)
from ducktective.vcs.diff_parser import (
    UnifiedDiffParser,
)
from tests.diff_fixtures import (
    MODIFIED_AND_ADDED_PATCH,
)
from tests.fakes import (
    FakeCodeReviewer,
    FakeEventPublisher,
    FakeUnitOfWork,
)


SERVICE_FILE = "app/service.py"
CHANGED_LINE = 11
UNCHANGED_LINE = 500


def prepare(
    unit_of_work: FakeUnitOfWork,
    *,
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY,
) -> tuple[TenantId, ReviewRun]:
    tenant_id = TenantId(uuid4())
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name="sandbox",
        vcs_provider=VcsProviderKind.LOCAL,
        local_path=Path("/repos/sandbox"),
        egress_policy=egress_policy,
    )
    unit_of_work.code_repositories.add(repository)

    diff = UnifiedDiffParser().parse(
        MODIFIED_AND_ADDED_PATCH,
        base_sha=CommitSha("a" * 40),
        head_sha=CommitSha("b" * 40),
    )
    run = ReviewRun.create(
        tenant_id=tenant_id,
        repository_id=repository.id,
        source=ReviewSource.LOCAL_DIFF,
        diff=diff,
    )
    unit_of_work.review_runs.add(run)
    return tenant_id, run


def build_draft(
    *,
    line: int = CHANGED_LINE,
    snippet: str = "result = self._compute()",
    with_evidence: bool = True,
    title: str = "Запрос в цикле",
) -> FindingDraft:
    return FindingDraft(
        file_path=SERVICE_FILE,
        line_start=line,
        line_end=line,
        side=DiffSide.NEW,
        severity=Severity.MAJOR,
        category=FindingCategory.PERFORMANCE,
        title=title,
        body_markdown="Вызов выполняется на каждой итерации",
        anchor_symbol="ReportBuilder.build",
        code_fragment=snippet,
        evidence=[EvidenceDraft(file_path=SERVICE_FILE, snippet=snippet)] if with_evidence else [],
    )


async def run_with(
    unit_of_work: FakeUnitOfWork,
    tenant_id: TenantId,
    run: ReviewRun,
    reviewer: FakeCodeReviewer,
) -> ReviewRun:
    return (await review_with(unit_of_work, tenant_id, run, reviewer)).run


def pipeline_for(
    reviewer: FakeCodeReviewer,
    context_builder: ContextBuilder | None = None,
) -> LangGraphReviewPipeline:
    return LangGraphReviewPipeline([reviewer], context_builder=context_builder)


async def review_with(
    unit_of_work: FakeUnitOfWork,
    tenant_id: TenantId,
    run: ReviewRun,
    reviewer: FakeCodeReviewer,
) -> ReviewOutcome:
    use_case = RunReview(unit_of_work, FakeEventPublisher(), pipeline_for(reviewer))
    return await use_case.execute(tenant_id, run.id)


async def test_findings_are_recorded_and_run_completed() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})

    result = await run_with(unit_of_work, tenant_id, run, reviewer)

    assert result.status is ReviewStatus.COMPLETED
    assert len(result.findings) == 1
    assert result.findings[0].status is FindingStatus.VERIFIED
    assert result.severity_totals == {"major": 1}


async def test_usage_is_accumulated() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})

    result = await run_with(unit_of_work, tenant_id, run, reviewer)

    assert result.tokens_input == 200
    assert result.tokens_output == 50


async def test_finding_outside_diff_is_discarded() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft(line=UNCHANGED_LINE)]})

    outcome = await review_with(unit_of_work, tenant_id, run, reviewer)

    assert outcome.run.findings == []
    assert outcome.proposed == 1
    assert outcome.discarded_outside_diff == 1


async def test_outcome_counts_discarded_by_reason() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer(
        {
            SERVICE_FILE: [
                build_draft(),
                build_draft(title="повтор"),
                build_draft(line=UNCHANGED_LINE, title="вне диффа"),
                build_draft(snippet="session.query(Model).all()", title="выдумка"),
            ]
        }
    )

    outcome = await review_with(unit_of_work, tenant_id, run, reviewer)

    assert outcome.proposed == 4
    assert len(outcome.run.findings) == 1
    assert outcome.discarded_outside_diff == 1
    assert outcome.discarded_without_evidence == 1
    assert outcome.discarded_as_duplicate == 1
    assert outcome.discarded == 3


async def test_finding_with_invented_quote_is_discarded() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft(snippet="session.query(Model).all()")]})

    result = await run_with(unit_of_work, tenant_id, run, reviewer)

    assert result.findings == []


async def test_finding_without_any_evidence_is_discarded() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    draft = build_draft(with_evidence=False, snippet="")
    reviewer = FakeCodeReviewer({SERVICE_FILE: [draft]})

    result = await run_with(unit_of_work, tenant_id, run, reviewer)

    assert result.findings == []


async def test_duplicate_drafts_collapse_into_one_finding() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer(
        {SERVICE_FILE: [build_draft(), build_draft(title="Другая формулировка")]}
    )

    result = await run_with(unit_of_work, tenant_id, run, reviewer)

    assert len(result.findings) == 1


async def test_local_only_policy_forbids_cloud() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work, egress_policy=EgressPolicy.LOCAL_ONLY)
    reviewer = FakeCodeReviewer()

    await run_with(unit_of_work, tenant_id, run, reviewer)

    assert reviewer.reviewed_paths == [SERVICE_FILE, "app/helpers.py"]


async def test_output_limit_from_settings_reaches_the_model() -> None:
    """Место под ответ вычитается из окна модели, поэтому лимит настраивается."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer()

    use_case = RunReview(
        unit_of_work,
        FakeEventPublisher(),
        pipeline_for(reviewer),
        max_output_tokens=1800,
    )
    await use_case.execute(tenant_id, run.id)

    assert {item.max_output_tokens for item in reviewer.seen_requirements} == {1800}


async def test_failed_file_does_not_break_run() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer(
        {SERVICE_FILE: [build_draft()]},
        failing_paths={"app/helpers.py"},
    )

    result = await run_with(unit_of_work, tenant_id, run, reviewer)

    assert result.status is ReviewStatus.COMPLETED
    assert len(result.findings) == 1


async def test_partial_failure_is_visible_on_completed_run() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer(
        {SERVICE_FILE: [build_draft()]},
        failing_paths={"app/helpers.py"},
    )

    result = await run_with(unit_of_work, tenant_id, run, reviewer)

    assert result.status is ReviewStatus.COMPLETED
    assert result.failure_reason is not None
    assert "app/helpers.py" in result.failure_reason
    assert "1 из 2" in result.failure_reason
    assert result.failure_reason.count("\n") == 1


async def test_partial_failure_names_the_node_on_the_run() -> None:
    """Общая фраза не говорит, кто упал, — разбирательство начинается с этого."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer(
        {SERVICE_FILE: [build_draft()]},
        failing_paths={"app/helpers.py"},
    )

    result = await run_with(unit_of_work, tenant_id, run, reviewer)

    assert [(mark.stage, mark.file_path, mark.reviewer) for mark in result.degradations] == [
        (ReviewStage.REVIEW, "app/helpers.py", "reviewer:fake")
    ]


async def test_restart_forgets_the_marks_of_the_previous_attempt() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer(failing_paths={SERVICE_FILE, "app/helpers.py"})

    result = await run_with(unit_of_work, tenant_id, run, reviewer)
    result.restart()

    assert result.degradations == []


async def test_run_fails_when_every_file_fails() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer(failing_paths={SERVICE_FILE, "app/helpers.py"})

    result = await run_with(unit_of_work, tenant_id, run, reviewer)

    assert result.status is ReviewStatus.FAILED
    assert result.failure_reason is not None


async def test_already_running_run_is_rejected() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    run.mark_running()

    with pytest.raises(RunNotReviewableError):
        await run_with(unit_of_work, tenant_id, run, FakeCodeReviewer())


async def test_foreign_tenant_is_rejected() -> None:
    unit_of_work = FakeUnitOfWork()
    _, run = prepare(unit_of_work)

    with pytest.raises(PermissionDeniedError):
        await run_with(unit_of_work, TenantId(uuid4()), run, FakeCodeReviewer())


def context_with(text: str, path: str = "app/caller.py") -> DiffContext:
    return DiffContext(
        path="app/service.py",
        pieces=(
            ContextPiece(
                origin=ContextOrigin.CALLER,
                path=path,
                qualified_name=QualifiedName("app.caller.handler"),
                start_line=10,
                end_line=20,
                text=text,
                token_count=10,
            ),
        ),
        token_budget=1000,
    )


class FakeContextBuilder:
    def __init__(self, context: DiffContext | None = None, *, failing: bool = False) -> None:
        self.context = context
        self.failing = failing
        self.calls = 0

    async def build(self, repository_id: RepositoryId, file: ReviewFile) -> DiffContext:
        self.calls += 1
        if self.failing:
            raise VcsOperationError("индекс недоступен")
        return self.context or DiffContext(path=file.path)


async def test_context_reaches_the_reviewer() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer()
    builder = FakeContextBuilder(context_with("def handler(): ..."))

    await RunReview(unit_of_work, FakeEventPublisher(), pipeline_for(reviewer, builder)).execute(
        tenant_id,
        run.id,
    )

    assert builder.calls == len(reviewer.reviewed_paths)
    assert all(context is not None for context in reviewer.seen_contexts)


async def test_quote_from_context_confirms_a_finding() -> None:
    """Ссылка на вызывающий код — самое ценное, что модель может сказать."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    caller_line = "result = service.compute(value)"
    draft = build_draft(snippet=caller_line)
    reviewer = FakeCodeReviewer({"app/service.py": [draft]})

    outcome = await RunReview(
        unit_of_work,
        FakeEventPublisher(),
        pipeline_for(reviewer, FakeContextBuilder(context_with(caller_line))),
    ).execute(tenant_id, run.id)

    assert outcome.discarded_without_evidence == 0
    assert outcome.run.findings
    assert outcome.run.findings[0].evidence[0].kind is EvidenceKind.RETRIEVED_CHUNK


async def test_quote_from_nowhere_is_still_discarded() -> None:
    """Контекст расширяет круг допустимых цитат, но не отменяет проверку."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    draft = build_draft(snippet="никогда не существовавшая строка")
    reviewer = FakeCodeReviewer({"app/service.py": [draft]})

    outcome = await RunReview(
        unit_of_work,
        FakeEventPublisher(),
        pipeline_for(reviewer, FakeContextBuilder(context_with("совсем другой код"))),
    ).execute(tenant_id, run.id)

    assert outcome.discarded_without_evidence == 1
    assert outcome.run.findings == []


async def test_broken_index_does_not_stop_the_run() -> None:
    """Ревью без контекста хуже, но лучше, чем отсутствие ревью."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer()

    outcome = await RunReview(
        unit_of_work,
        FakeEventPublisher(),
        pipeline_for(reviewer, FakeContextBuilder(failing=True)),
    ).execute(tenant_id, run.id)

    assert outcome.run.status is ReviewStatus.COMPLETED
    assert outcome.files_with_context == 0
    assert reviewer.reviewed_paths


async def test_run_without_builder_works_as_before() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer()

    outcome = await RunReview(unit_of_work, FakeEventPublisher(), pipeline_for(reviewer)).execute(
        tenant_id,
        run.id,
    )

    assert outcome.files_with_context == 0
    assert reviewer.seen_contexts == [None] * len(reviewer.reviewed_paths)


async def test_context_usage_is_stored_on_the_run() -> None:
    """По завершённому прогону должно быть видно, участвовал ли индекс."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer()

    outcome = await RunReview(
        unit_of_work,
        FakeEventPublisher(),
        pipeline_for(reviewer, FakeContextBuilder(context_with("def handler(): ..."))),
    ).execute(tenant_id, run.id)

    assert outcome.run.files_with_context == len(reviewer.reviewed_paths)


async def test_empty_context_does_not_count_as_used() -> None:
    """Собранный, но пустой контекст — это ревью без окружения."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)

    outcome = await RunReview(
        unit_of_work,
        FakeEventPublisher(),
        pipeline_for(FakeCodeReviewer(), FakeContextBuilder()),
    ).execute(tenant_id, run.id)

    assert outcome.run.files_with_context == 0


class CancellingReviewer(FakeCodeReviewer):
    """Ревьюер, который отменяет прогон, дочитав первый файл."""

    def __init__(self, run: ReviewRun, drafts: dict[str, list[FindingDraft]]) -> None:
        super().__init__(drafts)
        self._run = run

    async def review_file(self, *args: Any, **kwargs: Any) -> Any:
        result = await super().review_file(*args, **kwargs)
        self._run.cancel()
        return result


async def test_cancelling_between_files_saves_nothing() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = CancellingReviewer(run, {SERVICE_FILE: [build_draft()]})

    with pytest.raises(ReviewCancelledError):
        await review_with(unit_of_work, tenant_id, run, reviewer)

    assert run.findings == []
    assert run.status is ReviewStatus.CANCELLED
    assert reviewer.reviewed_paths == [SERVICE_FILE]


async def test_queued_run_can_be_cancelled() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)

    cancelled = await CancelReviewRun(unit_of_work, FakeEventPublisher()).execute(
        tenant_id,
        run.id,
    )

    assert cancelled is True
    assert run.status is ReviewStatus.CANCELLED


async def test_cancelling_a_run_cancels_the_index_build_it_queued() -> None:
    """Сборка на ревизии дела ставится запуском; без дела она только занимает воркер."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    queued = IndexSnapshot.create(repository_id=run.repository_id, commit_sha=run.head_sha)
    unit_of_work.index_snapshots.add(queued)

    await CancelReviewRun(unit_of_work, FakeEventPublisher()).execute(tenant_id, run.id)

    assert queued.status is SnapshotStatus.CANCELLED


async def test_cancelling_a_run_leaves_a_build_of_another_revision_alone() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    other = IndexSnapshot.create(repository_id=run.repository_id, commit_sha=CommitSha("c" * 40))
    unit_of_work.index_snapshots.add(other)

    await CancelReviewRun(unit_of_work, FakeEventPublisher()).execute(tenant_id, run.id)

    assert other.status is SnapshotStatus.PENDING


async def test_cancelling_finished_run_changes_nothing() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})
    await run_with(unit_of_work, tenant_id, run, reviewer)

    cancelled = await CancelReviewRun(unit_of_work, FakeEventPublisher()).execute(
        tenant_id,
        run.id,
    )

    assert cancelled is False
    assert run.status is ReviewStatus.COMPLETED


async def test_cancelled_run_can_be_restarted() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = CancellingReviewer(run, {SERVICE_FILE: [build_draft()]})
    with pytest.raises(ReviewCancelledError):
        await review_with(unit_of_work, tenant_id, run, reviewer)

    await RestartReviewRun(unit_of_work, FakeEventPublisher()).execute(tenant_id, run.id)

    assert run.status is ReviewStatus.QUEUED
    assert run.finished_at is None
    assert run.files


async def test_restarted_run_reviews_from_scratch() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    cancelling = CancellingReviewer(run, {SERVICE_FILE: [build_draft()]})
    with pytest.raises(ReviewCancelledError):
        await review_with(unit_of_work, tenant_id, run, cancelling)
    await RestartReviewRun(unit_of_work, FakeEventPublisher()).execute(tenant_id, run.id)

    result = await run_with(
        unit_of_work, tenant_id, run, FakeCodeReviewer({SERVICE_FILE: [build_draft()]})
    )

    assert result.status is ReviewStatus.COMPLETED
    assert len(result.findings) == 1
    assert result.tokens_input == 200


async def test_completed_run_is_not_restartable() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    await run_with(unit_of_work, tenant_id, run, FakeCodeReviewer({SERVICE_FILE: [build_draft()]}))

    with pytest.raises(RunNotRestartableError):
        await RestartReviewRun(unit_of_work, FakeEventPublisher()).execute(tenant_id, run.id)


async def test_run_from_scratch_forgets_the_previous_attempt() -> None:
    """Иначе «расследовать заново» вернуло бы ровно то, от чего уходили."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    pipeline = RecordingPipeline()
    use_case = RunReview(unit_of_work, FakeEventPublisher(), pipeline)

    await use_case.execute(tenant_id, run.id)

    assert pipeline.forgotten == [run.id, run.id]
    assert pipeline.resumed == [False]


async def test_resumed_run_keeps_what_it_had_read() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    pipeline = RecordingPipeline()
    use_case = RunReview(unit_of_work, FakeEventPublisher(), pipeline)

    await use_case.execute(tenant_id, run.id, resume=True)

    assert pipeline.resumed == [True]
    assert pipeline.forgotten == [run.id]


async def test_failed_run_remembers_its_progress() -> None:
    """Упавший прогон продолжают, а не начинают заново, — забывать его рано."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    pipeline = RecordingPipeline(outcome=PipelineOutcome(failed_files=("app/service.py: нет",)))
    use_case = RunReview(unit_of_work, FakeEventPublisher(), pipeline)

    await use_case.execute(tenant_id, run.id, resume=True)

    assert run.status is ReviewStatus.FAILED
    assert pipeline.forgotten == []


async def test_cancelled_run_can_be_resumed() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    reviewer = CancellingReviewer(run, {SERVICE_FILE: [build_draft()]})
    with pytest.raises(ReviewCancelledError):
        await review_with(unit_of_work, tenant_id, run, reviewer)

    await ResumeReviewRun(unit_of_work, FakeEventPublisher()).execute(tenant_id, run.id)

    assert run.status is ReviewStatus.QUEUED
    assert run.tokens_input == 0


async def test_completed_run_is_not_resumable() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    await run_with(unit_of_work, tenant_id, run, FakeCodeReviewer({SERVICE_FILE: [build_draft()]}))

    with pytest.raises(RunNotResumableError):
        await ResumeReviewRun(unit_of_work, FakeEventPublisher()).execute(tenant_id, run.id)


class RecordingPipeline:
    """Конвейер, запоминающий, что ему велели помнить и что забыть."""

    def __init__(self, *, outcome: PipelineOutcome | None = None) -> None:
        self.outcome = outcome or PipelineOutcome(reviewed_files=1)
        self.resumed: list[bool] = []
        self.forgotten: list[ReviewRunId] = []
        self.cancellations: list[CancellationCheck] = []

    async def run(
        self,
        request: PipelineRequest,
        *,
        cancellation: CancellationCheck | None = None,
        resume: bool = False,
    ) -> PipelineOutcome:
        self.resumed.append(resume)
        if cancellation is not None:
            self.cancellations.append(cancellation)
        return self.outcome

    async def forget(self, run_id: ReviewRunId) -> None:
        self.forgotten.append(run_id)


async def test_previous_attempt_stops_when_the_run_is_resumed() -> None:
    """Продолжение стирает признак отмены — прежняя попытка узнаёт себя иначе."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    pipeline = RecordingPipeline(outcome=PipelineOutcome(failed_files=("app/service.py: нет",)))
    use_case = RunReview(unit_of_work, FakeEventPublisher(), pipeline)

    await use_case.execute(tenant_id, run.id)
    stop = pipeline.cancellations[0]

    assert await stop() is False

    run.restart()

    assert run.is_cancelled is False
    assert await stop() is True


async def test_attempt_grows_with_every_return_to_the_queue() -> None:
    unit_of_work = FakeUnitOfWork()
    _, run = prepare(unit_of_work)

    assert run.attempt == 1

    run.cancel()
    run.restart()
    run.mark_running()
    run.cancel()
    run.restart()

    assert run.attempt == 3


def spend(run: ReviewRun, seconds: int) -> None:
    """Отматывает начало попытки назад: иначе она длится меньше миллисекунды."""
    run.mark_running()
    assert run.started_at is not None
    run.started_at -= timedelta(seconds=seconds)


async def test_resumed_run_keeps_the_time_it_had_already_spent() -> None:
    """Человек спрашивает, сколько идёт дело, а не сколько идёт последний заход."""
    unit_of_work = FakeUnitOfWork()
    _, run = prepare(unit_of_work)

    spend(run, 30)
    run.cancel()
    run.resume()

    assert run.duration_ms >= 30_000
    assert run.started_at is None


async def test_run_started_anew_forgets_the_time_it_had_spent() -> None:
    """Прежняя работа выброшена вместе с ходом — её цена уходит с ней."""
    unit_of_work = FakeUnitOfWork()
    _, run = prepare(unit_of_work)

    spend(run, 30)
    run.cancel()
    run.restart()

    assert run.duration_ms == 0


async def test_duration_adds_up_across_attempts() -> None:
    unit_of_work = FakeUnitOfWork()
    _, run = prepare(unit_of_work)

    spend(run, 30)
    run.cancel()
    run.resume()
    spend(run, 12)
    run.mark_completed()

    assert run.duration_ms >= 42_000
    assert run.attempt == 2
