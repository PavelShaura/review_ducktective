from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.review.run_review import (
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
from ducktective.core.review.drafts import (
    EvidenceDraft,
    FindingDraft,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.review.value_objects import (
    FindingCategory,
    FindingStatus,
    ReviewSource,
    ReviewStatus,
    Severity,
)
from ducktective.core.types import (
    CommitSha,
    TenantId,
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
        name="edussuz",
        vcs_provider=VcsProviderKind.LOCAL,
        local_path=Path("/repos/edussuz"),
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


async def review_with(
    unit_of_work: FakeUnitOfWork,
    tenant_id: TenantId,
    run: ReviewRun,
    reviewer: FakeCodeReviewer,
) -> ReviewOutcome:
    use_case = RunReview(unit_of_work, FakeEventPublisher(), reviewer)
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
