from dataclasses import (
    dataclass,
)
from typing import (
    Protocol,
)

from ducktective.core.indexing.value_objects import (
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


class SymbolReader(Protocol):
    """Чтение символов и их окружения по графу."""

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

    async def callees(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        limit: int = 20,
    ) -> list[SymbolContext]:
        """То, что вызывает изменённый код: сигнатуры и контракты."""
        ...

    async def callers(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        limit: int = 20,
    ) -> list[SymbolContext]:
        """Кто вызывает изменённый код — ответ на вопрос «что сломается»."""
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
