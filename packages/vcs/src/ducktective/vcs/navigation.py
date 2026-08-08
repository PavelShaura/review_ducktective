import re
from pathlib import (
    Path,
)

from ducktective.core.exceptions import (
    VcsOperationError,
)
from ducktective.core.retrieval.navigation import (
    CodeFragment,
    FragmentRole,
    NavigationAnswer,
    NavigationSource,
    clip_code,
)
from ducktective.vcs.git_provider import (
    GrepHit,
    LocalGitProvider,
)


SEARCH_CONTEXT_LINES = 2
DEFINITION_LINES = 40
FILE_CONTEXT_MARGIN = 20

DEFINITION_KEYWORDS = ("def", "class", "func", "function", "struct", "interface", "type")
DEFINITION_NOTE = (
    "Индекс не собран: определение найдено поиском по словам, "
    "и границы показанного участка приблизительны"
)
SEARCH_NOTE = "Индекс не собран: поиск лексический, по совпадению строки в ревизии"
CALLERS_NOTE = (
    "Индекс не собран: вызывающие найдены поиском по имени. "
    "Однофамильцы из других классов сюда тоже попадают, а вызовы через "
    "переменную — нет"
)


class GitCodeNavigator:
    """Навигация по ревизии средствами git — режим без индекса.

    Отвечает на те же вопросы, что и навигатор по индексу, и заметно грубее:
    вместо графа вызовов — совпадение имени, вместо границ символа — окно
    строк. Разница названа в каждом ответе, потому что читающему её видно
    только оттуда: пустая выдача грепа и пустой обход графа выглядят
    одинаково, а значат разное (D-021).

    Читается зафиксированная ревизия, а не рабочая копия: eval-прогон обязан
    повторяться, а недописанный код не обязан попадать в чужую подсказку.
    """

    source = NavigationSource.GIT

    def __init__(
        self,
        repository_path: Path,
        revision: str,
        *,
        git: LocalGitProvider,
    ) -> None:
        self._repository_path = repository_path
        self._revision = revision
        self._git = git

    async def search_code(self, query: str, *, limit: int = 10) -> NavigationAnswer:
        hits = await self._grep(query, limit=limit)
        if not hits:
            return NavigationAnswer(source=self.source, note=SEARCH_NOTE)

        return NavigationAnswer(
            source=self.source,
            fragments=await self._windows(
                hits,
                before=SEARCH_CONTEXT_LINES,
                after=SEARCH_CONTEXT_LINES,
                role=FragmentRole.MATCH,
            ),
            note=SEARCH_NOTE,
        )

    async def get_definition(self, name: str, *, limit: int = 5) -> NavigationAnswer:
        short_name = _short_name(name)
        pattern = rf"({'|'.join(DEFINITION_KEYWORDS)})[[:space:]]+{re.escape(short_name)}\b"

        hits = await self._grep(pattern, limit=limit, regexp=True)
        if not hits:
            hits = await self._grep(short_name, limit=limit)
        if not hits:
            return NavigationAnswer(source=self.source, note=DEFINITION_NOTE)

        return NavigationAnswer(
            source=self.source,
            fragments=await self._windows(
                hits,
                before=1,
                after=DEFINITION_LINES,
                role=FragmentRole.DEFINITION,
            ),
            note=DEFINITION_NOTE,
        )

    async def find_callers(self, name: str, *, limit: int = 20) -> NavigationAnswer:
        short_name = _short_name(name)

        hits = await self._grep(f"{short_name}(", limit=limit)
        callers = [hit for hit in hits if not _is_definition(hit.text, short_name)]
        if not callers:
            return NavigationAnswer(source=self.source, note=CALLERS_NOTE)

        return NavigationAnswer(
            source=self.source,
            fragments=await self._windows(
                callers,
                before=1,
                after=1,
                role=FragmentRole.CALLER,
            ),
            note=CALLERS_NOTE,
        )

    async def get_file_context(
        self,
        path: str,
        *,
        start_line: int,
        end_line: int,
        limit: int = 10,
    ) -> NavigationAnswer:
        lines = await self._read(path)
        if lines is None:
            return NavigationAnswer(
                source=self.source,
                note=f"Файла {path} в ревизии {self._revision[:8]} нет",
            )

        fragment = _window(
            path,
            lines,
            start_line=start_line - FILE_CONTEXT_MARGIN,
            end_line=end_line + FILE_CONTEXT_MARGIN,
        )
        return NavigationAnswer(source=self.source, fragments=(fragment,))

    async def _grep(
        self,
        pattern: str,
        *,
        limit: int,
        regexp: bool = False,
    ) -> list[GrepHit]:
        try:
            return await self._git.grep(
                self._repository_path,
                revision=self._revision,
                pattern=pattern,
                regexp=regexp,
                limit=limit,
            )
        except VcsOperationError:
            return []

    async def _read(self, path: str) -> list[str] | None:
        content = await self._git.get_file_content(
            self._repository_path,
            revision=self._revision,
            path=path,
        )
        if content is None:
            return None
        return content.splitlines()

    async def _windows(
        self,
        hits: list[GrepHit],
        *,
        before: int,
        after: int,
        role: FragmentRole,
    ) -> tuple[CodeFragment, ...]:
        """Разворачивает совпадения в участки файлов.

        Файл читается один раз на все свои совпадения: git show — отдельный
        процесс, и звать его на каждую строку значило бы платить за каждую
        находку в одном и том же файле.
        """
        files: dict[str, list[str] | None] = {}
        fragments = []

        for hit in hits:
            if hit.path not in files:
                files[hit.path] = await self._read(hit.path)

            lines = files[hit.path]
            if lines is None:
                continue

            fragments.append(
                _window(
                    hit.path,
                    lines,
                    start_line=hit.line_number - before,
                    end_line=hit.line_number + after,
                    role=role,
                )
            )

        return tuple(fragments)


class GitNavigators:
    """Навигаторы по ревизиям — по одному на прогон.

    Провайдер git один на приложение, а ревизия у каждого прогона своя.
    """

    def __init__(self, *, git: LocalGitProvider) -> None:
        self._git = git

    def for_revision(self, repository_path: Path, revision: str) -> GitCodeNavigator:
        return GitCodeNavigator(repository_path, revision, git=self._git)


def _window(
    path: str,
    lines: list[str],
    *,
    start_line: int,
    end_line: int,
    role: FragmentRole = FragmentRole.DEFINITION,
) -> CodeFragment:
    first = max(1, start_line)
    last = min(len(lines), end_line)
    return CodeFragment(
        path=path,
        start_line=first,
        end_line=last,
        text=clip_code("\n".join(lines[first - 1 : last]).rstrip()),
        role=role,
    )


def _short_name(name: str) -> str:
    """Последний сегмент имени.

    Греп не знает о принадлежности символа классу: `ReviewRun.add_finding`
    в коде так не пишется нигде, кроме вызова через экземпляр.
    """
    return name.rsplit(".", maxsplit=1)[-1]


def _is_definition(text: str, name: str) -> bool:
    """Само определение вызовом не является.

    Строка `async def` — то же определение: без снятия приставки метод
    оказывался бы в списке собственных вызывающих.
    """
    stripped = text.strip().removeprefix("async ")
    return any(stripped.startswith(f"{keyword} {name}") for keyword in DEFINITION_KEYWORDS)
