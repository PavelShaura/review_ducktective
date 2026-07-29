from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.retrieval.views import (
    CodeMatchView,
    SymbolNeighbourhoodView,
    SymbolView,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.retrieval.ports import (
    ChunkHit,
    ChunkSearch,
    SymbolContext,
    SymbolReader,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


class SearchCode:
    """Поиск по проиндексированному коду репозитория.

    Гибрид слов и смысла берётся целиком: на именах выигрывает лексика,
    на описании намерения — вектор, и выбирать за спрашивающего нечем.
    """

    def __init__(self, unit_of_work: UnitOfWork, search: ChunkSearch) -> None:
        self._unit_of_work = unit_of_work
        self._search = search

    async def execute(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 10,
    ) -> list[CodeMatchView]:
        await _ensure_owned(self._unit_of_work, tenant_id, repository_id)

        hits = await self._search.search_chunks(repository_id, query, limit=limit)
        return [_match(hit) for hit in hits]


class GetSymbolDefinition:
    """Определение символа по имени.

    Имя может быть неоднозначным — одноимённые методы разных классов, —
    поэтому возвращается список, а не одна запись: выбор оставлен тому,
    кто спрашивал, и он видит, из чего выбирает.
    """

    def __init__(self, unit_of_work: UnitOfWork, symbols: SymbolReader) -> None:
        self._unit_of_work = unit_of_work
        self._symbols = symbols

    async def execute(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        name: str,
        *,
        limit: int = 5,
    ) -> list[SymbolView]:
        await _ensure_owned(self._unit_of_work, tenant_id, repository_id)

        found = await self._symbols.find_by_name(repository_id, name, limit=limit)
        return [_symbol(context) for context in found]


class FindSymbolCallers:
    """Кто вызывает символ — ответ на вопрос «что сломается, если его тронуть».

    Вызывающие приходят контрактом без тела: чтобы оценить последствия правки,
    нужно место вызова и сигнатура, а не реализация каждого из них.
    """

    def __init__(self, unit_of_work: UnitOfWork, symbols: SymbolReader) -> None:
        self._unit_of_work = unit_of_work
        self._symbols = symbols

    async def execute(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        name: str,
        *,
        limit: int = 20,
    ) -> list[SymbolView]:
        await _ensure_owned(self._unit_of_work, tenant_id, repository_id)

        targets = await self._symbols.find_by_name(repository_id, name)
        if not targets:
            return []

        callers = await self._symbols.callers(
            [context.symbol_id for context in targets],
            limit=limit,
        )
        return [_contract(context) for context in callers]


class GetFileContext:
    """Окружение участка файла: его символы и их соседи по графу.

    Участок задаётся строками, а отвечает use case символами: вопрос «что тут
    происходит» решается определением метода, а не выпиской строк, которую
    спрашивающий может получить и сам, открыв файл.
    """

    def __init__(self, unit_of_work: UnitOfWork, symbols: SymbolReader) -> None:
        self._unit_of_work = unit_of_work
        self._symbols = symbols

    async def execute(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        path: str,
        *,
        start_line: int,
        end_line: int,
        neighbours_limit: int = 10,
    ) -> SymbolNeighbourhoodView:
        await _ensure_owned(self._unit_of_work, tenant_id, repository_id)

        covering = await self._symbols.symbols_covering(
            repository_id,
            path,
            start_line,
            end_line,
        )
        if not covering:
            return SymbolNeighbourhoodView(
                path=path,
                start_line=start_line,
                end_line=end_line,
            )

        symbol_ids = [context.symbol_id for context in covering]
        callees = await self._symbols.callees(symbol_ids, limit=neighbours_limit)
        callers = await self._symbols.callers(symbol_ids, limit=neighbours_limit)

        return SymbolNeighbourhoodView(
            path=path,
            start_line=start_line,
            end_line=end_line,
            symbols=tuple(_symbol(context) for context in covering),
            callees=tuple(_contract(context) for context in callees),
            callers=tuple(_contract(context) for context in callers),
        )


async def _ensure_owned(
    unit_of_work: UnitOfWork,
    tenant_id: TenantId,
    repository_id: RepositoryId,
) -> None:
    async with unit_of_work:
        repository = await unit_of_work.code_repositories.get(repository_id)
        if repository.tenant_id != tenant_id:
            raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")


def _match(hit: ChunkHit) -> CodeMatchView:
    return CodeMatchView(
        path=hit.path,
        breadcrumb=hit.breadcrumb,
        start_line=hit.start_line,
        end_line=hit.end_line,
        content=hit.content,
        score=hit.score,
    )


def _symbol(context: SymbolContext) -> SymbolView:
    return SymbolView(
        qualified_name=context.qualified_name,
        kind=context.kind,
        path=context.path,
        start_line=context.start_line,
        end_line=context.end_line,
        signature=context.signature,
        docstring=context.docstring,
        text=context.text,
    )


def _contract(context: SymbolContext) -> SymbolView:
    return SymbolView(
        qualified_name=context.qualified_name,
        kind=context.kind,
        path=context.path,
        start_line=context.start_line,
        end_line=context.end_line,
        signature=context.signature,
        docstring=context.docstring,
        text="",
    )
