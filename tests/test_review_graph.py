from uuid import (
    uuid4,
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
    DiffContext,
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
from ducktective.core.review.value_objects import (
    FindingCategory,
    ReviewSource,
    Severity,
)
from ducktective.core.types import (
    CommitSha,
    RepositoryId,
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
