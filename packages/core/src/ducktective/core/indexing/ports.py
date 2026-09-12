from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Protocol,
)

from ducktective.core.indexing.entities import (
    CodeChunk,
    CodeSymbol,
    IndexSnapshot,
    SourceFile,
    SymbolEdge,
)
from ducktective.core.indexing.value_objects import (
    EdgeKind,
)
from ducktective.core.types import (
    CodeChunkId,
    CodeSymbolId,
    ContentHash,
    EmbeddingModelId,
    IndexSnapshotId,
    QualifiedName,
    RepositoryId,
)


@dataclass(frozen=True, kw_only=True)
class SymbolReference:
    """Ссылка символа на имя, встреченная при разборе.

    Имя уже развёрнуто по импортам модуля, насколько это возможно статически.
    Привязка к конкретному символу происходит позже: цель может лежать
    в файле, который ещё не разобран.
    """

    source_symbol_id: CodeSymbolId
    kind: EdgeKind
    target_name: QualifiedName
    confidence: float = 1.0


@dataclass(frozen=True, kw_only=True)
class ParsedFile:
    """Разбор одного файла: что в нём объявлено и что попадёт в поиск."""

    symbols: list[CodeSymbol] = field(default_factory=list)
    chunks: list[CodeChunk] = field(default_factory=list)
    references: list[SymbolReference] = field(default_factory=list)


class CodeParser(Protocol):
    """Разбор исходного файла на символы и чанки.

    Реализация привязана к языку: грамматика, правила именования и границы
    определений у каждого свои.
    """

    def supports(self, language: str | None) -> bool: ...

    def parse(self, *, path: str, content: str) -> ParsedFile: ...


class Embedder(Protocol):
    """Превращает текст в вектор.

    Модель всегда локальная: эмбеддинг требует отправки самого кода, и для
    репозитория под NDA внешний сервис исключён без оговорок.
    """

    @property
    def name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True, kw_only=True)
class VectorCoverage:
    """Сколько фрагментов репозитория уже имеет вектор.

    Векторы считаются отдельным шагом после символов и графа: недоступность
    модели не должна оставлять репозиторий без индекса вовсе. Из этого следует
    состояние, которое надо уметь показать — символы готовы, поиск по смыслу
    ещё нет.
    """

    chunks: int = 0
    embedded: int = 0

    @property
    def is_complete(self) -> bool:
        return self.embedded >= self.chunks


@dataclass(frozen=True, kw_only=True)
class IndexTotals:
    """Сколько всего в индексе репозитория: файлов, символов, фрагментов, связей."""

    files: int = 0
    symbols: int = 0
    chunks: int = 0
    edges: int = 0


class EmbeddingStore(Protocol):
    """Хранилище векторов.

    Векторы отделены от чанков: при переезде на другую модель два набора
    держатся параллельно, и их можно честно сравнить на одном индексе.
    """

    async def register_model(self, name: str, dimensions: int) -> EmbeddingModelId: ...

    async def count_coverage(self, repository_id: RepositoryId, model: str) -> VectorCoverage:
        """Считает, у скольких фрагментов есть вектор названной модели.

        Поиск по смыслу ищет только по векторам активной модели, поэтому
        векторы других моделей покрытием не считаются.
        """
        ...

    async def missing_chunks(
        self,
        repository_id: RepositoryId,
        model_id: EmbeddingModelId,
    ) -> list[tuple[CodeChunkId, ContentHash, str]]:
        """Чанки без вектора: идентификатор, хеш содержимого и текст."""
        ...

    async def reuse_by_hash(
        self,
        repository_id: RepositoryId,
        model_id: EmbeddingModelId,
    ) -> int:
        """Копирует готовые векторы чанкам с тем же содержимым.

        Одинаковый код встречается чаще, чем кажется: перемещённый файл,
        вынесенный хелпер, повторяющийся шаблон. Считать для него вектор
        заново — трата, которой легко избежать.
        """
        ...

    async def store(
        self,
        model_id: EmbeddingModelId,
        vectors: list[tuple[CodeChunkId, list[float]]],
    ) -> None: ...


class IndexSnapshotRepository(Protocol):
    """Доступ к агрегату IndexSnapshot. Транзакцию не фиксирует."""

    def add(self, snapshot: IndexSnapshot) -> None: ...

    async def get(self, snapshot_id: IndexSnapshotId) -> IndexSnapshot: ...

    async def find_latest_ready(self, repository_id: RepositoryId) -> IndexSnapshot | None:
        """Снапшот, против которого можно работать прямо сейчас."""
        ...

    async def find_latest(self, repository_id: RepositoryId) -> IndexSnapshot | None:
        """Последний снапшот в любом состоянии.

        Нужен интерфейсу: пока индексация идёт или упала, готового снапшота
        нет, но человеку надо показать именно это, а не «индекс не собран».
        """
        ...

    async def remove_for_repository(self, repository_id: RepositoryId) -> int:
        """Стирает индекс репозитория целиком, оставляя сам репозиторий.

        Инкрементальность опирается на хеши уже разобранных файлов, поэтому
        сменившиеся правила разбора или чанкинга новым прогоном не применятся:
        неизменившийся файл не перечитывается. Стереть и собрать заново —
        единственный способ применить их ко всей базе.

        Возвращает число удалённых снапшотов.
        """
        ...


class SourceFileRepository(Protocol):
    """Доступ к агрегату SourceFile."""

    def add(self, source_file: SourceFile) -> None: ...

    async def find_by_path(self, repository_id: RepositoryId, path: str) -> SourceFile | None: ...

    async def load_many(
        self,
        repository_id: RepositoryId,
        paths: list[str],
    ) -> dict[str, SourceFile]:
        """Загружает файлы пачкой.

        При индексации их тысячи, и запрос на каждый превращает запись
        в тысячи обращений к базе.
        """
        ...

    async def count_totals(self, repository_id: RepositoryId) -> IndexTotals:
        """Итоги по неудалённым файлам репозитория; связи считает репозиторий рёбер."""
        ...

    async def list_paths(self, repository_id: RepositoryId) -> dict[str, str]:
        """Путь → хеш содержимого для всех живых файлов репозитория.

        Инкрементальная индексация сверяет хеши, а не читает файлы целиком,
        поэтому загружать здесь агрегаты незачем.
        """
        ...


class SymbolEdgeRepository(Protocol):
    """Доступ к рёбрам графа символов.

    Рёбра пересекают границы файлов, поэтому не принадлежат ни одному агрегату
    и заменяются пачкой при переразборе файла-источника.
    """

    async def replace_for_symbols(
        self,
        repository_id: RepositoryId,
        symbol_ids: list[CodeSymbolId],
        edges: list[SymbolEdge],
    ) -> None: ...

    async def refresh_statistics(self) -> None:
        """Просит хранилище пересчитать статистику по таблицам графа.

        Нужна перед замыканием рёбер: план этого запроса зависит от того,
        сколько строк хранилище считает существующими, а после массовой
        записи оно об этом ещё не знает.
        """
        ...

    async def count_resolved(self, repository_id: RepositoryId) -> int:
        """Сколько рёбер репозитория связано с определением."""
        ...

    async def resolve_pending(self, repository_id: RepositoryId) -> int:
        """Привязывает висящие рёбра к символам с подходящим именем.

        Ребро на ещё не разобранный файл создаётся неразрешённым; когда файл
        доходит до индексации, ссылка замыкается без переразбора источника.
        Возвращает число связанных рёбер.
        """
        ...
