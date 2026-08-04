from collections.abc import (
    Callable,
)
from uuid import (
    uuid4,
)

from langgraph.checkpoint.memory import (
    InMemorySaver,
)

from ducktective.core.diff.value_objects import (
    DiffSide,
)
from ducktective.core.exceptions import (
    LlmInvocationError,
)
from ducktective.core.llm.value_objects import (
    ModelRequirements,
)
from ducktective.core.retrieval.context import (
    ContextOrigin,
    ContextPiece,
    DiffContext,
)
from ducktective.core.review.degradation import (
    DegradationKind,
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
    PipelineRequest,
)
from ducktective.core.review.ports import (
    CancellationCheck,
    FileReviewResult,
)
from ducktective.core.review.value_objects import (
    FindingCategory,
    ReviewSource,
    Severity,
)
from ducktective.core.types import (
    CommitSha,
    RepositoryId,
    ReviewRunId,
    TenantId,
)
from ducktective.review_graph import (
    LangGraphReviewPipeline,
)
from ducktective.review_graph.checkpointing import (
    build_serializer,
)
from ducktective.vcs.diff_parser import (
    UnifiedDiffParser,
)
from tests.diff_fixtures import (
    MODIFIED_AND_ADDED_PATCH,
)
from tests.fakes import (
    FakeCodeReviewer,
)


SERVICE_FILE = "app/service.py"
HELPERS_FILE = "app/helpers.py"
CHANGED_LINE = 11
UNCHANGED_LINE = 500
QUOTED_LINE = "result = self._compute()"


def build_request() -> PipelineRequest:
    diff = UnifiedDiffParser().parse(
        MODIFIED_AND_ADDED_PATCH,
        base_sha=CommitSha("a" * 40),
        head_sha=CommitSha("b" * 40),
    )
    run = ReviewRun.create(
        tenant_id=TenantId(uuid4()),
        repository_id=RepositoryId(uuid4()),
        source=ReviewSource.LOCAL_DIFF,
        diff=diff,
    )
    return PipelineRequest(
        run_id=run.id,
        repository_id=run.repository_id,
        files=tuple(run.reviewable_files()),
        requirements=ModelRequirements(needs_deep_reasoning=True),
    )


def build_draft(
    *,
    line: int = CHANGED_LINE,
    snippet: str = QUOTED_LINE,
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


def named(reviewer: FakeCodeReviewer, name: str) -> FakeCodeReviewer:
    reviewer.name = name
    return reviewer


class FailingContextBuilder:
    async def build(self, repository_id: RepositoryId, file: ReviewFile) -> DiffContext:
        raise LlmInvocationError("индекс недоступен")


async def test_graph_produces_verified_findings() -> None:
    pipeline = LangGraphReviewPipeline([FakeCodeReviewer({SERVICE_FILE: [build_draft()]})])

    outcome = await pipeline.run(build_request())

    assert outcome.proposed == 1
    assert len(outcome.findings) == 1
    assert outcome.findings[0].producer_name == "reviewer:fake"


async def test_every_reviewer_sees_every_file() -> None:
    """Единица распараллеливания — пара «файл × ревьюер», а не файл."""
    first = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})
    second = named(
        FakeCodeReviewer({SERVICE_FILE: [build_draft(title="другой взгляд")]}),
        "reviewer:second",
    )
    pipeline = LangGraphReviewPipeline([first, second])

    outcome = await pipeline.run(build_request())

    assert sorted(first.reviewed_paths) == sorted(second.reviewed_paths)
    assert outcome.proposed == 2


async def test_specialised_reviewer_is_not_called_without_its_signals() -> None:
    """План — ограничитель стоимости: лишний проход стоит минуты (D-018)."""
    security = named(FakeCodeReviewer(), "reviewer:security")
    correctness = named(FakeCodeReviewer({SERVICE_FILE: [build_draft()]}), "reviewer:correctness")
    pipeline = LangGraphReviewPipeline([security, correctness])

    outcome = await pipeline.run(build_request())

    assert security.reviewed_paths == []
    assert sorted(correctness.reviewed_paths) == [HELPERS_FILE, SERVICE_FILE]
    assert len(outcome.findings) == 1


async def test_duplicate_keeps_the_draft_that_survives_verification() -> None:
    """Иначе черновик с выдуманной цитатой вытесняет достоверного двойника."""
    invented = named(
        FakeCodeReviewer({SERVICE_FILE: [build_draft(with_evidence=False, snippet="")]}),
        "reviewer:invented",
    )
    grounded = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})
    pipeline = LangGraphReviewPipeline([invented, grounded])

    outcome = await pipeline.run(build_request())

    assert len(outcome.findings) == 1
    assert outcome.findings[0].producer_name == "reviewer:fake"


async def test_displaced_draft_is_counted_by_its_own_defect() -> None:
    """Назвать дублем то, что и само не прошло бы проверку, значит спрятать причину."""
    reviewer = FakeCodeReviewer(
        {
            SERVICE_FILE: [
                build_draft(),
                build_draft(line=UNCHANGED_LINE, title="вне диффа"),
            ]
        }
    )
    pipeline = LangGraphReviewPipeline([reviewer])

    outcome = await pipeline.run(build_request())

    assert outcome.discarded_outside_diff == 1
    assert outcome.discarded_as_duplicate == 0
    assert len(outcome.findings) == 1


async def test_file_read_by_one_reviewer_is_not_counted_as_unreviewed() -> None:
    """Сбой случается на паре «файл × ревьюер», а отчитываются файлами."""
    failing = named(FakeCodeReviewer(failing_paths={SERVICE_FILE}), "reviewer:one")
    reading = named(FakeCodeReviewer({SERVICE_FILE: [build_draft()]}), "reviewer:two")
    pipeline = LangGraphReviewPipeline([failing, reading])

    outcome = await pipeline.run(build_request())

    assert outcome.unreviewed_files == ()
    assert outcome.reviewed_files == 2
    assert len(outcome.findings) == 1


async def test_same_failure_from_every_reviewer_is_reported_once() -> None:
    """Обрыв на лимите настигает всех четверых на одном и том же файле."""
    first = named(FakeCodeReviewer(failing_paths={SERVICE_FILE}), "reviewer:one")
    second = named(FakeCodeReviewer(failing_paths={SERVICE_FILE}), "reviewer:two")
    pipeline = LangGraphReviewPipeline([first, second])

    outcome = await pipeline.run(build_request())

    assert outcome.unreviewed_files == (SERVICE_FILE,)
    assert len(outcome.failed_files) == 1


async def test_failed_file_does_not_stop_the_others() -> None:
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()]}, failing_paths={HELPERS_FILE})
    pipeline = LangGraphReviewPipeline([reviewer])

    outcome = await pipeline.run(build_request())

    assert len(outcome.failed_files) == 1
    assert outcome.reviewed_files == 1
    assert len(outcome.findings) == 1


async def test_empty_diff_reaches_the_end_without_reviewers() -> None:
    """Ветвление без задач не должно упираться в узел без входящих данных."""
    pipeline = LangGraphReviewPipeline([FakeCodeReviewer()])

    outcome = await pipeline.run(
        PipelineRequest(
            run_id=ReviewRunId(uuid4()),
            repository_id=RepositoryId(uuid4()),
            files=(),
            requirements=ModelRequirements(),
        )
    )

    assert outcome.findings == ()
    assert outcome.proposed == 0
    assert outcome.reviewed_files == 0


async def test_cancellation_is_checked_before_the_model_is_asked() -> None:
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})
    pipeline = LangGraphReviewPipeline([reviewer])

    async def always_cancelled() -> bool:
        return True

    outcome = await pipeline.run(build_request(), cancellation=always_cancelled)

    assert outcome.is_cancelled is True
    assert reviewer.reviewed_paths == []


async def test_broken_index_leaves_the_run_without_context() -> None:
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})
    pipeline = LangGraphReviewPipeline([reviewer], context_builder=FailingContextBuilder())

    outcome = await pipeline.run(build_request())

    assert outcome.files_with_context == 0
    assert len(outcome.findings) == 1


async def test_failure_names_the_reviewer_and_the_file() -> None:
    """С четырьмя ревьюерами «часть файлов не прочитана» не говорит, кем."""
    failing = named(FakeCodeReviewer(failing_paths={SERVICE_FILE}), "reviewer:one")
    reading = named(FakeCodeReviewer({SERVICE_FILE: [build_draft()]}), "reviewer:two")
    pipeline = LangGraphReviewPipeline([failing, reading])

    outcome = await pipeline.run(build_request())

    marks = [mark for mark in outcome.degradations if mark.stage is ReviewStage.REVIEW]
    assert [(mark.reviewer, mark.file_path) for mark in marks] == [("reviewer:one", SERVICE_FILE)]
    assert marks[0].kind is DegradationKind.PROVIDER_UNAVAILABLE


async def test_broken_index_is_marked_by_the_node_that_broke() -> None:
    """Ревью по одному диффу — не то же самое, что ревью с окружением."""
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})
    pipeline = LangGraphReviewPipeline([reviewer], context_builder=FailingContextBuilder())

    outcome = await pipeline.run(build_request())

    stages = {mark.stage for mark in outcome.degradations}
    assert stages == {ReviewStage.BUILD_CONTEXT}
    assert all(mark.kind is DegradationKind.CONTEXT_UNAVAILABLE for mark in outcome.degradations)


async def test_run_without_an_index_is_not_a_degradation() -> None:
    """Отсутствие сборщика — заявленный режим работы, а не сбой."""
    pipeline = LangGraphReviewPipeline([FakeCodeReviewer({SERVICE_FILE: [build_draft()]})])

    outcome = await pipeline.run(build_request())

    assert outcome.degradations == ()


async def test_resumed_run_reads_only_what_was_left() -> None:
    """Ради этого чекпоинтер и заводился: прочитанное не читается второй раз."""
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()], HELPERS_FILE: []})
    pipeline = LangGraphReviewPipeline([reviewer], checkpointer=InMemorySaver())
    request = build_request()

    stopped = await pipeline.run(request, cancellation=read_at_least(reviewer, 1))

    assert stopped.is_cancelled is True
    assert len(reviewer.reviewed_paths) == 1

    continued = await pipeline.run(request, resume=True)

    assert continued.is_cancelled is False
    assert sorted(reviewer.reviewed_paths) == sorted([SERVICE_FILE, HELPERS_FILE])
    assert continued.reviewed_files == 2
    assert len(continued.findings) == 1


async def test_run_started_anew_forgets_what_it_had_read() -> None:
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})
    pipeline = LangGraphReviewPipeline([reviewer], checkpointer=InMemorySaver())
    request = build_request()

    await pipeline.run(request, cancellation=read_at_least(reviewer, 1))
    await pipeline.forget(request.run_id)
    await pipeline.run(request)

    assert reviewer.reviewed_paths.count(SERVICE_FILE) == 2


async def test_state_survives_the_serializer_that_stores_it() -> None:
    """Тип, забытый в перечне, теряется молча — и ровно при возобновлении."""
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})
    saver = InMemorySaver(serde=build_serializer())
    pipeline = LangGraphReviewPipeline([reviewer], checkpointer=saver)
    request = build_request()

    await pipeline.run(request, cancellation=read_at_least(reviewer, 1))
    outcome = await pipeline.run(request, resume=True)

    assert outcome.reviewed_files == 2
    assert len(outcome.findings) == 1


def cancel_when(condition: Callable[[], bool]) -> CancellationCheck:
    """Просит прекратить, когда наступило названное условие.

    Условие названо явно, а не счётчиком обращений: спрашивают об отмене
    и узел контекста, и узел ревьюера, и привязка к числу вопросов делает
    тест зависимым от того, кто спросил первым.
    """

    async def cancellation() -> bool:
        return condition()

    return cancellation


async def test_resume_without_saved_progress_starts_from_the_beginning() -> None:
    """Прогон живёт минуты до первого чекпоинта — столько собирается контекст."""
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})
    pipeline = LangGraphReviewPipeline([reviewer], checkpointer=InMemorySaver())

    outcome = await pipeline.run(build_request(), resume=True)

    assert outcome.reviewed_files == 2
    assert len(outcome.findings) == 1


async def test_cancellation_stops_the_context_node_too() -> None:
    """Иначе прекращённый прогон собирает окружение на весь дифф впустую."""
    builder = CountingContextBuilder()
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})
    pipeline = LangGraphReviewPipeline([reviewer], context_builder=builder)

    outcome = await pipeline.run(
        build_request(), cancellation=cancel_when(lambda: builder.calls >= 1)
    )

    assert outcome.is_cancelled is True
    assert builder.calls == 1
    assert reviewer.reviewed_paths == []


def read_at_least(reviewer: FakeCodeReviewer, files: int) -> CancellationCheck:
    return cancel_when(lambda: len(reviewer.reviewed_paths) >= files)


class CountingContextBuilder:
    def __init__(self) -> None:
        self.calls = 0

    async def build(self, repository_id: RepositoryId, file: ReviewFile) -> DiffContext:
        self.calls += 1
        return DiffContext(path=file.path)


async def test_run_cancelled_before_any_pair_resumes_from_the_context_node() -> None:
    """Прекращение на сборке окружения оставляет ход, из которого нечего брать."""
    builder = CountingContextBuilder()
    reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})
    pipeline = LangGraphReviewPipeline(
        [reviewer],
        context_builder=builder,
        checkpointer=InMemorySaver(serde=build_serializer()),
    )
    request = build_request()

    stopped = await pipeline.run(request, cancellation=cancel_when(lambda: builder.calls >= 1))

    assert stopped.is_cancelled is True
    assert reviewer.reviewed_paths == []

    continued = await pipeline.run(request, resume=True)

    assert continued.reviewed_files == 2
    assert len(continued.findings) == 1


HELPERS_LINE = "def compute_total(values):"


async def test_findings_of_earlier_attempts_reach_the_outcome() -> None:
    """Продолжение обязано отдать и то, что нашла прерванная попытка.

    Иначе прекращение молча стоило бы находок, а понять это можно было бы
    только сравнением с прогоном без остановок.
    """
    reviewer = FakeCodeReviewer(
        {
            SERVICE_FILE: [build_draft(title="из первой попытки")],
            HELPERS_FILE: [helpers_draft()],
        }
    )
    pipeline = LangGraphReviewPipeline(
        [reviewer],
        checkpointer=InMemorySaver(serde=build_serializer()),
    )
    request = build_request()

    await pipeline.run(request, cancellation=read_at_least(reviewer, 1))
    continued = await pipeline.run(request, resume=True)

    assert {finding.title for finding in continued.findings} == {
        "из первой попытки",
        "из второй попытки",
    }


def helpers_draft() -> FindingDraft:
    return FindingDraft(
        file_path=HELPERS_FILE,
        line_start=1,
        line_end=1,
        side=DiffSide.NEW,
        severity=Severity.MAJOR,
        category=FindingCategory.CORRECTNESS,
        title="из второй попытки",
        body_markdown="Сумма считается без проверки",
        anchor_symbol="compute_total",
        code_fragment=HELPERS_LINE,
        evidence=[EvidenceDraft(file_path=HELPERS_FILE, snippet=HELPERS_LINE)],
    )


async def test_interruption_does_not_change_what_the_model_is_asked() -> None:
    """Прекращение не должно стоить качества.

    При температуре 0 одинаковый вход даёт одинаковый выход, поэтому
    сравнивается именно вход: те же пары, тот же патч, то же окружение.
    Иначе разницу в находках пришлось бы объяснять догадками.
    """
    clean = RecordingReviewer({SERVICE_FILE: [build_draft()]})
    without_stops = await _pipeline_with(clean).run(build_request())

    interrupted = RecordingReviewer({SERVICE_FILE: [build_draft()]})
    pipeline = _pipeline_with(interrupted)
    request = build_request()
    await pipeline.run(request, cancellation=read_at_least(interrupted, 1))
    resumed = await pipeline.run(request, resume=True)

    assert sorted(interrupted.asked) == sorted(clean.asked)
    assert [finding.title for finding in resumed.findings] == [
        finding.title for finding in without_stops.findings
    ]


def _pipeline_with(reviewer: "RecordingReviewer") -> LangGraphReviewPipeline:
    return LangGraphReviewPipeline(
        [reviewer],
        context_builder=NeighbourContextBuilder(),
        checkpointer=InMemorySaver(serde=build_serializer()),
    )


class RecordingReviewer(FakeCodeReviewer):
    """Ревьюер, запоминающий, о чём его спросили."""

    def __init__(self, drafts_by_path: dict[str, list[FindingDraft]] | None = None) -> None:
        super().__init__(drafts_by_path)
        self.asked: list[tuple[str, str, str, tuple[ContextPiece, ...]]] = []

    async def review_file(
        self,
        file: ReviewFile,
        *,
        patch_text: str,
        requirements: ModelRequirements,
        context: DiffContext | None = None,
    ) -> FileReviewResult:
        self.asked.append(
            (file.path, self.name, patch_text, () if context is None else context.pieces)
        )
        return await super().review_file(
            file,
            patch_text=patch_text,
            requirements=requirements,
            context=context,
        )


class NeighbourContextBuilder:
    async def build(self, repository_id: RepositoryId, file: ReviewFile) -> DiffContext:
        return DiffContext(
            path=file.path,
            token_budget=2000,
            pieces=(
                ContextPiece(
                    origin=ContextOrigin.CALLER,
                    path="app/caller.py",
                    qualified_name=None,
                    start_line=1,
                    end_line=3,
                    text=f"# вызывающий для {file.path}",
                    token_count=10,
                ),
            ),
        )
