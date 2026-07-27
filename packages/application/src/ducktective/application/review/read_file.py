from pathlib import (
    Path,
)

from ducktective.application.exceptions import (
    ApplicationError,
    PermissionDeniedError,
)
from ducktective.application.review.views import (
    FileContextView,
    FilePatchView,
)
from ducktective.core.diff.ports import (
    VcsProvider,
)
from ducktective.core.diff.value_objects import (
    ChangeType,
    DiffSide,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
    VcsOperationError,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.review.entities import (
    ReviewFile,
    ReviewRun,
)
from ducktective.core.review.limits import (
    MAX_CONTEXT_WINDOW_LINES,
)
from ducktective.core.types import (
    CommitSha,
    ReviewFileId,
    ReviewRunId,
    TenantId,
)


class FileContentUnavailableError(ApplicationError):
    def __init__(self, path: str, commit_sha: str) -> None:
        super().__init__(f"Содержимое {path} недоступно в ревизии {commit_sha}")
        self.path = path
        self.commit_sha = commit_sha


class GetFilePatch:
    """Отдаёт патч файла в формате unified diff.

    Слишком большие файлы возвращаются без текста: клиент показывает заглушку
    вместо того, чтобы пытаться отрисовать десятки тысяч строк.

    Вместе с патчем сообщается длина файла в ревизии. Без неё клиент не может
    отличить изменение в конце файла от изменения, за которым идёт ещё код,
    и предлагал бы раскрыть несуществующий остаток.
    """

    def __init__(self, unit_of_work: UnitOfWork, vcs_provider: VcsProvider) -> None:
        self._unit_of_work = unit_of_work
        self._vcs_provider = vcs_provider

    async def execute(
        self,
        tenant_id: TenantId,
        run_id: ReviewRunId,
        file_id: ReviewFileId,
    ) -> FilePatchView:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            file = _resolve_file(run, tenant_id, file_id)
            repository = await self._unit_of_work.code_repositories.get(run.repository_id)
            repository_path = repository.local_path

        is_too_large = file.is_too_large_to_display
        side = _context_side(file)
        total_lines = (
            None if is_too_large else await self._count_lines(repository_path, run, file, side)
        )

        return FilePatchView(
            path=file.path,
            previous_path=file.previous_path,
            change_type=file.change_type,
            language=file.language,
            added_lines=file.added_lines,
            removed_lines=file.removed_lines,
            is_too_large=is_too_large,
            patch_size_bytes=file.patch_size_bytes,
            patch="" if is_too_large else file.to_unified_patch(),
            context_side=side,
            total_lines=total_lines,
        )

    async def _count_lines(
        self,
        repository_path: Path,
        run: ReviewRun,
        file: ReviewFile,
        side: DiffSide,
    ) -> int | None:
        """Считает строки файла в ревизии, из которой раскрывается контекст.

        Недоступное содержимое не считается ошибкой: патч показывается и без
        длины, просто без предложения раскрыть остаток файла.
        """
        commit_sha, path = _content_location(run, file, side)

        try:
            content = await self._vcs_provider.get_file_content(
                repository_path,
                revision=commit_sha,
                path=path,
            )
        except VcsOperationError:
            return None

        return None if content is None else len(content.splitlines())


class GetFileContext:
    """Отдаёт произвольный фрагмент файла для раскрытия контекста вокруг ханка."""

    def __init__(self, unit_of_work: UnitOfWork, vcs_provider: VcsProvider) -> None:
        self._unit_of_work = unit_of_work
        self._vcs_provider = vcs_provider

    async def execute(
        self,
        tenant_id: TenantId,
        run_id: ReviewRunId,
        file_id: ReviewFileId,
        *,
        side: DiffSide,
        start_line: int,
        end_line: int,
    ) -> FileContextView:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            file = _resolve_file(run, tenant_id, file_id)
            repository = await self._unit_of_work.code_repositories.get(run.repository_id)
            repository_path = repository.local_path

        commit_sha, path = _content_location(run, file, side)

        content = await self._vcs_provider.get_file_content(
            repository_path,
            revision=commit_sha,
            path=path,
        )
        if content is None:
            raise FileContentUnavailableError(path, commit_sha)

        all_lines = content.splitlines()
        window_start = max(start_line, 1)
        window_end = min(end_line, len(all_lines), window_start + MAX_CONTEXT_WINDOW_LINES - 1)

        return FileContextView(
            path=path,
            side=side,
            commit_sha=commit_sha,
            start_line=window_start,
            end_line=max(window_end, window_start - 1),
            total_lines=len(all_lines),
            lines=all_lines[window_start - 1 : window_end],
        )


def _context_side(file: ReviewFile) -> DiffSide:
    """Сторона, из которой читается окружение изменений.

    У удалённого файла новой версии не существует, у всех остальных
    интереснее именно она.
    """
    return DiffSide.OLD if file.change_type is ChangeType.DELETED else DiffSide.NEW


def _content_location(run: ReviewRun, file: ReviewFile, side: DiffSide) -> tuple[CommitSha, str]:
    if side is DiffSide.OLD:
        return run.base_sha, file.previous_path or file.path
    return run.head_sha, file.path


def _resolve_file(run: ReviewRun, tenant_id: TenantId, file_id: ReviewFileId) -> ReviewFile:
    if run.tenant_id != tenant_id:
        raise PermissionDeniedError("Прогон принадлежит другому тенанту")

    file = run.find_file_by_id(file_id)
    if file is None:
        raise EntityNotFoundError("ReviewFile", file_id)
    return file
