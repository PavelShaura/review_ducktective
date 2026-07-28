from pathlib import (
    Path,
)
from typing import (
    Protocol,
)

from ducktective.core.diff.entities import (
    Diff,
)
from ducktective.core.types import (
    CommitSha,
    ContentHash,
)


class DiffParser(Protocol):
    """Разбор unified diff в доменные объекты."""

    def parse(self, patch_text: str, *, base_sha: CommitSha, head_sha: CommitSha) -> Diff: ...


class VcsProvider(Protocol):
    """Доступ к системе контроля версий.

    Операции медленные и выполняются вне открытой транзакции.
    """

    async def resolve_revision(self, repository_path: Path, revision: str) -> CommitSha: ...

    async def get_patch(
        self,
        repository_path: Path,
        *,
        base: str,
        head: str,
    ) -> str: ...

    async def get_staged_patch(self, repository_path: Path) -> str:
        """Изменения, подготовленные к коммиту, но ещё не закоммиченные."""
        ...

    async def get_file_content(
        self,
        repository_path: Path,
        *,
        revision: str,
        path: str,
    ) -> str | None: ...

    async def list_tree(self, repository_path: Path, revision: str) -> dict[str, ContentHash]:
        """Файлы ревизии и хеш содержимого каждого.

        Хеш отдаёт сама система контроля версий, поэтому для сверки с прошлым
        снапшотом читать файлы не нужно — на этом держится инкрементальность.
        """
        ...
