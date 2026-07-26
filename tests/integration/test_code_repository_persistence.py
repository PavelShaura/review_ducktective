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
    EgressPolicy,
    VcsProvider,
)
from ducktective.core.types import (
    TenantId,
)
from ducktective.storage.models.tenancy import (
    TenantModel,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


pytestmark = pytest.mark.integration


async def create_tenant(session_factory: async_sessionmaker[AsyncSession]) -> TenantId:
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
    return TenantId(tenant_id)


def build_repository(tenant_id: TenantId, name: str = "edussuz") -> CodeRepository:
    return CodeRepository.register(
        tenant_id=tenant_id,
        name=name,
        vcs_provider=VcsProvider.LOCAL,
        local_path=Path("/repos/edussuz"),
    )


async def test_repository_survives_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await create_tenant(session_factory)
    repository = build_repository(tenant_id)

    async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.code_repositories.add(repository)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        stored = await unit_of_work.code_repositories.get(repository.id)

    assert stored.name == repository.name
    assert stored.local_path == repository.local_path
    assert stored.egress_policy is EgressPolicy.LOCAL_ONLY
    assert stored.created_at.tzinfo is not None


async def test_changes_without_commit_are_rolled_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await create_tenant(session_factory)
    repository = build_repository(tenant_id, name="rolled-back")

    async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.code_repositories.add(repository)

    async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        found = await unit_of_work.code_repositories.find_by_name(tenant_id, "rolled-back")

    assert found is None


async def test_policy_change_is_persisted_and_produces_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await create_tenant(session_factory)
    repository = build_repository(tenant_id, name="policy-change")

    async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.code_repositories.add(repository)
        await unit_of_work.commit()
        unit_of_work.collect_events()

    async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        stored = await unit_of_work.code_repositories.get(repository.id)
        stored.change_egress_policy(EgressPolicy.ALLOW_CLOUD)
        await unit_of_work.commit()
        events = unit_of_work.collect_events()

    assert len(events) == 1

    async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        reloaded = await unit_of_work.code_repositories.get(repository.id)

    assert reloaded.egress_policy is EgressPolicy.ALLOW_CLOUD


async def test_duplicate_name_within_tenant_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = await create_tenant(session_factory)

    async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.code_repositories.add(build_repository(tenant_id, name="duplicate"))
        await unit_of_work.commit()

    with pytest.raises(Exception, match="uq_repository_tenant_id_name"):
        async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            unit_of_work.code_repositories.add(build_repository(tenant_id, name="duplicate"))
            await unit_of_work.commit()
