from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.application.code_repository.resolve_revision import (
    ResolveRepositoryRevision,
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
from ducktective.core.exceptions import (
    VcsOperationError,
)
from ducktective.core.types import (
    TenantId,
)
from tests.fakes import (
    FakeUnitOfWork,
    FakeVcsProvider,
)


TENANT_ID = TenantId(uuid4())
OTHER_TENANT_ID = TenantId(uuid4())


def registered(unit_of_work: FakeUnitOfWork, *, tenant_id: TenantId = TENANT_ID) -> CodeRepository:
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name="library",
        vcs_provider=VcsProvider.LOCAL,
        local_path=Path("/repos/library"),
    )
    unit_of_work.code_repositories.add(repository)
    return repository


async def test_symbolic_reference_is_resolved_to_a_commit() -> None:
    """`HEAD` — ссылка, и во что она указывает, знает только git."""
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    provider = FakeVcsProvider(commit_subject="Перевод чатов на следующий год")

    view = await ResolveRepositoryRevision(unit_of_work, provider).execute(
        TENANT_ID,
        repository.id,
        "HEAD",
    )

    assert view.revision == "HEAD"
    assert view.commit_sha != "HEAD"
    assert view.subject == "Перевод чатов на следующий год"


async def test_unknown_revision_is_reported_as_a_failure() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work)
    provider = FakeVcsProvider(known_revisions=set())

    with pytest.raises(VcsOperationError):
        await ResolveRepositoryRevision(unit_of_work, provider).execute(
            TENANT_ID,
            repository.id,
            "нет-такой-ревизии",
        )


async def test_foreign_repository_is_denied() -> None:
    unit_of_work = FakeUnitOfWork()
    repository = registered(unit_of_work, tenant_id=OTHER_TENANT_ID)

    with pytest.raises(PermissionDeniedError):
        await ResolveRepositoryRevision(unit_of_work, FakeVcsProvider()).execute(
            TENANT_ID,
            repository.id,
            "HEAD",
        )
