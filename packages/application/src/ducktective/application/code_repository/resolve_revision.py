from dataclasses import (
    dataclass,
)

from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.diff.ports import (
    VcsProvider,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.types import (
    CommitSha,
    RepositoryId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class ResolvedRevisionView:
    """Ревизия вместе с тем, во что она разрешилась."""

    revision: str
    commit_sha: CommitSha
    subject: str | None


class ResolveRepositoryRevision:
    """Разрешает ссылку на ревизию в коммит.

    Нужен интерфейсу: `HEAD`, имя ветки и `abc123~1` — ссылки, и во что они
    указывают, знает только git. Сравнивать их со строкой в базе — гадание:
    так интерфейс сообщал о расхождении ревизий там, где расхождения не было.
    """

    def __init__(self, unit_of_work: UnitOfWork, vcs_provider: VcsProvider) -> None:
        self._unit_of_work = unit_of_work
        self._vcs_provider = vcs_provider

    async def execute(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        revision: str,
    ) -> ResolvedRevisionView:
        async with self._unit_of_work:
            repository = await self._unit_of_work.code_repositories.get(repository_id)
            if repository.tenant_id != tenant_id:
                raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")
            path = repository.local_path

        commit_sha = await self._vcs_provider.resolve_revision(path, revision)
        subject = await self._vcs_provider.get_commit_subject(path, revision)

        return ResolvedRevisionView(revision=revision, commit_sha=commit_sha, subject=subject)
