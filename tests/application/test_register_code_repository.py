from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.application.code_repository.register import (
    RegisterCodeRepository,
    RegisterCodeRepositoryCommand,
    RepositoryAlreadyRegisteredError,
)
from ducktective.core.code_repository.events import (
    CodeRepositoryRegistered,
)
from ducktective.core.code_repository.value_objects import (
    VcsProvider,
)
from ducktective.core.types import (
    TenantId,
)
from tests.fakes import (
    FakeEventPublisher,
    FakeUnitOfWork,
)


def build_command(name: str = "sandbox") -> RegisterCodeRepositoryCommand:
    return RegisterCodeRepositoryCommand(
        tenant_id=TenantId(uuid4()),
        name=name,
        vcs_provider=VcsProvider.LOCAL,
        local_path=Path("/repos/sandbox"),
    )


async def test_repository_is_stored_and_committed() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    use_case = RegisterCodeRepository(unit_of_work, publisher)

    repository = await use_case.execute(build_command())

    assert unit_of_work.code_repositories.stored[repository.id] is repository
    assert unit_of_work.commit_calls == 1


async def test_events_are_published_after_commit() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    use_case = RegisterCodeRepository(unit_of_work, publisher)

    await use_case.execute(build_command())

    assert len(publisher.published) == 1
    assert isinstance(publisher.published[0], CodeRepositoryRegistered)


async def test_duplicate_name_is_rejected_without_commit() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    use_case = RegisterCodeRepository(unit_of_work, publisher)

    command = build_command()
    await use_case.execute(command)

    with pytest.raises(RepositoryAlreadyRegisteredError):
        await use_case.execute(command)

    assert unit_of_work.commit_calls == 1
