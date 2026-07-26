from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.application.review.read_file import (
    FileContentUnavailableError,
    GetFileContext,
    GetFilePatch,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import VcsProvider as VcsProviderKind
from ducktective.core.diff.value_objects import (
    DiffSide,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.review.limits import (
    MAX_CONTEXT_WINDOW_LINES,
)
from ducktective.core.review.value_objects import (
    ReviewSource,
)
from ducktective.core.types import (
    CommitSha,
    ReviewFileId,
    TenantId,
)
from ducktective.vcs.diff_parser import (
    UnifiedDiffParser,
)
from tests.diff_fixtures import (
    MODIFIED_AND_ADDED_PATCH,
)
from tests.fakes import (
    FakeUnitOfWork,
    FakeVcsProvider,
)


REPOSITORY_PATH = Path("/repos/edussuz")
SOURCE_FILE = "app/service.py"


def prepare(unit_of_work: FakeUnitOfWork) -> tuple[TenantId, ReviewRun]:
    tenant_id = TenantId(uuid4())
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name="edussuz",
        vcs_provider=VcsProviderKind.LOCAL,
        local_path=REPOSITORY_PATH,
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


async def test_patch_contains_git_header_and_hunk() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    file = run.files[0]

    view = await GetFilePatch(unit_of_work).execute(tenant_id, run.id, file.id)

    assert view.path == SOURCE_FILE
    assert view.patch.startswith(f"diff --git a/{SOURCE_FILE} b/{SOURCE_FILE}")
    assert f"--- a/{SOURCE_FILE}" in view.patch
    assert f"+++ b/{SOURCE_FILE}" in view.patch
    assert "@@ -10,2 +10,3 @@" in view.patch
    assert view.is_too_large is False


async def test_added_file_patch_uses_dev_null_as_source() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    added_file = run.files[1]

    view = await GetFilePatch(unit_of_work).execute(tenant_id, run.id, added_file.id)

    assert view.patch.splitlines()[1] == "--- /dev/null"
    assert view.patch.splitlines()[2] == "+++ b/app/helpers.py"


async def test_oversized_file_is_returned_without_text() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    file = run.files[0]
    file.hunks[0].patch_text = "+line\n" * 6000

    view = await GetFilePatch(unit_of_work).execute(tenant_id, run.id, file.id)

    assert view.is_too_large is True
    assert view.patch == ""
    assert view.patch_size_bytes > 0


async def test_unknown_file_is_reported() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)

    with pytest.raises(EntityNotFoundError):
        await GetFilePatch(unit_of_work).execute(tenant_id, run.id, ReviewFileId(uuid4()))


async def test_context_returns_requested_window() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    file = run.files[0]
    content = "\n".join(f"line {number}" for number in range(1, 51))
    vcs_provider = FakeVcsProvider(file_contents={SOURCE_FILE: content})

    view = await GetFileContext(unit_of_work, vcs_provider).execute(
        tenant_id,
        run.id,
        file.id,
        side=DiffSide.NEW,
        start_line=10,
        end_line=14,
    )

    assert view.lines == ["line 10", "line 11", "line 12", "line 13", "line 14"]
    assert view.total_lines == 50
    assert view.commit_sha == run.head_sha


async def test_context_window_is_capped() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    file = run.files[0]
    content = "\n".join(f"line {number}" for number in range(1, 2001))
    vcs_provider = FakeVcsProvider(file_contents={SOURCE_FILE: content})

    view = await GetFileContext(unit_of_work, vcs_provider).execute(
        tenant_id,
        run.id,
        file.id,
        side=DiffSide.NEW,
        start_line=1,
        end_line=2000,
    )

    assert len(view.lines) == MAX_CONTEXT_WINDOW_LINES


async def test_context_beyond_end_of_file_is_clamped() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    file = run.files[0]
    vcs_provider = FakeVcsProvider(file_contents={SOURCE_FILE: "only one line"})

    view = await GetFileContext(unit_of_work, vcs_provider).execute(
        tenant_id,
        run.id,
        file.id,
        side=DiffSide.NEW,
        start_line=1,
        end_line=100,
    )

    assert view.lines == ["only one line"]
    assert view.end_line == 1


async def test_missing_content_is_reported() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, run = prepare(unit_of_work)
    file = run.files[0]
    vcs_provider = FakeVcsProvider(file_contents={})

    with pytest.raises(FileContentUnavailableError):
        await GetFileContext(unit_of_work, vcs_provider).execute(
            tenant_id,
            run.id,
            file.id,
            side=DiffSide.OLD,
            start_line=1,
            end_line=5,
        )
