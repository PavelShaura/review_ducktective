from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.application.code_repository.delete import (
    DeleteCodeRepository,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.events import (
    CodeRepositoryDeleted,
)
from ducktective.core.code_repository.value_objects import VcsProvider as VcsProviderKind
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)
from tests.fakes import (
    FakeEventPublisher,
    FakeUnitOfWork,
)


def prepare(unit_of_work: FakeUnitOfWork) -> tuple[TenantId, CodeRepository]:
    tenant_id = TenantId(uuid4())
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name="sandbox",
        vcs_provider=VcsProviderKind.LOCAL,
        local_path=Path("/repos/sandbox"),
    )
    repository.pull_events()
    unit_of_work.code_repositories.add(repository)
    return tenant_id, repository


async def test_repository_is_removed() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository = prepare(unit_of_work)

    await DeleteCodeRepository(unit_of_work, FakeEventPublisher()).execute(
        tenant_id,
        repository.id,
    )

    assert await unit_of_work.code_repositories.list_for_tenant(tenant_id) == []


async def test_deletion_is_announced() -> None:
    """Событие нужно до самого удаления: после него агрегата уже нет."""
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id, repository = prepare(unit_of_work)

    await DeleteCodeRepository(unit_of_work, publisher).execute(tenant_id, repository.id)

    assert any(isinstance(event, CodeRepositoryDeleted) for event in publisher.published)


async def test_foreign_tenant_cannot_delete() -> None:
    unit_of_work = FakeUnitOfWork()
    _, repository = prepare(unit_of_work)

    with pytest.raises(PermissionDeniedError):
        await DeleteCodeRepository(unit_of_work, FakeEventPublisher()).execute(
            TenantId(uuid4()),
            repository.id,
        )


async def test_unknown_repository_is_reported() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, _ = prepare(unit_of_work)

    with pytest.raises(EntityNotFoundError):
        await DeleteCodeRepository(unit_of_work, FakeEventPublisher()).execute(
            tenant_id,
            RepositoryId(uuid4()),
        )
