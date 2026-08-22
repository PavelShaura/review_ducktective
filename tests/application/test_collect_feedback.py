from datetime import (
    UTC,
    datetime,
    timedelta,
)
from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

from ducktective.application.review.read_feedback import (
    CollectFeedback,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import VcsProvider as VcsProviderKind
from ducktective.core.diff.value_objects import (
    DiffSide,
)
from ducktective.core.review.dedup import (
    build_dedup_key,
)
from ducktective.core.review.entities import (
    Finding,
    FindingFeedback,
    ReviewRun,
)
from ducktective.core.review.value_objects import (
    FeedbackVerdict,
    FindingCategory,
    FindingProducer,
    FindingStatus,
    ReviewSource,
    Severity,
)
from ducktective.core.types import (
    CommitSha,
    FindingFeedbackId,
    FindingId,
    RepositoryId,
    TenantId,
)
from ducktective.vcs.diff_parser import (
    UnifiedDiffParser,
)
from tests.diff_fixtures import (
    MODIFIED_AND_ADDED_PATCH,
)
from tests.fakes import (
    FakeUnitOfWork,
)


def build_finding(title: str, severity: Severity = Severity.MAJOR) -> Finding:
    return Finding(
        id=FindingId(uuid4()),
        file_path="app/service.py",
        line_start=11,
        line_end=11,
        side=DiffSide.NEW,
        severity=severity,
        category=FindingCategory.PERFORMANCE,
        title=title,
        body_markdown="Подробности",
        dedup_key=build_dedup_key(
            category=FindingCategory.PERFORMANCE,
            rule_id=None,
            symbol_name="ReportBuilder.build",
            file_path="app/service.py",
            code_fragment=title,
        ),
        producer=FindingProducer.LLM,
        producer_name="reviewer:single-pass",
        status=FindingStatus.VERIFIED,
    )


def build_run(tenant_id: TenantId, repository_id: RepositoryId) -> ReviewRun:
    diff = UnifiedDiffParser().parse(
        MODIFIED_AND_ADDED_PATCH,
        base_sha=CommitSha("a" * 40),
        head_sha=CommitSha("b" * 40),
    )
    run = ReviewRun.create(
        tenant_id=tenant_id,
        repository_id=repository_id,
        source=ReviewSource.LOCAL_DIFF,
        diff=diff,
    )
    run.pull_events()
    return run


def mark(finding: Finding, verdict: FeedbackVerdict, *, at: datetime) -> None:
    finding.feedback.append(
        FindingFeedback(
            id=FindingFeedbackId(uuid4()),
            verdict=verdict,
            created_at=at,
        )
    )


def prepare(unit_of_work: FakeUnitOfWork) -> tuple[TenantId, RepositoryId]:
    tenant_id = TenantId(uuid4())
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name="sandbox",
        vcs_provider=VcsProviderKind.LOCAL,
        local_path=Path("/repos/sandbox"),
    )
    unit_of_work.code_repositories.add(repository)
    return tenant_id, repository.id


async def test_marked_findings_are_collected_with_counts() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    run = build_run(tenant_id, repository_id)

    now = datetime.now(UTC)
    useful = build_finding("Запрос в цикле")
    false_positive = build_finding("Мнимая гонка", Severity.CRITICAL)
    untouched = build_finding("Никем не размечено", Severity.NITPICK)
    for finding in (useful, false_positive, untouched):
        run.add_finding(finding)

    mark(useful, FeedbackVerdict.USEFUL, at=now)
    mark(false_positive, FeedbackVerdict.FALSE_POSITIVE, at=now)
    unit_of_work.review_runs.add(run)

    digest = await CollectFeedback(unit_of_work).execute(tenant_id, repository_id)

    assert digest.marked_count == 2
    assert digest.total_findings == 3
    assert digest.counts == {"useful": 1, "false_positive": 1}
    assert digest.useful_share == 0.5


async def test_only_latest_mark_of_a_finding_is_taken() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    run = build_run(tenant_id, repository_id)

    finding = build_finding("Передумали")
    run.add_finding(finding)
    now = datetime.now(UTC)
    mark(finding, FeedbackVerdict.FALSE_POSITIVE, at=now - timedelta(hours=1))
    mark(finding, FeedbackVerdict.USEFUL, at=now)
    unit_of_work.review_runs.add(run)

    digest = await CollectFeedback(unit_of_work).execute(tenant_id, repository_id)

    assert digest.marked_count == 1
    assert digest.counts == {"useful": 1}
    assert digest.marked[0].verdict is FeedbackVerdict.USEFUL


async def test_marks_are_sorted_by_recency() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    run = build_run(tenant_id, repository_id)

    now = datetime.now(UTC)
    older = build_finding("Раньше")
    newer = build_finding("Позже")
    run.add_finding(older)
    run.add_finding(newer)
    mark(older, FeedbackVerdict.USEFUL, at=now - timedelta(days=1))
    mark(newer, FeedbackVerdict.WONTFIX, at=now)
    unit_of_work.review_runs.add(run)

    digest = await CollectFeedback(unit_of_work).execute(tenant_id, repository_id)

    assert [item.title for item in digest.marked] == ["Позже", "Раньше"]


async def test_runs_of_other_tenants_are_not_counted() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)

    foreign_run = build_run(TenantId(uuid4()), repository_id)
    foreign_finding = build_finding("Чужая находка")
    foreign_run.add_finding(foreign_finding)
    mark(foreign_finding, FeedbackVerdict.USEFUL, at=datetime.now(UTC))
    unit_of_work.review_runs.add(foreign_run)

    digest = await CollectFeedback(unit_of_work).execute(tenant_id, repository_id)

    assert digest.marked_count == 0
    assert digest.total_findings == 0


async def test_empty_repository_reports_no_share() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)

    digest = await CollectFeedback(unit_of_work).execute(tenant_id, repository_id)

    assert digest.marked == ()
    assert digest.useful_share is None
