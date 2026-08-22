from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.application.code_repository.resolve import (
    RepositoryNotResolvedError,
    ResolveCodeRepository,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import (
    VcsProvider,
)
from ducktective.core.types import (
    TenantId,
)
from tests.fakes import (
    FakeUnitOfWork,
)


TENANT_ID = TenantId(uuid4())
OTHER_TENANT_ID = TenantId(uuid4())


def registered(
    unit_of_work: FakeUnitOfWork,
    name: str,
    *,
    tenant_id: TenantId = TENANT_ID,
) -> CodeRepository:
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name=name,
        vcs_provider=VcsProvider.LOCAL,
        local_path=Path(f"/repos/{name}"),
    )
    unit_of_work.code_repositories.add(repository)
    return repository


async def test_resolves_by_name() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work, "ducktective")

    found = await ResolveCodeRepository(unit_of_work).execute(TENANT_ID, "ducktective")

    assert found.id == repository.id


async def test_resolves_by_identifier() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work, "ducktective")

    found = await ResolveCodeRepository(unit_of_work).execute(TENANT_ID, str(repository.id))

    assert found.id == repository.id


async def test_unknown_reference_carries_available_names() -> None:
    """Ошибшийся в названии должен получить выбор, а не тупик."""
    unit_of_work = FakeUnitOfWork()
    registered(unit_of_work, "ducktective")
    registered(unit_of_work, "sandbox")

    with pytest.raises(RepositoryNotResolvedError) as error:
        await ResolveCodeRepository(unit_of_work).execute(TENANT_ID, "duck")

    assert error.value.available == ["ducktective", "sandbox"]


async def test_identifier_of_foreign_tenant_is_denied() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work, "ducktective", tenant_id=OTHER_TENANT_ID)

    with pytest.raises(PermissionDeniedError):
        await ResolveCodeRepository(unit_of_work).execute(TENANT_ID, str(repository.id))


async def test_name_of_foreign_tenant_is_not_found() -> None:
    unit_of_work = FakeUnitOfWork()
    registered(unit_of_work, "ducktective", tenant_id=OTHER_TENANT_ID)

    with pytest.raises(RepositoryNotResolvedError) as error:
        await ResolveCodeRepository(unit_of_work).execute(TENANT_ID, "ducktective")

    assert error.value.available == []


async def test_unknown_identifier_falls_back_to_name_lookup() -> None:
    unit_of_work = FakeUnitOfWork()

    with pytest.raises(RepositoryNotResolvedError):
        await ResolveCodeRepository(unit_of_work).execute(TENANT_ID, str(uuid4()))
