from dataclasses import (
    dataclass,
)
from typing import (
    Protocol,
)

from ducktective.core.indexing.value_objects import (
    EdgeKind,
    SymbolKind,
)
from ducktective.core.retrieval.context import (
    DiffContext,
)
from ducktective.core.review.entities import (
    ReviewFile,
)
from ducktective.core.types import (
    CodeChunkId,
    CodeSymbolId,
    QualifiedName,
    RepositoryId,
)


@dataclass(frozen=True, kw_only=True)
class ChunkHit:
    """Найденный фрагмент кода вместе с тем, откуда он взят."""

    chunk_id: CodeChunkId
    symbol_id: CodeSymbolId | None
    path: str
    breadcrumb: str
    content: str
    start_line: int
    end_line: int
    score: float


@dataclass(frozen=True, kw_only=True)
class SymbolHit:
    symbol_id: CodeSymbolId
    qualified_name: QualifiedName
    kind: SymbolKind
    path: str
    start_line: int
    end_line: int
    signature: str | None
    score: float


@dataclass(frozen=True, kw_only=True)
class SymbolContext:
    """Символ вместе с его текстом и местом в файле."""

    symbol_id: CodeSymbolId
    qualified_name: QualifiedName
    kind: SymbolKind
    path: str
    start_line: int
    end_line: int
    signature: str | None
    docstring: str | None
    text: str


CALL_EDGES = (EdgeKind.CALLS,)
"""Вид связи, о котором спрашивают «кто вызывает».

Выделен постоянной, потому что раньше подразумевался: обход брал соседей
по любому ребру, а ответ подписывался вызовом. Наследник, импортёр
и декоратор попадали в список того, что сломается от правки сигнатуры,
хотя сигнатуру они не вызывают.
"""


@dataclass(frozen=True, kw_only=True)
class RelatedSymbol:
    """Сосед по графу вместе с видом связи.

    Вид едет рядом с символом, а не остаётся в запросе: «наследует»,
    «импортирует» и «вызывает» — доказательства разной силы и разного
    смысла, и подписать их одним словом значит выдать одно за другое.
    """

    context: SymbolContext
    kind: EdgeKind
    is_resolved: bool


class SymbolReader(Protocol):
    """Чтение проиндексированного кода: символы, граф и строки файлов.

    Строки здесь же, а не отдельным портом: содержимое лежит в тех же
    чанках, из которых собирается текст символа, и разводить два порта
    по одной таблице значило бы плодить сущности ради названия.
    """

    async def symbols_covering(
        self,
        repository_id: RepositoryId,
        path: str,
        start_line: int,
        end_line: int,
    ) -> list[SymbolContext]:
        """Символы, пересекающиеся с изменёнными строками.

        Точка входа ретривала от диффа: ханк превращается не в «строки 40–52»,
        а в «метод ReportBuilder.build».
        """
        ...

    async def find_paths(
        self,
        repository_id: RepositoryId,
        needle: str,
        *,
        limit: int = 5,
    ) -> list[str]:
        """Пути проиндексированных файлов, оканчивающиеся на переданный кусок.

        В индексе путь лежит относительно корня репозитория, а человек
        называет файл так, как видит его у себя: абсолютным путём из
        редактора, куском с середины, одним именем. Поиск по концу пути
        сводит все три случая к одному и не требует от спрашивающего
        знать, где у репозитория корень.
        """
        ...

    async def find_by_name(
        self,
        repository_id: RepositoryId,
        name: str,
        *,
        limit: int = 10,
    ) -> list[SymbolContext]:
        """Символы, названные этим именем.

        Точка входа ретривала от имени, а не от диффа: внешний клиент знает
        `ReviewRun.add_finding`, но не знает ни файла, ни строк. Совпадение
        по полному имени точнее совпадения по последнему сегменту, поэтому
        порядок выдачи задаёт точность совпадения, а не релевантность.
        """
        ...

    async def symbols_in_file(
        self,
        repository_id: RepositoryId,
        path: str,
        *,
        limit: int = 200,
    ) -> list[SymbolContext]:
        """Символы файла по порядку, без тел.

        Оглавление: что в файле есть и где. Тела не подтягиваются намеренно —
        на файле в тысячу строк они вытеснят из окна всё остальное, а вопрос
        здесь другой: с чего начать чтение.
        """
        ...

    async def read_lines(
        self,
        repository_id: RepositoryId,
        path: str,
        *,
        start_line: int,
        end_line: int,
    ) -> str | None:
        """Строки файла как строки, без привязки к символам.

        Там, где символов нет — миграция, файл настроек, шаблон, — обход
        по графу отвечает пустотой, и прочитать написанное нечем.
        """
        ...

    async def search_symbols(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 10,
    ) -> list[SymbolHit]:
        """Символы, чьи имена похожи на запрос.

        Отличается от `find_by_name` тем же, чем поиск отличается от
        разрешения имени: спрашивающий помнит слово, а не полное имя.
        """
        ...

    async def callees(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        kinds: tuple[EdgeKind, ...] = CALL_EDGES,
        limit: int = 20,
    ) -> list[SymbolContext]:
        """То, что вызывает изменённый код: сигнатуры и контракты."""
        ...

    async def callers(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        kinds: tuple[EdgeKind, ...] = CALL_EDGES,
        limit: int = 20,
    ) -> list[SymbolContext]:
        """Кто вызывает изменённый код — ответ на вопрос «что сломается»."""
        ...

    async def referring(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        kinds: tuple[EdgeKind, ...] = (),
        limit: int = 20,
    ) -> list[RelatedSymbol]:
        """Все, кто ссылается на символ, вместе с видом ссылки.

        Направление одно — входящее: спрашивают о последствиях правки,
        а что символ делает сам, видно из его тела. Пустой перечень видов
        означает «любая связь», и тогда ответ разнороден по построению —
        поэтому вид приходит с каждым соседом.
        """
        ...

    async def edge_kinds(self, symbol_ids: list[CodeSymbolId]) -> dict[EdgeKind, int]:
        """Сколько входящих связей каждого вида есть у символа.

        Нужно, чтобы отфильтрованный ответ не выглядел исчерпывающим:
        «вызывающих нет» при трёх наследниках — правда, которая читается
        как «этот код никому не нужен».
        """
        ...


class ContextBuilder(Protocol):
    """Сборка контекста вокруг изменений файла.

    Объявлен здесь, а не рядом с реализацией: use case ревью зависит от того,
    что контекст можно собрать, но не от того, чем он собирается.
    """

    async def build(self, repository_id: RepositoryId, file: ReviewFile) -> DiffContext: ...


class ChunkSearch(Protocol):
    """Любой источник фрагментов кода.

    Слиянию всё равно, откуда пришёл список — по словам или по смыслу, —
    поэтому оно зависит только от этого метода.
    """

    async def search_chunks(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 20,
    ) -> list[ChunkHit]: ...


class LexicalSearch(ChunkSearch, Protocol):
    """Поиск по словам.

    На коде он регулярно выигрывает у векторного: имена функций, константы
    и поля — точные строки, и эмбеддинг их размывает.
    """

    async def search_symbols(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 20,
    ) -> list[SymbolHit]: ...
