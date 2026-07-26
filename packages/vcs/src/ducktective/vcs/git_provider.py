import asyncio
from pathlib import (
    Path,
)

from ducktective.core.exceptions import (
    VcsOperationError,
)
from ducktective.core.types import (
    CommitSha,
)


GIT_EXECUTABLE = "git"
DIFF_ARGUMENTS = (
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "--find-renames",
    "--unified=3",
)


class LocalGitProvider:
    """Работа с локальным git-репозиторием через командную строку.

    Отдельная библиотека не используется намеренно: нужен предсказуемый набор
    флагов и асинхронный запуск, а весь необходимый функционал сводится к трём
    командам.
    """

    def __init__(self, *, executable: str = GIT_EXECUTABLE, timeout_seconds: float = 60.0) -> None:
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    async def resolve_revision(self, repository_path: Path, revision: str) -> CommitSha:
        stdout = await self._run(repository_path, "rev-parse", "--verify", f"{revision}^{{commit}}")
        return CommitSha(stdout.strip())

    async def get_patch(
        self,
        repository_path: Path,
        *,
        base: str,
        head: str,
        use_merge_base: bool = True,
    ) -> str:
        """Возвращает unified diff между ревизиями.

        По умолчанию используется трёхточечный синтаксис: он показывает только то,
        что добавила ветка head, игнорируя изменения, попавшие в base параллельно.
        """
        separator = "..." if use_merge_base else ".."
        return await self._run(
            repository_path,
            "diff",
            *DIFF_ARGUMENTS,
            f"{base}{separator}{head}",
        )

    async def get_file_content(
        self,
        repository_path: Path,
        *,
        revision: str,
        path: str,
    ) -> str | None:
        try:
            return await self._run(repository_path, "show", f"{revision}:{path}")
        except VcsOperationError:
            return None

    async def _run(self, repository_path: Path, *arguments: str) -> str:
        if not repository_path.exists():
            raise VcsOperationError(f"Каталог репозитория не найден: {repository_path}")

        process = await asyncio.create_subprocess_exec(
            self._executable,
            "-C",
            str(repository_path),
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            process.kill()
            raise VcsOperationError(
                f"Команда git превысила таймаут {self._timeout_seconds} с: {' '.join(arguments)}"
            ) from error

        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise VcsOperationError(f"git {' '.join(arguments)} завершился с ошибкой: {message}")

        return stdout.decode("utf-8", errors="replace")
