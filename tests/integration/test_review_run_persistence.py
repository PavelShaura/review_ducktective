from datetime import (
    UTC,
    datetime,
)
from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import (
    VcsProvider,
)
from ducktective.core.diff.value_objects import (
    ChangeType,
    DiffSide,
)
from ducktective.core.review.dedup import (
    build_dedup_key,
)
from ducktective.core.review.entities import (
    Evidence,
    Finding,
    ReviewRun,
)
from ducktective.core.review.value_objects import (
    EvidenceKind,
    FindingCategory,
    FindingProducer,
    FindingStatus,
    ReviewSource,
    ReviewStatus,
    Severity,
)
from ducktective.core.types import (
    CommitSha,
    FindingId,
    RepositoryId,
    TenantId,
)
from ducktective.storage.models.tenancy import (
    TenantModel,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ducktective.vcs.diff_parser import (
    UnifiedDiffParser,
)
from tests.diff_fixtures import (
    MODIFIED_AND_ADDED_PATCH,
)


pytestmark = pytest.mark.integration


async def prepare_repository(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[TenantId, RepositoryId]:
    tenant_id = uuid4()
    async with session_factory() as session:
        session.add(
            TenantModel(
                id=tenant_id,
                slug=f"tenant-{tenant_id.hex[:8]}",
                name="Test tenant",
                settings={},
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    repository = CodeRepository.register(
        tenant_id=TenantId(tenant_id),
        name=f"repo-{tenant_id.hex[:8]}",
        vcs_provider=VcsProvider.LOCAL,
        local_path=Path("/repos/sample"),
    )
    async with SqlAlchemyUnitOfWork(
        session_factory,
        tenant_id=TenantId(tenant_id),
    ) as unit_of_work:
        unit_of_work.code_repositories.add(repository)
        await unit_of_work.commit()

    return TenantId(tenant_id), repository.id


def build_run(tenant_id: TenantId, repository_id: RepositoryId) -> ReviewRun:
    diff = UnifiedDiffParser().parse(
        MODIFIED_AND_ADDED_PATCH,
        base_sha=CommitSha("a" * 40),
        head_sha=CommitSha("b" * 40),
    )
    return ReviewRun.create(
        tenant_id=tenant_id,
        repository_id=repository_id,
        source=ReviewSource.LOCAL_DIFF,
        diff=diff,
    )


def build_finding() -> Finding:
    return Finding(
        id=FindingId(uuid4()),
        file_path="app/service.py",
        line_start=11,
        line_end=12,
        side=DiffSide.NEW,
        severity=Severity.MAJOR,
        category=FindingCategory.PERFORMANCE,
        title="Запрос в цикле",
        body_markdown="Вызов выполняется для каждой итерации",
        dedup_key=build_dedup_key(
            category=FindingCategory.PERFORMANCE,
            rule_id=None,
            symbol_name="ReportBuilder.build",
            file_path="app/service.py",
            code_fragment="result = self._compute()",
        ),
        producer=FindingProducer.LLM,
        producer_name="reviewer:performance",
        evidence=[
            Evidence(
                kind=EvidenceKind.QUOTED_CODE,
                file_path="app/service.py",
                snippet="result = self._compute()",
                line_start=11,
                line_end=11,
            )
        ],
    )


async def test_run_with_files_and_hunks_survives_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, repository_id = await prepare_repository(session_factory)
    run = build_run(tenant_id, repository_id)

    async with SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id) as unit_of_work:
        unit_of_work.review_runs.add(run)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id) as unit_of_work:
        stored = await unit_of_work.review_runs.get(run.id)

    assert stored.status is ReviewStatus.QUEUED
    assert [file.path for file in stored.files] == ["app/service.py", "app/helpers.py"]
    assert stored.files[0].change_type is ChangeType.MODIFIED
    assert stored.files[0].hunks[0].new_start == 10
    assert stored.files[0].hunks[0].patch_text.startswith("@@")


async def test_findings_and_status_are_persisted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, repository_id = await prepare_repository(session_factory)
    run = build_run(tenant_id, repository_id)

    async with SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id) as unit_of_work:
        unit_of_work.review_runs.add(run)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id) as unit_of_work:
        stored = await unit_of_work.review_runs.get(run.id)
        stored.mark_running()
        finding = build_finding()
        finding.verify()
        stored.add_finding(finding)
        stored.mark_completed()
        await unit_of_work.commit()
        events = unit_of_work.collect_events()

    async with SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id) as unit_of_work:
        reloaded = await unit_of_work.review_runs.get(run.id)

    assert len(events) == 3
    assert reloaded.status is ReviewStatus.COMPLETED
    assert reloaded.severity_totals == {"major": 1}
    assert len(reloaded.findings) == 1
    assert reloaded.findings[0].status is FindingStatus.VERIFIED
    assert reloaded.findings[0].evidence[0].snippet == "result = self._compute()"


async def test_duplicate_dedup_key_within_run_is_rejected_by_database(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, repository_id = await prepare_repository(session_factory)
    run = build_run(tenant_id, repository_id)
    first_finding = build_finding()
    second_finding = build_finding()
    second_finding.evidence.clear()

    async with SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id) as unit_of_work:
        unit_of_work.review_runs.add(run)
        run.findings.append(first_finding)
        run.findings.append(second_finding)

        with pytest.raises(Exception, match="uq_finding_run_id_dedup_key"):
            await unit_of_work.commit()


async def test_context_usage_survives_reload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Число файлов с контекстом должно переживать перезагрузку прогона."""
    tenant_id, repository_id = await prepare_repository(session_factory)
    run = build_run(tenant_id, repository_id)

    async with SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id) as unit_of_work:
        unit_of_work.review_runs.add(run)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id) as unit_of_work:
        stored = await unit_of_work.review_runs.get(run.id)
        stored.mark_running()
        stored.record_context_usage(2)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id) as unit_of_work:
        reloaded = await unit_of_work.review_runs.get(run.id)

    assert reloaded.files_with_context == 2
