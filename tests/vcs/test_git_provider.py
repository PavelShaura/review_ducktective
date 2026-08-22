import subprocess
from pathlib import (
    Path,
)

import pytest

from ducktective.core.exceptions import (
    VcsOperationError,
)
from ducktective.vcs.git_provider import (
    LocalGitProvider,
)


def run_git(repository_path: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository_path), *arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    run_git(tmp_path, "init", "-q")
    run_git(tmp_path, "config", "user.email", "test@local")
    run_git(tmp_path, "config", "user.name", "test")

    (tmp_path / "service.py").write_text("def build():\n    return None\n", encoding="utf-8")
    run_git(tmp_path, "add", "-A")
    run_git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


async def test_existing_revision_is_resolved(repository: Path) -> None:
    provider = LocalGitProvider()

    resolved = await provider.resolve_revision(repository, "HEAD")

    assert len(resolved) == 40


async def test_unknown_commit_is_named_in_message(repository: Path) -> None:
    provider = LocalGitProvider()

    with pytest.raises(VcsOperationError) as error:
        await provider.resolve_revision(repository, "dc1283466c1")

    assert "dc1283466c1" in str(error.value)
    assert "нет в этом репозитории" in str(error.value)


async def test_first_commit_has_no_parent(repository: Path) -> None:
    provider = LocalGitProvider()

    with pytest.raises(VcsOperationError) as error:
        await provider.resolve_revision(repository, "HEAD~1")

    assert "первый коммит" in str(error.value)


async def test_unknown_base_of_relative_revision_is_reported(repository: Path) -> None:
    provider = LocalGitProvider()

    with pytest.raises(VcsOperationError) as error:
        await provider.resolve_revision(repository, "abcdef123~1")

    assert "abcdef123" in str(error.value)
    assert "git fetch" in str(error.value)


async def test_staged_patch_contains_indexed_changes(repository: Path) -> None:
    (repository / "service.py").write_text(
        "def build():\n    return compute()\n",
        encoding="utf-8",
    )
    run_git(repository, "add", "-A")
    provider = LocalGitProvider()

    patch = await provider.get_staged_patch(repository)

    assert "service.py" in patch
    assert "+    return compute()" in patch


async def test_missing_directory_is_reported() -> None:
    provider = LocalGitProvider()

    with pytest.raises(VcsOperationError, match="не найден"):
        await provider.resolve_revision(Path("/nonexistent/repository"), "HEAD")
