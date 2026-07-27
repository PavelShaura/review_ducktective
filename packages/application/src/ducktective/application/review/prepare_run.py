from dataclasses import (
    dataclass,
)

from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    ApplicationError,
    PermissionDeniedError,
)
from ducktective.core.diff.ports import (
    DiffParser,
    VcsProvider,
)
from ducktective.core.diff.value_objects import (
    STAGED_REVISION,
)
from ducktective.core.ports import (
    EventPublisher,
    UnitOfWork,
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
    UserId,
)


@dataclass(frozen=True, kw_only=True)
class PrepareReviewRunCommand:
    tenant_id: TenantId
    repository_id: RepositoryId
    base: str = "HEAD"
    head: str = "HEAD"
    staged: bool = False
    include_patterns: tuple[str, ...] = ()
    source: ReviewSource = ReviewSource.LOCAL_DIFF
    external_pull_request_id: str | None = None
    created_by: UserId | None = None


class EmptyDiffError(ApplicationError):
    def __init__(self, base: str, head: str) -> None:
        super().__init__(f"Между {base} и {head} нет изменений")
        self.base = base
        self.head = head


class NoMatchingFilesError(ApplicationError):
    def __init__(self, patterns: tuple[str, ...]) -> None:
        super().__init__(f"Ни один файл диффа не совпал с шаблонами: {', '.join(patterns)}")
        self.patterns = patterns


def _describe_range(command: "PrepareReviewRunCommand") -> tuple[str, str]:
    if command.staged:
        return "HEAD", "проиндексированными изменениями"
    return command.base, command.head


class PrepareReviewRun(TransactionalUseCase):
    """Создаёт прогон ревью по диффу между двумя ревизиями.

    Обращение к git и разбор патча выполняются вне транзакции: держать соединение
    открытым на время внешних операций нельзя.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        event_publisher: EventPublisher,
        vcs_provider: VcsProvider,
        diff_parser: DiffParser,
    ) -> None:
        super().__init__(unit_of_work, event_publisher)
        self._vcs_provider = vcs_provider
        self._diff_parser = diff_parser

    async def execute(self, command: PrepareReviewRunCommand) -> ReviewRun:
        async with self._unit_of_work:
            repository = await self._unit_of_work.code_repositories.get(command.repository_id)
            if repository.tenant_id != command.tenant_id:
                raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")
            repository_path = repository.local_path

        if command.staged:
            base_sha = await self._vcs_provider.resolve_revision(repository_path, "HEAD")
            head_sha = CommitSha(STAGED_REVISION)
            patch_text = await self._vcs_provider.get_staged_patch(repository_path)
        else:
            base_sha = await self._vcs_provider.resolve_revision(repository_path, command.base)
            head_sha = await self._vcs_provider.resolve_revision(repository_path, command.head)
            patch_text = await self._vcs_provider.get_patch(
                repository_path,
                base=command.base,
                head=command.head,
            )

        diff = self._diff_parser.parse(patch_text, base_sha=base_sha, head_sha=head_sha)
        if diff.is_empty:
            raise EmptyDiffError(*_describe_range(command))

        diff = diff.include_only(command.include_patterns)
        if diff.is_empty:
            raise NoMatchingFilesError(command.include_patterns)

        async with self._unit_of_work:
            run = ReviewRun.create(
                tenant_id=command.tenant_id,
                repository_id=command.repository_id,
                source=command.source,
                diff=diff,
                created_by=command.created_by,
                external_pull_request_id=command.external_pull_request_id,
            )
            self._unit_of_work.review_runs.add(run)
            await self._commit_and_publish()

        return run
