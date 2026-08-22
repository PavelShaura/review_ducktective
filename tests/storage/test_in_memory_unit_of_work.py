from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.events import (
    CodeRepositoryRegistered,
)
from ducktective.core.code_repository.value_objects import (
    VcsProvider,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.types import (
    TenantId,
)
from ducktective.storage.memory.unit_of_work import (
    InMemoryUnitOfWork,
)


def build_repository(tenant_id: TenantId, name: str = "demo") -> CodeRepository:
    return CodeRepository.register(
        tenant_id=tenant_id,
        name=name,
        vcs_provider=VcsProvider.LOCAL,
        local_path=Path("/repos/demo"),
    )


async def test_committed_aggregate_survives_new_transaction() -> None:
    unit_of_work = InMemoryUnitOfWork()
    tenant_id = TenantId(uuid4())
    repository = build_repository(tenant_id)

    async with unit_of_work:
        unit_of_work.code_repositories.add(repository)
        await unit_of_work.commit()

    async with unit_of_work:
        stored = await unit_of_work.code_repositories.get(repository.id)

    assert stored is repository


async def test_aggregate_without_commit_is_discarded() -> None:
    unit_of_work = InMemoryUnitOfWork()
    tenant_id = TenantId(uuid4())
    repository = build_repository(tenant_id)

    async with unit_of_work:
        unit_of_work.code_repositories.add(repository)

    async with unit_of_work:
        with pytest.raises(EntityNotFoundError):
            await unit_of_work.code_repositories.get(repository.id)


async def test_events_are_collected_on_commit() -> None:
    unit_of_work = InMemoryUnitOfWork()
    tenant_id = TenantId(uuid4())

    async with unit_of_work:
        unit_of_work.code_repositories.add(build_repository(tenant_id))
        await unit_of_work.commit()
        events = unit_of_work.collect_events()

    assert len(events) == 1
    assert isinstance(events[0], CodeRepositoryRegistered)
    assert unit_of_work.collect_events() == []


async def test_search_by_name_sees_committed_aggregates() -> None:
    unit_of_work = InMemoryUnitOfWork()
    tenant_id = TenantId(uuid4())

    async with unit_of_work:
        unit_of_work.code_repositories.add(build_repository(tenant_id, name="sandbox"))
        await unit_of_work.commit()

    async with unit_of_work:
        found = await unit_of_work.code_repositories.find_by_name(tenant_id, "sandbox")

    assert found is not None
    assert found.name == "sandbox"


async def test_nested_unit_of_work_is_rejected() -> None:
    unit_of_work = InMemoryUnitOfWork()

    async with unit_of_work:
        with pytest.raises(RuntimeError):
            await unit_of_work.__aenter__()
