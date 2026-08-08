import asyncio
from dataclasses import (
    dataclass,
)
from pathlib import (
    Path,
)

from ducktective.core.exceptions import (
    RepositoryPathError,
    VcsOperationError,
)
from ducktective.core.types import (
    CommitSha,
    ContentHash,
)


GIT_EXECUTABLE = "git"
GREP_NO_MATCHES = 1
"""git grep отличает «не нашлось» от сбоя кодом возврата, а не текстом."""

MATCHES_PER_FILE = 5
RELATIVE_REVISION_MARKS = ("~", "^")
TREE_FORMAT = "%(objectmode) %(objectname) %(path)"
REGULAR_FILE_MODES = frozenset({"100644", "100755"})
DIFF_ARGUMENTS = (
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "--find-renames",
    "--unified=3",
)


@dataclass(frozen=True, kw_only=True)
class GrepHit:
    """Строка ревизии, совпавшая с образцом."""

    path: str
    line_number: int
    text: str


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
        try:
            stdout = await self._run(
                repository_path,
                "rev-parse",
                "--verify",
                f"{revision}^{{commit}}",
            )
        except RepositoryPathError:
            raise
        except VcsOperationError as error:
            message = await self._describe_unknown_revision(repository_path, revision)
            raise VcsOperationError(message) from error
        return CommitSha(stdout.strip())

    async def _describe_unknown_revision(self, repository_path: Path, revision: str) -> str:
        """Объясняет, почему ревизия не разрешилась.

        Вывод git здесь бесполезен: «Needed a single revision» не говорит,
        отсутствует ли сам коммит или у него просто нет родителя.
        """
        base = revision
        for mark in RELATIVE_REVISION_MARKS:
            base = base.split(mark)[0]

        if base == revision:
            return (
                f"Коммита «{revision}» нет в этом репозитории. Проверьте хеш или название "
                f"ветки; если коммит пришёл из удалённой ветки, сначала выполните git fetch."
            )

        if await self._revision_exists(repository_path, base):
            return (
                f"У коммита {base} нет предыдущего — это первый коммит в истории, "
                f"и сравнивать его не с чем."
            )

        return (
            f"Коммита {base} нет в этом репозитории, поэтому «{revision}» не разрешается. "
            f"Проверьте хеш; если коммит пришёл из удалённой ветки, выполните git fetch."
        )

    async def _revision_exists(self, repository_path: Path, revision: str) -> bool:
        try:
            await self._run(repository_path, "rev-parse", "--verify", f"{revision}^{{commit}}")
        except VcsOperationError:
            return False
        return True

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

    async def get_staged_patch(self, repository_path: Path) -> str:
        """Дифф проиндексированных изменений относительно HEAD."""
        return await self._run(repository_path, "diff", *DIFF_ARGUMENTS, "--cached")

    async def get_commit_subject(self, repository_path: Path, revision: str) -> str | None:
        """Первая строка сообщения коммита.

        Подпись дела, а не его содержимое: не разрешилась ревизия — дело
        останется без подписи, но заводиться от этого не перестанет.
        """
        try:
            subject = await self._run(repository_path, "log", "-1", "--format=%s", revision)
        except VcsOperationError:
            return None
        return subject.strip() or None

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

    async def grep(
        self,
        repository_path: Path,
        *,
        revision: str,
        pattern: str,
        regexp: bool = False,
        limit: int = 100,
    ) -> list[GrepHit]:
        """Ищет строки в ревизии, а не в рабочей копии.

        Ревизия названа явно по той же причине, по которой её называет индекс:
        ответ должен описывать зафиксированное состояние, иначе повторный
        прогон читает другой код и объяснить расхождение нечем (D-021).
        """
        arguments = [
            "grep",
            "--no-color",
            "-I",
            "-n",
            "-E" if regexp else "-F",
            f"-m{MATCHES_PER_FILE}",
        ]
        arguments.extend(["-e", pattern, revision])

        output = await self._run(
            repository_path,
            *arguments,
            tolerated_returncodes=(GREP_NO_MATCHES,),
        )
        return _parse_grep(output, revision=revision, limit=limit)

    async def list_tree(self, repository_path: Path, revision: str) -> dict[str, ContentHash]:
        """Файлы ревизии с хешами их содержимого.

        Хеш объекта git считается по содержимому, поэтому совпадение с прошлым
        снапшотом означает, что файл не менялся, — и читать его незачем.
        Подмодули и символические ссылки пропускаются: разбирать там нечего.
        """
        output = await self._run(
            repository_path,
            "ls-tree",
            "-r",
            "--full-tree",
            f"--format={TREE_FORMAT}",
            revision,
        )

        tree: dict[str, ContentHash] = {}
        for line in output.splitlines():
            mode, _, remainder = line.partition(" ")
            object_hash, _, path = remainder.partition(" ")
            if mode in REGULAR_FILE_MODES and path:
                tree[path] = ContentHash(object_hash)
        return tree

    async def _run(
        self,
        repository_path: Path,
        *arguments: str,
        tolerated_returncodes: tuple[int, ...] = (),
    ) -> str:
        if not repository_path.exists():
            raise RepositoryPathError(f"Каталог репозитория не найден: {repository_path}")

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

        if process.returncode != 0 and process.returncode not in tolerated_returncodes:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise VcsOperationError(f"git {' '.join(arguments)} завершился с ошибкой: {message}")

        return stdout.decode("utf-8", errors="replace")


def _parse_grep(output: str, *, revision: str, limit: int) -> list[GrepHit]:
    """Разбирает выдачу вида `ревизия:путь:строка:текст`.

    Путь и текст режутся по первым двум двоеточиям после ревизии, а не по
    всем: двоеточия встречаются и в пути, и — постоянно — в самой строке кода.
    """
    prefix = f"{revision}:"
    hits: list[GrepHit] = []

    for line in output.splitlines():
        if not line.startswith(prefix):
            continue

        remainder = line[len(prefix) :]
        path, _, tail = remainder.partition(":")
        number, _, text = tail.partition(":")
        if not path or not number.isdigit():
            continue

        hits.append(GrepHit(path=path, line_number=int(number), text=text))
        if len(hits) >= limit:
            break

    return hits
