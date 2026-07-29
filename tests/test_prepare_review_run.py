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
from ducktective.application.review.prepare_run import (
    EmptyDiffError,
    NoMatchingFilesError,
    PrepareReviewRun,
    PrepareReviewRunCommand,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import VcsProvider as VcsProviderKind
from ducktective.core.diff.value_objects import (
    STAGED_REVISION,
)
from ducktective.core.review.events import (
    ReviewRunCreated,
)
from ducktective.core.review.value_objects import (
    ReviewStatus,
)
from ducktective.core.types import (
    RepositoryId,
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
    FakeVcsProvider,
)


REPOSITORY_PATH = Path("/repos/sandbox")


def register_repository(unit_of_work: FakeUnitOfWork, tenant_id: TenantId) -> CodeRepository:
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name="sandbox",
        vcs_provider=VcsProviderKind.LOCAL,
        local_path=REPOSITORY_PATH,
    )
    repository.pull_events()
    unit_of_work.code_repositories.add(repository)
    return repository


def build_use_case(
    unit_of_work: FakeUnitOfWork,
    publisher: FakeEventPublisher,
    patch_text: str,
) -> PrepareReviewRun:
    return PrepareReviewRun(
        unit_of_work,
        publisher,
        FakeVcsProvider(patch_text),
        UnifiedDiffParser(),
    )


async def test_run_is_created_from_patch() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id = TenantId(uuid4())
    repository = register_repository(unit_of_work, tenant_id)
    use_case = build_use_case(unit_of_work, publisher, MODIFIED_AND_ADDED_PATCH)

    run = await use_case.execute(
        PrepareReviewRunCommand(
            tenant_id=tenant_id,
            repository_id=repository.id,
            base="main",
            head="feature",
        )
    )

    assert run.status is ReviewStatus.QUEUED
    assert [file.path for file in run.files] == ["app/service.py", "app/helpers.py"]
    assert unit_of_work.review_runs.stored[run.id] is run
    assert unit_of_work.commit_calls == 1


async def test_creation_event_is_published() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id = TenantId(uuid4())
    repository = register_repository(unit_of_work, tenant_id)
    use_case = build_use_case(unit_of_work, publisher, MODIFIED_AND_ADDED_PATCH)

    await use_case.execute(
        PrepareReviewRunCommand(
            tenant_id=tenant_id,
            repository_id=repository.id,
            base="main",
            head="feature",
        )
    )

    assert any(isinstance(event, ReviewRunCreated) for event in publisher.published)


async def test_empty_patch_is_rejected_without_commit() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id = TenantId(uuid4())
    repository = register_repository(unit_of_work, tenant_id)
    use_case = build_use_case(unit_of_work, publisher, "")

    with pytest.raises(EmptyDiffError):
        await use_case.execute(
            PrepareReviewRunCommand(
                tenant_id=tenant_id,
                repository_id=repository.id,
                base="main",
                head="main",
            )
        )

    assert unit_of_work.commit_calls == 0
    assert unit_of_work.review_runs.stored == {}


async def test_foreign_tenant_is_rejected() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    repository = register_repository(unit_of_work, TenantId(uuid4()))
    use_case = build_use_case(unit_of_work, publisher, MODIFIED_AND_ADDED_PATCH)

    with pytest.raises(PermissionDeniedError):
        await use_case.execute(
            PrepareReviewRunCommand(
                tenant_id=TenantId(uuid4()),
                repository_id=repository.id,
                base="main",
                head="feature",
            )
        )

    assert unit_of_work.commit_calls == 0


async def test_repository_path_is_taken_from_aggregate() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id = TenantId(uuid4())
    repository = register_repository(unit_of_work, tenant_id)
    vcs_provider = FakeVcsProvider(MODIFIED_AND_ADDED_PATCH)
    use_case = PrepareReviewRun(unit_of_work, publisher, vcs_provider, UnifiedDiffParser())

    await use_case.execute(
        PrepareReviewRunCommand(
            tenant_id=tenant_id,
            repository_id=repository.id,
            base="main",
            head="feature",
        )
    )

    assert vcs_provider.requested_paths == [REPOSITORY_PATH]


async def test_staged_mode_uses_index_instead_of_revisions() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id = TenantId(uuid4())
    repository = register_repository(unit_of_work, tenant_id)
    vcs_provider = FakeVcsProvider("", staged_patch_text=MODIFIED_AND_ADDED_PATCH)
    use_case = PrepareReviewRun(unit_of_work, publisher, vcs_provider, UnifiedDiffParser())

    run = await use_case.execute(
        PrepareReviewRunCommand(
            tenant_id=tenant_id,
            repository_id=repository.id,
            staged=True,
        )
    )

    assert run.head_sha == STAGED_REVISION
    assert run.base_sha == "sha-HEAD"
    assert len(run.files) == 2


async def test_staged_mode_without_changes_is_reported() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id = TenantId(uuid4())
    repository = register_repository(unit_of_work, tenant_id)
    vcs_provider = FakeVcsProvider("", staged_patch_text="")
    use_case = PrepareReviewRun(unit_of_work, publisher, vcs_provider, UnifiedDiffParser())

    with pytest.raises(EmptyDiffError):
        await use_case.execute(
            PrepareReviewRunCommand(
                tenant_id=tenant_id,
                repository_id=repository.id,
                staged=True,
            )
        )


async def test_include_pattern_narrows_review() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id = TenantId(uuid4())
    repository = register_repository(unit_of_work, tenant_id)
    use_case = build_use_case(unit_of_work, publisher, MODIFIED_AND_ADDED_PATCH)

    run = await use_case.execute(
        PrepareReviewRunCommand(
            tenant_id=tenant_id,
            repository_id=repository.id,
            base="main",
            head="feature",
            include_patterns=("*/service.py",),
        )
    )

    assert [file.path for file in run.files] == ["app/service.py"]


async def test_include_pattern_without_matches_is_reported() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    tenant_id = TenantId(uuid4())
    repository = register_repository(unit_of_work, tenant_id)
    use_case = build_use_case(unit_of_work, publisher, MODIFIED_AND_ADDED_PATCH)

    with pytest.raises(NoMatchingFilesError):
        await use_case.execute(
            PrepareReviewRunCommand(
                tenant_id=tenant_id,
                repository_id=repository.id,
                base="main",
                head="feature",
                include_patterns=("*.ts",),
            )
        )

    assert unit_of_work.commit_calls == 0


async def test_missing_repository_is_reported() -> None:
    unit_of_work = FakeUnitOfWork()
    publisher = FakeEventPublisher()
    use_case = build_use_case(unit_of_work, publisher, MODIFIED_AND_ADDED_PATCH)

    with pytest.raises(Exception, match="CodeRepository"):
        await use_case.execute(
            PrepareReviewRunCommand(
                tenant_id=TenantId(uuid4()),
                repository_id=RepositoryId(uuid4()),
                base="main",
                head="feature",
            )
        )
