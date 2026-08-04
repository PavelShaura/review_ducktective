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

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import VcsProvider as VcsProviderKind
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.review.value_objects import (
    ReviewSource,
)
from ducktective.core.types import (
    CommitSha,
    TenantId,
)
from ducktective.review_graph import (
    LangGraphReviewPipeline,
)
from ducktective.reviewer.worker import (
    run_review_task,
    shutdown,
)
from ducktective.vcs.diff_parser import (
    UnifiedDiffParser,
)
from tests.diff_fixtures import (
    MODIFIED_AND_ADDED_PATCH,
)
from tests.fakes import (
    FakeCodeReviewer,
    FakeUnitOfWork,
)


class UnitOfWorkFactory:
    """Возвращает один и тот же Unit of Work: воркер создаёт его на каждый вызов."""

    def __init__(self, unit_of_work: FakeUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def __call__(self, *args: Any, **kwargs: Any) -> FakeUnitOfWork:
        return self.unit_of_work


def build_context(
    unit_of_work: FakeUnitOfWork,
    reviewer: FakeCodeReviewer,
    monkeypatch: Any,
) -> dict[str, Any]:
    monkeypatch.setattr(
        "ducktective.reviewer.worker.SqlAlchemyUnitOfWork",
        UnitOfWorkFactory(unit_of_work),
    )
    monkeypatch.setattr(
        "ducktective.reviewer.worker.RedisEventPublisher",
        lambda redis_client: _NullPublisher(),
    )
    return {
        "session_factory": None,
        "redis": None,
        "pipeline": LangGraphReviewPipeline([reviewer]),
        "context_builder": None,
        "max_output_tokens": 4096,
    }


class _NullPublisher:
    async def publish(self, events: list[Any]) -> None:
        return None


def prepare(unit_of_work: FakeUnitOfWork) -> tuple[TenantId, ReviewRun]:
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
    unit_of_work.review_runs.add(run)
    return tenant_id, run


async def test_task_returns_summary(monkeypatch: Any) -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    context = build_context(unit_of_work, FakeCodeReviewer(), monkeypatch)

    result = await run_review_task(context, str(run.id), str(tenant_id))

    assert result["run_id"] == str(run.id)
    assert result["status"] == "completed"
    assert result["findings"] == 0


async def test_task_reports_domain_error_without_raising(monkeypatch: Any) -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    run.mark_running()
    context = build_context(unit_of_work, FakeCodeReviewer(), monkeypatch)

    result = await run_review_task(context, str(run.id), str(tenant_id))

    assert result["status"] == "failed"
    assert "error" in result


class FailingCloser:
    """Ресурс, чьё закрытие срывается."""

    async def aclose(self) -> None:
        raise RuntimeError("не закрылось")


class RecordingEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


async def test_shutdown_closes_the_database_even_if_something_else_fails() -> None:
    """Незакрытый пул переживает процесс и достаётся сборщику мусора.

    Тогда на выходе сыплются жалобы на невозвращённые в пул соединения,
    а причина — сбой закрытия чего-то другого, случившийся раньше.
    """
    engine = RecordingEngine()
    context: dict[str, Any] = {
        "resources": FailingCloser(),
        "redis": FailingCloser(),
        "engine": engine,
    }

    with pytest.raises(RuntimeError):
        await shutdown(context)

    assert engine.disposed is True
