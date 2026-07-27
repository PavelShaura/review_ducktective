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
from ducktective.application.review.delete_run import (
    DeleteReviewRun,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import VcsProvider as VcsProviderKind
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.review.events import (
    ReviewRunDeleted,
)
from ducktective.core.review.value_objects import (
    ReviewSource,
)
from ducktective.core.types import (
    CommitSha,
    ReviewRunId,
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


def prepare(unit_of_work: FakeUnitOfWork) -> tuple[TenantId, ReviewRun]:
    tenant_id = TenantId(uuid4())
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name="edussuz",
        vcs_provider=VcsProviderKind.LOCAL,
        local_path=Path("/repos/edussuz"),
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
    run.pull_events()
    unit_of_work.review_runs.add(run)
    return tenant_id, run


async def test_run_is_removed() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id, run = prepare(unit_of_work)

    await DeleteReviewRun(unit_of_work, publisher).execute(tenant_id, run.id)

    assert unit_of_work.review_runs.stored == {}
    assert unit_of_work.commit_calls == 1


async def test_deletion_event_is_published() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id, run = prepare(unit_of_work)

    await DeleteReviewRun(unit_of_work, publisher).execute(tenant_id, run.id)

    assert any(isinstance(event, ReviewRunDeleted) for event in publisher.published)


async def test_foreign_tenant_cannot_delete() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    _, run = prepare(unit_of_work)

    with pytest.raises(PermissionDeniedError):
        await DeleteReviewRun(unit_of_work, publisher).execute(TenantId(uuid4()), run.id)

    assert run.id in unit_of_work.review_runs.stored


async def test_unknown_run_is_reported() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id, _ = prepare(unit_of_work)

    with pytest.raises(EntityNotFoundError):
        await DeleteReviewRun(unit_of_work, publisher).execute(
            tenant_id,
            ReviewRunId(uuid4()),
        )
