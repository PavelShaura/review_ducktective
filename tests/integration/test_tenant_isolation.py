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
from sqlalchemy import (
    func,
    select,
)
from sqlalchemy.exc import (
    DBAPIError,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import (
    ModelTrust,
    VcsProvider,
)
from ducktective.core.llm.model_profile import (
    ModelProfile,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.review.value_objects import (
    ReviewSource,
)
from ducktective.core.types import (
    CommitSha,
    RepositoryId,
    TenantId,
)
from ducktective.storage.models.code_repository import (
    CodeRepositoryModel,
)
from ducktective.storage.models.model_profile import (
    ModelProfileModel,
)
from ducktective.storage.models.review import (
    ReviewRunModel,
)
from ducktective.storage.models.tenancy import (
    TenantModel,
)
from ducktective.storage.tenant_scope import (
    bind_tenant,
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


async def seed_organization(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    name: str,
) -> tuple[TenantId, RepositoryId]:
    """Организация с репозиторием и одним прогоном ревью."""
    tenant_id = await create_tenant(session_factory)

    async with SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id) as unit_of_work:
        repository = CodeRepository.register(
            tenant_id=tenant_id,
            name=name,
            vcs_provider=VcsProvider.LOCAL,
            local_path=Path(f"/repos/{name}"),
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
        await unit_of_work.commit()

    return tenant_id, repository.id


async def count_visible(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: TenantId | None,
    model: type[CodeRepositoryModel] | type[ReviewRunModel],
) -> int:
    """Считает строки запросом без единого условия — тем самым «забытым WHERE»."""
    async with session_factory() as session:
        await bind_tenant(session, tenant_id)
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def test_forgotten_filter_does_not_show_another_organization(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Запрос без условия отдаёт только своё — ради этого политики и заводились."""
    first_tenant, first_repository = await seed_organization(session_factory, name="first")
    second_tenant, _ = await seed_organization(session_factory, name="second")

    visible_to_first = await count_visible(session_factory, first_tenant, CodeRepositoryModel)
    visible_to_second = await count_visible(session_factory, second_tenant, CodeRepositoryModel)

    assert visible_to_first == 1
    assert visible_to_second == 1

    async with session_factory() as session:
        await bind_tenant(session, first_tenant)
        rows = (await session.execute(select(CodeRepositoryModel.id))).scalars().all()

    assert list(rows) == [first_repository]


async def test_runs_of_another_organization_are_invisible(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_tenant, _ = await seed_organization(session_factory, name="runs-first")
    await seed_organization(session_factory, name="runs-second")

    assert await count_visible(session_factory, first_tenant, ReviewRunModel) == 1


async def test_transaction_without_tenant_sees_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Контур входа открывает транзакцию без тенанта и данных не видит вовсе."""
    await seed_organization(session_factory, name="nameless")

    assert await count_visible(session_factory, None, CodeRepositoryModel) == 0
    assert await count_visible(session_factory, None, ReviewRunModel) == 0


async def test_row_of_another_organization_cannot_be_written(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Политика проверяет и запись: чужой tenant_id в своей транзакции отвергается."""
    first_tenant, _ = await seed_organization(session_factory, name="write-first")
    second_tenant = await create_tenant(session_factory)

    async with session_factory() as session:
        await bind_tenant(session, first_tenant)
        session.add(
            CodeRepositoryModel(
                id=uuid4(),
                tenant_id=second_tenant,
                name="smuggled",
                vcs_provider=VcsProvider.LOCAL,
                remote_url=None,
                default_branch="main",
                local_path="/repos/smuggled",
                egress_policy="local_only",
                created_at=datetime.now(UTC),
            )
        )
        with pytest.raises(DBAPIError):
            await session.commit()


async def test_child_rows_follow_their_parent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Файлы и находки закрыты через прогон, а не собственным полем тенанта."""
    first_tenant, _ = await seed_organization(session_factory, name="children-first")
    second_tenant, _ = await seed_organization(session_factory, name="children-second")

    async with session_factory() as session:
        await bind_tenant(session, first_tenant)
        own = (await session.execute(select(ReviewRunModel.id))).scalars().all()

    async with session_factory() as session:
        await bind_tenant(session, second_tenant)
        foreign = (await session.execute(select(ReviewRunModel.id))).scalars().all()

    assert set(own).isdisjoint(set(foreign))


async def test_model_of_another_organization_is_neither_read_nor_written(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Модели организации закрыты политикой так же, как её прогоны.

    Проверка появилась после живой ошибки: ручка открывала транзакцию без
    названного тенанта — ту, что предназначена контуру входа, — и вставка
    падала на политике уже у пользователя.
    """
    first_tenant = await create_tenant(session_factory)
    second_tenant = await create_tenant(session_factory)

    async with SqlAlchemyUnitOfWork(session_factory, tenant_id=first_tenant) as unit_of_work:
        unit_of_work.model_profiles.add(
            ModelProfile.create(
                tenant_id=first_tenant,
                name="free",
                model="openrouter/model:free",
                encrypted_api_key="ciphertext",
            )
        )
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(session_factory, tenant_id=first_tenant) as unit_of_work:
        assert len(await unit_of_work.model_profiles.list_for_tenant(first_tenant)) == 1

    async with SqlAlchemyUnitOfWork(session_factory, tenant_id=second_tenant) as unit_of_work:
        assert await unit_of_work.model_profiles.list_for_tenant(first_tenant) == []

    async with session_factory() as session:
        await bind_tenant(session, second_tenant)
        session.add(
            ModelProfileModel(
                id=uuid4(),
                tenant_id=first_tenant,
                name="smuggled",
                model="openrouter/model:free",
                provider="openrouter",
                base_url="",
                encrypted_api_key="",
                trust=ModelTrust.TRAINING_REMOTE,
                supports_tools=True,
                context_window=0,
                note="",
                is_enabled=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        with pytest.raises(DBAPIError):
            await session.commit()
