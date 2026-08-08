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
from ducktective.application.review.read_investigation import (
    ReadInvestigation,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import (
    VcsProvider,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.review.investigation import (
    InvestigationStep,
    RecordedStep,
    StepKind,
)
from ducktective.core.review.value_objects import (
    ReviewSource,
)
from ducktective.core.types import (
    ReviewRunId,
    TenantId,
)
from ducktective.storage.investigation import (
    RecordingInvestigationSink,
    RecordingInvestigationSinks,
)
from ducktective.vcs.diff_parser import (
    UnifiedDiffParser,
)
from tests.diff_fixtures import (
    MODIFIED_AND_ADDED_PATCH,
)
from tests.fakes import (
    FakeInvestigationLog,
    FakeUnitOfWork,
)


TENANT_ID = TenantId(uuid4())
OTHER_TENANT_ID = TenantId(uuid4())


def build_step(number: int = 1, kind: StepKind = StepKind.TOOL_CALL) -> InvestigationStep:
    return InvestigationStep(
        file_path="app/service.py",
        number=number,
        kind=kind,
        tool_name="find_callers",
        arguments='{"name": "build"}',
        detail="Источник: индекс проекта",
    )


async def stored_run(unit_of_work: FakeUnitOfWork, *, tenant_id: TenantId = TENANT_ID) -> ReviewRun:
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name="ducktective",
        vcs_provider=VcsProvider.LOCAL,
        local_path=Path("/repos/ducktective"),
    )
    unit_of_work.code_repositories.add(repository)

    diff = UnifiedDiffParser().parse(
        MODIFIED_AND_ADDED_PATCH,
        base_sha="a" * 40,  # type: ignore[arg-type]
        head_sha="b" * 40,  # type: ignore[arg-type]
    )
    run = ReviewRun.create(
        tenant_id=tenant_id,
        repository_id=repository.id,
        source=ReviewSource.LOCAL_DIFF,
        diff=diff,
    )
    unit_of_work.review_runs.add(run)
    return run


async def test_sink_writes_the_step_under_the_name_of_its_run() -> None:
    """Прогон подставляет слушатель: ревьюер читает файл, а не ведёт дело."""
    log = FakeInvestigationLog()
    run_id = ReviewRunId(uuid4())

    await RecordingInvestigationSinks(log).for_run(run_id).record(build_step())

    assert [entry[0] for entry in log.appended] == [run_id]


async def test_broken_log_does_not_interrupt_the_review() -> None:
    """Лента — способ смотреть за работой, а не сама работа."""

    class FailingLog(FakeInvestigationLog):
        async def append(self, run_id: ReviewRunId, step: InvestigationStep) -> RecordedStep:
            raise RuntimeError("база недоступна")

    sink = RecordingInvestigationSink(FailingLog(), ReviewRunId(uuid4()))

    await sink.record(build_step())


async def test_broken_broadcast_does_not_interrupt_the_review() -> None:
    class FailingBroadcaster:
        async def publish(self, run_id: ReviewRunId, recorded: RecordedStep) -> None:
            raise RuntimeError("redis недоступен")

    log = FakeInvestigationLog()
    sink = RecordingInvestigationSink(
        log,
        ReviewRunId(uuid4()),
        broadcaster=FailingBroadcaster(),
    )

    await sink.record(build_step())

    assert len(log.appended) == 1


async def test_investigation_is_read_from_the_cursor() -> None:
    unit_of_work = FakeUnitOfWork()
    run = await stored_run(unit_of_work)
    log = FakeInvestigationLog()
    for number in (1, 2, 3):
        await log.append(run.id, build_step(number))

    view = await ReadInvestigation(unit_of_work, log).execute(TENANT_ID, run.id, after=1)

    assert [step.number for step in view.steps] == [2, 3]
    assert view.next_cursor == 3


async def test_empty_tail_keeps_the_cursor() -> None:
    """Иначе клиент, догнавший конец ленты, прочитал бы её сначала."""
    unit_of_work = FakeUnitOfWork()
    run = await stored_run(unit_of_work)
    log = FakeInvestigationLog()
    await log.append(run.id, build_step())

    view = await ReadInvestigation(unit_of_work, log).execute(TENANT_ID, run.id, after=1)

    assert view.steps == ()
    assert view.next_cursor == 1


async def test_investigation_of_a_foreign_run_is_denied() -> None:
    unit_of_work = FakeUnitOfWork()
    run = await stored_run(unit_of_work, tenant_id=OTHER_TENANT_ID)
    log = FakeInvestigationLog()
    await log.append(run.id, build_step())

    with pytest.raises(PermissionDeniedError):
        await ReadInvestigation(unit_of_work, log).execute(TENANT_ID, run.id)
