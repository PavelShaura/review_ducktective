import re
from collections import (
    Counter,
)
from fnmatch import (
    fnmatch,
)
from pathlib import (
    Path,
    PurePosixPath,
)

from ducktective.core.exceptions import (
    VcsOperationError,
)
from ducktective.core.retrieval.navigation import (
    CodeFragment,
    FragmentRole,
    NavigationAnswer,
    NavigationSource,
    ReferenceRelation,
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
NO_INDEX_REASON = "индекса нет"

DEFINITION_NOTE = (
    "определение найдено поиском по словам, и границы показанного участка приблизительны"
)
SEARCH_NOTE = "поиск лексический, по совпадению строки в ревизии"
CALLERS_NOTE = (
    "вызывающие найдены поиском по имени. Однофамильцы из других классов сюда тоже "
    "попадают, а вызовы через переменную — нет"
)
REFERENCES_NOTE = (
    "ссылки найдены поиском по словам: вид связи угадан по форме строки, а не взят "
    "из графа, поэтому наследник через промежуточный класс сюда не попадёт"
)

NAMES_NOTE = "имена найдены по строкам определений, тела не читались"

DOCUMENTATION_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
DOC_SEARCH_WIDENING = 4
"""Во сколько раз шире искать, чтобы после отбора осталось нужное число.

Греп не умеет спрашивать «только по документации», поэтому отбор идёт
после него, и без запаса выдача схлопывается в ноль на первом же файле
кода, попавшем в совпадения.
"""

DIRECTORY_LIMIT = 12

REFERENCE_PATTERNS = {
    ReferenceRelation.SUBCLASSES: "(class|extends|implements).*\\b{name}\\b",
    ReferenceRelation.IMPORTERS: "(import|from|require).*\\b{name}\\b",
    ReferenceRelation.RAISED_BY: "(raise|throw)[[:space:]]+{name}\\b",
}
"""Чем выглядит связь в строке кода, когда графа нет.

Точности здесь не будет: `class Foo(Bar)` и `class Foo extends Bar` — это
всё, чем наследование отличается от упоминания в тексте. Оговорка едет
с ответом, потому что читающему разницу видно только оттуда (D-021).
"""

RELATION_ROLES = {
    ReferenceRelation.ANY: FragmentRole.RELATED,
    ReferenceRelation.SUBCLASSES: FragmentRole.SUBCLASS,
    ReferenceRelation.IMPORTERS: FragmentRole.IMPORTER,
    ReferenceRelation.RAISED_BY: FragmentRole.RAISER,
}


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
        reason: str = NO_INDEX_REASON,
    ) -> None:
        self._repository_path = repository_path
        self._revision = revision
        self._git = git
        self._reason = reason

    def _note(self, detail: str) -> str:
        """Оговорка вместе с причиной, по которой отвечает не индекс."""
        return f"{self._reason.capitalize()}: {detail}"

    async def search_code(self, query: str, *, limit: int = 10) -> NavigationAnswer:
        hits = await self._grep(query, limit=limit)
        if not hits:
            return NavigationAnswer(source=self.source, note=self._note(SEARCH_NOTE))

        return NavigationAnswer(
            source=self.source,
            fragments=await self._windows(
                hits,
                before=SEARCH_CONTEXT_LINES,
                after=SEARCH_CONTEXT_LINES,
                role=FragmentRole.MATCH,
            ),
            note=self._note(SEARCH_NOTE),
        )

    async def get_definition(self, name: str, *, limit: int = 5) -> NavigationAnswer:
        short_name = _short_name(name)
        pattern = rf"({'|'.join(DEFINITION_KEYWORDS)})[[:space:]]+{re.escape(short_name)}\b"

        hits = await self._grep(pattern, limit=limit, regexp=True)
        if not hits:
            hits = await self._grep(short_name, limit=limit)
        if not hits:
            return NavigationAnswer(source=self.source, note=self._note(DEFINITION_NOTE))

        return NavigationAnswer(
            source=self.source,
            fragments=await self._windows(
                hits,
                before=1,
                after=DEFINITION_LINES,
                role=FragmentRole.DEFINITION,
            ),
            note=self._note(DEFINITION_NOTE),
        )

    async def find_callers(self, name: str, *, limit: int = 20) -> NavigationAnswer:
        short_name = _short_name(name)

        hits = await self._grep(f"{short_name}(", limit=limit)
        callers = [hit for hit in hits if not _is_definition(hit.text, short_name)]
        if not callers:
            return NavigationAnswer(source=self.source, note=self._note(CALLERS_NOTE))

        return NavigationAnswer(
            source=self.source,
            fragments=await self._windows(
                callers,
                before=1,
                after=1,
                role=FragmentRole.CALLER,
            ),
            note=self._note(CALLERS_NOTE),
        )

    async def find_references(
        self,
        name: str,
        *,
        relation: ReferenceRelation = ReferenceRelation.ANY,
        limit: int = 20,
    ) -> NavigationAnswer:
        """Ссылки, узнанные по форме строки.

        Без графа вид связи не хранится нигде, и различить его можно только
        тем, как строка написана. Перечень операций от этого не меняется —
        меняется точность, и она названа в ответе.
        """
        short_name = _short_name(name)
        template = REFERENCE_PATTERNS.get(relation)

        if template is None:
            hits = await self._grep(short_name, limit=limit)
        else:
            pattern = template.format(name=re.escape(short_name))
            hits = await self._grep(pattern, limit=limit, regexp=True)

        found = [hit for hit in hits if not _is_definition(hit.text, short_name)]
        if not found:
            return NavigationAnswer(source=self.source, note=self._note(REFERENCES_NOTE))

        return NavigationAnswer(
            source=self.source,
            fragments=await self._windows(
                found,
                before=1,
                after=1,
                role=RELATION_ROLES[relation],
            ),
            note=self._note(REFERENCES_NOTE),
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

    async def read_file(
        self,
        path: str,
        *,
        start_line: int,
        end_line: int,
    ) -> NavigationAnswer:
        """Строки файла из ревизии.

        Единственная операция, где режим без индекса точнее индексного:
        git отдаёт файл как он есть, а индекс — собранный из чанков.
        """
        lines = await self._read(path)
        if lines is None:
            return NavigationAnswer(
                source=self.source,
                note=f"Файла {path} в ревизии {self._revision[:8]} нет",
            )

        return NavigationAnswer(
            source=self.source,
            fragments=(
                _window(
                    path,
                    lines,
                    start_line=start_line,
                    end_line=end_line,
                    role=FragmentRole.SOURCE,
                ),
            ),
        )

    async def get_file_outline(self, path: str, *, limit: int = 60) -> NavigationAnswer:
        """Оглавление, собранное по строкам определений.

        Без разбора языка граница определения не известна, поэтому строки
        показываются как есть: их номер и текст. Вложенность видна отступом,
        каким её написал автор файла.
        """
        lines = await self._read(path)
        if lines is None:
            return NavigationAnswer(
                source=self.source,
                note=f"Файла {path} в ревизии {self._revision[:8]} нет",
            )

        found = [
            f"  {number}  {line.strip()}"
            for number, line in enumerate(lines, start=1)
            if _starts_definition(line)
        ][:limit]

        if not found:
            return NavigationAnswer(
                source=self.source,
                note=self._note(f"строк с определениями в {path} не нашлось"),
            )

        listed = "\n".join(found)
        return NavigationAnswer(
            source=self.source,
            note=self._note(f"оглавление {path} собрано по строкам определений:\n{listed}"),
        )

    async def find_symbol(self, query: str, *, limit: int = 10) -> NavigationAnswer:
        """Имена, найденные грепом по строкам определений."""
        pattern = rf"({'|'.join(DEFINITION_KEYWORDS)})[[:space:]]+[A-Za-z_]*{re.escape(query)}"
        hits = await self._grep(pattern, limit=limit, regexp=True)
        if not hits:
            return NavigationAnswer(
                source=self.source,
                note=self._note(f"определений, похожих на «{query}», не нашлось"),
            )

        return NavigationAnswer(
            source=self.source,
            note=self._note(NAMES_NOTE),
            fragments=tuple(
                CodeFragment(
                    path=hit.path,
                    start_line=hit.line_number,
                    end_line=hit.line_number,
                    text=clip_code(hit.text.strip()),
                    role=FragmentRole.NAME,
                )
                for hit in hits
            ),
        )

    async def project_docs(self, query: str, *, limit: int = 5) -> NavigationAnswer:
        """Поиск по документации грепом, с отбором по расширению файла."""
        hits = await self._grep(query, limit=limit * DOC_SEARCH_WIDENING)
        found = [hit for hit in hits if _is_documentation(hit.path)][:limit]
        if not found:
            return NavigationAnswer(
                source=self.source,
                note=self._note(f"в документации про «{query}» ничего не нашлось"),
            )

        return NavigationAnswer(
            source=self.source,
            fragments=await self._windows(
                found,
                before=SEARCH_CONTEXT_LINES,
                after=SEARCH_CONTEXT_LINES,
                role=FragmentRole.MATCH,
            ),
            note=self._note(SEARCH_NOTE),
        )

    async def describe_repository(self) -> NavigationAnswer:
        """Сводка по ревизии: сколько файлов и каких, где они лежат."""
        try:
            tree = await self._git.list_tree(self._repository_path, self._revision)
        except Exception as error:
            return NavigationAnswer(
                source=self.source, note=f"Не удалось прочитать ревизию: {error}"
            )

        if not tree:
            return NavigationAnswer(
                source=self.source, note=f"В ревизии {self._revision[:8]} файлов нет"
            )

        extensions = Counter(PurePosixPath(path).suffix or "без расширения" for path in tree)
        directories = Counter(
            path.split("/", maxsplit=1)[0] if "/" in path else "/" for path in tree
        )

        listed_kinds = ", ".join(
            f"{name} — {total}" for name, total in extensions.most_common(DIRECTORY_LIMIT)
        )
        listed_directories = "\n".join(
            f"  {name} — {total}" for name, total in directories.most_common(DIRECTORY_LIMIT)
        )
        return NavigationAnswer(
            source=self.source,
            note=self._note(
                f"файлов {len(tree)}.\nПо виду: {listed_kinds}\n"
                f"Каталоги верхнего уровня:\n{listed_directories}"
            ),
        )

    async def list_files(self, pattern: str, *, limit: int = 40) -> NavigationAnswer:
        """Файлы ревизии, подходящие под образец.

        Перечень берётся у git, а не с диска: рабочая копия может обгонять
        ревизию, о которой идёт разговор, и показать в ней файл, которого
        в обсуждаемом коде нет.
        """
        try:
            tree = await self._git.list_tree(self._repository_path, self._revision)
        except Exception as error:
            return NavigationAnswer(
                source=self.source, note=f"Не удалось прочитать ревизию: {error}"
            )

        found = sorted(path for path in tree if _matches(path, pattern))
        if not found:
            return NavigationAnswer(
                source=self.source,
                note=self._note(f"файлов по образцу «{pattern}» в ревизии нет"),
            )

        shown = found[:limit]
        tail = f", показаны первые {limit} из {len(found)}" if len(found) > limit else ""
        listed = "\n".join(shown)
        return NavigationAnswer(
            source=self.source,
            note=f"Файлы по образцу «{pattern}»{tail}:\n{listed}",
        )

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

    def for_revision(
        self,
        repository_path: Path,
        revision: str,
        *,
        reason: str = NO_INDEX_REASON,
    ) -> GitCodeNavigator:
        return GitCodeNavigator(repository_path, revision, git=self._git, reason=reason)


def _matches(path: str, pattern: str) -> bool:
    """Подходит ли путь под образец: расширение, звёздочка или кусок пути."""
    cleaned = pattern.strip().lstrip("/")
    if not cleaned:
        return False
    if "*" in cleaned:
        return fnmatch(path, cleaned if "/" in cleaned else f"*{cleaned}")
    if cleaned.startswith("."):
        return path.endswith(cleaned)
    return path == cleaned or path.endswith(f"/{cleaned}") or cleaned in path


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
        text="\n".join(lines[first - 1 : last]).rstrip(),
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


def _starts_definition(line: str) -> bool:
    """Похожа ли строка на начало определения."""
    stripped = line.strip().removeprefix("async ")
    return any(stripped.startswith(f"{keyword} ") for keyword in DEFINITION_KEYWORDS)


def _is_documentation(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in DOCUMENTATION_SUFFIXES
