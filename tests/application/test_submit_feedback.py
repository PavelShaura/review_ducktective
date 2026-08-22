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
from ducktective.application.review.submit_feedback import (
    SubmitFindingFeedback,
    SubmitFindingFeedbackCommand,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import VcsProvider as VcsProviderKind
from ducktective.core.diff.value_objects import (
    DiffSide,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.review.dedup import (
    build_dedup_key,
)
from ducktective.core.review.entities import (
    Evidence,
    Finding,
    ReviewRun,
)
from ducktective.core.review.events import (
    FindingFeedbackSubmitted,
)
from ducktective.core.review.value_objects import (
    EvidenceKind,
    FeedbackVerdict,
    FindingCategory,
    FindingProducer,
    FindingStatus,
    ReviewSource,
    Severity,
)
from ducktective.core.types import (
    CommitSha,
    FindingId,
    TenantId,
)
from ducktective.vcs.diff_parser import (
    UnifiedDiffParser,
)
from tests.diff_fixtures import (
    MODIFIED_AND_ADDED_PATCH,
)
from tests.fakes import (
    FakeEventPublisher,
    FakeUnitOfWork,
)


def build_finding() -> Finding:
    return Finding(
        id=FindingId(uuid4()),
        file_path="app/service.py",
        line_start=11,
        line_end=11,
        side=DiffSide.NEW,
        severity=Severity.MAJOR,
        category=FindingCategory.PERFORMANCE,
        title="Запрос в цикле",
        body_markdown="Вызов выполняется на каждой итерации",
        dedup_key=build_dedup_key(
            category=FindingCategory.PERFORMANCE,
            rule_id=None,
            symbol_name="ReportBuilder.build",
            file_path="app/service.py",
            code_fragment="result = self._compute()",
        ),
        producer=FindingProducer.LLM,
        producer_name="reviewer:single-pass",
        status=FindingStatus.VERIFIED,
    )


def prepare(unit_of_work: FakeUnitOfWork) -> tuple[TenantId, ReviewRun, Finding]:
    tenant_id = TenantId(uuid4())
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name="sandbox",
        vcs_provider=VcsProviderKind.LOCAL,
        local_path=Path("/repos/sandbox"),
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
    finding = build_finding()
    run.add_finding(finding)
    run.pull_events()
    unit_of_work.review_runs.add(run)
    return tenant_id, run, finding


async def submit(
    unit_of_work: FakeUnitOfWork,
    publisher: FakeEventPublisher,
    tenant_id: TenantId,
    run: ReviewRun,
    finding_id: FindingId,
    verdict: FeedbackVerdict,
) -> None:
    await SubmitFindingFeedback(unit_of_work, publisher).execute(
        SubmitFindingFeedbackCommand(
            tenant_id=tenant_id,
            run_id=run.id,
            finding_id=finding_id,
            verdict=verdict,
        )
    )


async def test_useful_feedback_is_recorded() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id, run, finding = prepare(unit_of_work)

    await submit(unit_of_work, publisher, tenant_id, run, finding.id, FeedbackVerdict.USEFUL)

    assert finding.latest_verdict is FeedbackVerdict.USEFUL
    assert finding.status is FindingStatus.VERIFIED
    assert unit_of_work.commit_calls == 1


async def test_false_positive_rejects_finding() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id, run, finding = prepare(unit_of_work)

    await submit(
        unit_of_work,
        publisher,
        tenant_id,
        run,
        finding.id,
        FeedbackVerdict.FALSE_POSITIVE,
    )

    assert finding.status is FindingStatus.REJECTED
    assert run.severity_totals == {}


async def test_feedback_event_is_published() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id, run, finding = prepare(unit_of_work)

    await submit(unit_of_work, publisher, tenant_id, run, finding.id, FeedbackVerdict.WONTFIX)

    assert any(isinstance(event, FindingFeedbackSubmitted) for event in publisher.published)


async def test_confirmation_returns_rejected_finding_to_work() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id, run, finding = prepare(unit_of_work)
    finding.evidence.append(
        Evidence(
            kind=EvidenceKind.QUOTED_CODE,
            file_path=finding.file_path,
            snippet="result = self._compute()",
        )
    )

    await submit(
        unit_of_work,
        publisher,
        tenant_id,
        run,
        finding.id,
        FeedbackVerdict.FALSE_POSITIVE,
    )
    status_after_rejection = finding.status
    assert status_after_rejection is FindingStatus.REJECTED

    await submit(unit_of_work, publisher, tenant_id, run, finding.id, FeedbackVerdict.USEFUL)

    assert finding.status is FindingStatus.VERIFIED
    assert run.severity_totals == {"major": 1}


async def test_postponing_also_clears_rejection() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id, run, finding = prepare(unit_of_work)

    await submit(
        unit_of_work,
        publisher,
        tenant_id,
        run,
        finding.id,
        FeedbackVerdict.FALSE_POSITIVE,
    )
    await submit(unit_of_work, publisher, tenant_id, run, finding.id, FeedbackVerdict.WONTFIX)

    assert finding.status is not FindingStatus.REJECTED


async def test_latest_verdict_wins() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id, run, finding = prepare(unit_of_work)

    await submit(
        unit_of_work,
        publisher,
        tenant_id,
        run,
        finding.id,
        FeedbackVerdict.FALSE_POSITIVE,
    )
    await submit(unit_of_work, publisher, tenant_id, run, finding.id, FeedbackVerdict.USEFUL)

    assert len(finding.feedback) == 2
    assert finding.latest_verdict is FeedbackVerdict.USEFUL


async def test_unknown_finding_is_reported() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id, run, _ = prepare(unit_of_work)

    with pytest.raises(EntityNotFoundError):
        await submit(
            unit_of_work,
            publisher,
            tenant_id,
            run,
            FindingId(uuid4()),
            FeedbackVerdict.USEFUL,
        )


async def test_foreign_tenant_is_rejected() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    _, run, finding = prepare(unit_of_work)

    with pytest.raises(PermissionDeniedError):
        await submit(
            unit_of_work,
            publisher,
            TenantId(uuid4()),
            run,
            finding.id,
            FeedbackVerdict.USEFUL,
        )
