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
    DiffSide,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
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
    """

    def __init__(self, unit_of_work: UnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def execute(
        self,
        tenant_id: TenantId,
        run_id: ReviewRunId,
        file_id: ReviewFileId,
    ) -> FilePatchView:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            file = _resolve_file(run, tenant_id, file_id)

            is_too_large = file.is_too_large_to_display
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
            )


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

        commit_sha = run.base_sha if side is DiffSide.OLD else run.head_sha
        path = file.previous_path or file.path if side is DiffSide.OLD else file.path

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


def _resolve_file(run: ReviewRun, tenant_id: TenantId, file_id: ReviewFileId) -> ReviewFile:
    if run.tenant_id != tenant_id:
        raise PermissionDeniedError("Прогон принадлежит другому тенанту")

    file = run.find_file_by_id(file_id)
    if file is None:
        raise EntityNotFoundError("ReviewFile", file_id)
    return file
