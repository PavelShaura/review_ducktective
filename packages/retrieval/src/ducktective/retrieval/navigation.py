from ducktective.core.retrieval.navigation import (
    CodeFragment,
    CodeNavigator,
    FragmentRole,
    NavigationAnswer,
    NavigationSource,
    clip_code,
)
from ducktective.core.retrieval.ports import (
    ChunkHit,
    ChunkSearch,
    SymbolContext,
    SymbolReader,
)
from ducktective.core.types import (
    RepositoryId,
)


class IndexedCodeNavigator:
    """Навигация по собранному индексу: граф символов и гибридный поиск.

    Определение приходит телом, а вызывающие — контрактом: чтобы понять, что
    сломается от правки, нужны место вызова и сигнатура, а телом два десятка
    вызывающих вытеснили бы всё остальное.
    """

    source = NavigationSource.INDEX

    def __init__(
        self,
        repository_id: RepositoryId,
        *,
        symbols: SymbolReader,
        search: ChunkSearch,
    ) -> None:
        self._repository_id = repository_id
        self._symbols = symbols
        self._search = search

    async def search_code(self, query: str, *, limit: int = 10) -> NavigationAnswer:
        hits = await self._search.search_chunks(self._repository_id, query, limit=limit)
        return NavigationAnswer(
            source=self.source,
            fragments=tuple(_from_chunk(hit) for hit in hits),
        )

    async def get_definition(self, name: str, *, limit: int = 5) -> NavigationAnswer:
        found = await self._symbols.find_by_name(self._repository_id, name, limit=limit)
        return NavigationAnswer(
            source=self.source,
            fragments=tuple(_definition(context) for context in found),
            note=_ambiguity_note(name, len(found)),
        )

    async def find_callers(self, name: str, *, limit: int = 20) -> NavigationAnswer:
        targets = await self._symbols.find_by_name(self._repository_id, name)
        if not targets:
            return NavigationAnswer(source=self.source)

        callers = await self._symbols.callers(
            [context.symbol_id for context in targets],
            limit=limit,
        )
        return NavigationAnswer(
            source=self.source,
            fragments=tuple(_contract(context, FragmentRole.CALLER) for context in callers),
        )

    async def get_file_context(
        self,
        path: str,
        *,
        start_line: int,
        end_line: int,
        limit: int = 10,
    ) -> NavigationAnswer:
        covering = await self._symbols.symbols_covering(
            self._repository_id,
            path,
            start_line,
            end_line,
        )
        if not covering:
            return NavigationAnswer(
                source=self.source,
                note=f"В {path}:{start_line}-{end_line} проиндексированных символов нет",
            )

        symbol_ids = [context.symbol_id for context in covering]
        callees = await self._symbols.callees(symbol_ids, limit=limit)
        callers = await self._symbols.callers(symbol_ids, limit=limit)

        return NavigationAnswer(
            source=self.source,
            fragments=(
                *(_definition(context) for context in covering),
                *(_contract(context, FragmentRole.CALLEE) for context in callees),
                *(_contract(context, FragmentRole.CALLER) for context in callers),
            ),
        )


class IndexedNavigators:
    """Навигаторы по индексу — по одному на репозиторий."""

    def __init__(self, *, symbols: SymbolReader, search: ChunkSearch) -> None:
        self._symbols = symbols
        self._search = search

    def for_repository(self, repository_id: RepositoryId) -> CodeNavigator:
        return IndexedCodeNavigator(
            repository_id,
            symbols=self._symbols,
            search=self._search,
        )


def _from_chunk(hit: ChunkHit) -> CodeFragment:
    return CodeFragment(
        path=hit.path,
        start_line=hit.start_line,
        end_line=hit.end_line,
        text=clip_code(hit.content.rstrip()),
        role=FragmentRole.MATCH,
        title=hit.breadcrumb,
    )


def _definition(context: SymbolContext) -> CodeFragment:
    return CodeFragment(
        path=context.path,
        start_line=context.start_line,
        end_line=context.end_line,
        text=clip_code(context.text.rstrip() or context.signature or ""),
        title=f"{context.qualified_name} · {context.kind.value}",
    )


def _contract(context: SymbolContext, role: FragmentRole) -> CodeFragment:
    """Сосед по графу приходит контрактом, а не телом.

    От него нужно, что он обещает и где лежит: телом один крупный класс
    вытеснил бы из ответа всех остальных.
    """
    body = context.signature or str(context.qualified_name)
    if context.docstring:
        body = f"{body}\n{context.docstring}"

    return CodeFragment(
        path=context.path,
        start_line=context.start_line,
        end_line=context.end_line,
        text=clip_code(body.rstrip()),
        role=role,
        title=f"{context.qualified_name} · {context.kind.value}",
    )


def _ambiguity_note(name: str, found: int) -> str | None:
    """Одноимённые символы возвращаются все, и об этом стоит сказать.

    Иначе спрашивающий читает первый попавшийся как единственный и делает
    вывод о классе, которого не имел в виду.
    """
    if found <= 1:
        return None
    return f"Символов с именем «{name}» несколько: {found}"
